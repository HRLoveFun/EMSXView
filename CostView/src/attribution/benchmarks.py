"""
Benchmarks computation for attribution metrics.

Pulls 1-minute bars from raw_bdib.db and computes per-fill:
  - arrival_px      : mid (close) of the first bar at/after route's first fill time
  - interval_vwap   : volume-weighted bar VWAP across [first_fill, last_fill] on route
  - mid_at_fill     : close of bar covering fill minute
  - mid_fill_plus_N : close of bar at fill_minute + N min, for N in reversal_windows

Strategy: batch by (order_as_of_date). For each date load ALL bars for the
distinct tickers traded on that date, build per-ticker mid_series + vwap_volume
DataFrame, then iterate that date's fills.

raw_bdib row (relevant cols):
    equ_ticker TEXT, order_as_of_date TEXT (YYYYMMDD), mkt_timestamp TEXT (HH:MM:SS),
    open, high, low, close, vwap, volume

Notes
-----
- We do NOT have NBBO; mid_at_fill is approximated by bar close.
- order_as_of_date in raw_bdib aligns with processed_fills.order_as_of_date.
- mkt_timestamp for many bars is HH:MM:00 (1-min grid). Some entries are
  intra-minute (e.g. '09:30:10') from auctions; we floor fill time to minute
  before lookup.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# DB paths
# ----------------------------------------------------------------------------
_THIS = Path(__file__).resolve()
_COSTVIEW_ROOT = _THIS.parents[2]
RAW_BDIB_DB = _COSTVIEW_ROOT / "data" / "raw_bdib.db"
PROCESSED_FILLS_DB = _COSTVIEW_ROOT / "data" / "processed_fills.db"


@dataclass(frozen=True)
class BarPanel:
    """Per-ticker bar series for one trading day.

    raw_bdib bars are sub-minute (10s grid). We keep two views:
    - `mid_by_minute`: floor-to-minute -> last close in that minute (for spot
      mid lookups; sub-minute order preserves auction prints by 'last' wins).
    - `bars`: DataFrame with all bars indexed by floored 'HH:MM' string,
      columns ['close','volume']. Used for interval VWAP integration where we
      need every share of volume.

    raw_bdib.vwap is unreliable (all NULL on observed dates) so we ignore it
    and treat `close` as the trade-price proxy.
    """
    mid_by_minute: pd.Series
    bars: pd.DataFrame  # cols: close, volume; index: minute str


# ----------------------------------------------------------------------------
# Bar loading
# ----------------------------------------------------------------------------
def _floor_to_minute(hms: str) -> str:
    """'09:30:10' -> '09:30'. Returns '' on malformed input."""
    if not hms:
        return ""
    parts = str(hms).split(":")
    if len(parts) < 2:
        return ""
    return parts[0].zfill(2) + ":" + parts[1].zfill(2)


def load_bar_panels_for_date(
    bdib_conn: sqlite3.Connection,
    yyyymmdd: str,
    tickers: Iterable[str],
) -> Dict[str, BarPanel]:
    """Return {equ_ticker: BarPanel} for the requested tickers on a single date.

    Tickers absent from raw_bdib are simply omitted (caller will mark
    data_quality_flags).
    """
    tickers = sorted(set(t for t in tickers if t))
    if not tickers:
        return {}

    out: Dict[str, BarPanel] = {}
    CHUNK = 500
    for i in range(0, len(tickers), CHUNK):
        batch = tickers[i:i + CHUNK]
        placeholders = ",".join(["?"] * len(batch))
        sql = (
            f"SELECT equ_ticker, mkt_timestamp, close, volume "
            f"FROM raw_bdib "
            f"WHERE order_as_of_date = ? "
            f"  AND equ_ticker IN ({placeholders})"
        )
        df = pd.read_sql_query(sql, bdib_conn, params=[yyyymmdd] + batch)
        if df.empty:
            continue
        df["minute"] = df["mkt_timestamp"].apply(_floor_to_minute)
        df = df[df["minute"] != ""]
        # Coerce numerics; close=0 or NaN unusable for mid; volume NaN -> 0.
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
        df = df[(df["close"].notna()) & (df["close"] > 0)]
        if df.empty:
            continue
        df = df.sort_values(["equ_ticker", "mkt_timestamp"])
        for tk, sub in df.groupby("equ_ticker", sort=False):
            # mid_by_minute: take the LAST close in each minute (auction
            # prints come after the regular minute close).
            mid_by_minute = (
                sub.drop_duplicates(subset=["minute"], keep="last")
                   .set_index("minute")["close"]
            )
            bars = sub[["minute", "close", "volume"]].set_index("minute")
            out[tk] = BarPanel(mid_by_minute=mid_by_minute, bars=bars)
    return out


def lookup_mid_at_or_after(panel: BarPanel, minute: str) -> Optional[float]:
    """Return the bar close at `minute`, or the first bar after it if missing.
    None if nothing on/after the requested minute.
    """
    if not minute:
        return None
    s = panel.mid_by_minute
    if minute in s.index:
        v = s[minute]
        if pd.notna(v) and v > 0:
            return float(v)
    later = s.index[s.index >= minute]
    for m in later:
        v = s[m]
        if pd.notna(v) and v > 0:
            return float(v)
    return None


def add_minutes(minute: str, n: int) -> str:
    """Add n minutes to 'HH:MM'; clamps within the same trading day window
    [00:00, 23:59]. Returns '' if input invalid.
    """
    if not minute or len(minute) != 5 or minute[2] != ":":
        return ""
    try:
        h = int(minute[:2])
        m = int(minute[3:])
    except ValueError:
        return ""
    total = h * 60 + m + int(n)
    total = max(0, min(total, 23 * 60 + 59))
    return f"{total // 60:02d}:{total % 60:02d}"


def interval_vwap(panel: BarPanel, start_minute: str, end_minute: str) -> Optional[float]:
    """Volume-weighted bar price over [start, end] (inclusive).

    raw_bdib.vwap is unreliable, so we use bar `close` as the trade-price proxy:
        VWAP_proxy = sum(close * volume) / sum(volume)
    Includes ALL sub-minute bars in the interval (do NOT pre-dedup).
    """
    if not start_minute or not end_minute or end_minute < start_minute:
        return None
    bars = panel.bars
    mask = (bars.index >= start_minute) & (bars.index <= end_minute)
    if not mask.any():
        return None
    sub = bars[mask]
    sub = sub[(sub["volume"] > 0) & (sub["close"] > 0)]
    if sub.empty:
        return None
    total_vol = float(sub["volume"].sum())
    if total_vol <= 0:
        return None
    return float((sub["close"] * sub["volume"]).sum() / total_vol)


def interval_volume(panel: BarPanel, start_minute: str, end_minute: str) -> Optional[float]:
    """Total bar volume over [start, end] (inclusive).

    Used to compute participation_rate = route_shares / interval_volume.
    None if the panel covers no bars in the interval or volume is 0.
    """
    if not start_minute or not end_minute or end_minute < start_minute:
        return None
    bars = panel.bars
    mask = (bars.index >= start_minute) & (bars.index <= end_minute)
    if not mask.any():
        return None
    sub = bars[mask]
    sub = sub[sub["volume"] > 0]
    if sub.empty:
        return None
    total = float(sub["volume"].sum())
    if total <= 0:
        return None
    return total


# ----------------------------------------------------------------------------
# Fills + route-context loaders
# ----------------------------------------------------------------------------
def load_fills_for_date(
    fills_conn: sqlite3.Connection,
    yyyymmdd: str,
) -> pd.DataFrame:
    """Pull fills + route ticker/side context for a single order_as_of_date.

    Returns columns:
      OrderId, RouteId, FillId, order_as_of_date, mkt_timestamp,
      Broker, algo, FillPrice, FillShares, RouteShares, Exchange,
      equ_ticker, Side
    """
    sql = """
    SELECT pf.OrderId, pf.RouteId, pf.FillId, pf.order_as_of_date,
           pf.mkt_timestamp, pf.Broker, pf.algo,
           pf.FillPrice, pf.FillShares, pf.RouteShares, pf.Exchange,
           rr.equ_ticker, rr.Side
    FROM processed_fills pf
    LEFT JOIN route_registry rr
      ON rr.OrderId = pf.OrderId AND rr.RouteId = pf.RouteId
    WHERE pf.order_as_of_date = ?
      AND pf.ExecType = 'FILL'
      AND pf.FillShares > 0
      AND pf.FillPrice > 0
    """
    return pd.read_sql_query(sql, fills_conn, params=(yyyymmdd,))


def compute_route_arrival_minutes(fills_df: pd.DataFrame) -> pd.DataFrame:
    """For each (OrderId, RouteId), compute first/last fill MINUTE strings.

    Returns DataFrame indexed by (OrderId, RouteId) with columns
    'first_minute', 'last_minute'.
    """
    df = fills_df.copy()
    df["minute"] = df["mkt_timestamp"].apply(_floor_to_minute)
    df = df[df["minute"] != ""]
    grp = df.groupby(["OrderId", "RouteId"], sort=False)["minute"].agg(["min", "max"])
    grp.columns = ["first_minute", "last_minute"]
    return grp

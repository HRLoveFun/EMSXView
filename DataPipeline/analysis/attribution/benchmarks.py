"""Pure-algorithm benchmark computations for attribution metrics.

This module contains ONLY pure functions and data structures that operate
on in-memory data (BarPanel, DataFrames). All database access has been
migrated to repositories.py.

Functions provided:
  - BarPanel: per-ticker bar data container
  - _floor_to_minute: timestamp truncation helper
  - lookup_mid_at_or_after: find bar close at/after a given minute
  - add_minutes: minute arithmetic within [00:00, 23:59]
  - interval_vwap: volume-weighted price over a time interval
  - interval_volume: total bar volume over a time interval
  - compute_route_arrival_minutes: first/last fill minute per route
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


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


# Bar loading has been migrated to repositories.py (SqliteBarDataRepository).
# Use FillRepository.get_fills_for_date() for fills queries.
# Use BarDataRepository.get_bar_panels_for_date() for bar panel queries.


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


# ---------------------------------------------------------------------------
# Route context helpers (pure computation)
# ---------------------------------------------------------------------------
# Fills loading has been migrated to repositories.py (SqliteFillRepository).
# Use FillRepository.get_fills_for_date() for fills queries.


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

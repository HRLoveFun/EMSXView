"""
Stage 7a: load per-market daily index/vol features into daily_market_index.

Bloomberg fields used (per market):
  - benchmark_index:  PX_LAST, TURNOVER, MOV_AVG_30D, MOV_AVG_50D, MOV_AVG_200D, RSI_30D
  - vol_index:        PX_LAST  (the value, e.g. VIX = 14.3)
  - VOLATILITY_20D / VOLATILITY_60D: from benchmark
Derived (NOT a Bloomberg mnemonic):
  - high_252d, low_252d: rolling 252-day max/min of benchmark PX_LAST

Markets without a vol_index get vol_index_value=NULL; downstream vol_regime
degrades to realized-vol classification.

Idempotent: UPSERT on (market_code, trade_date).
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from DataPipeline.analysis.regime.schema import (
    REGIME_DB_PATH,
    SCHEMA_VERSION,
    connect,
    ensure_schema_current,
)

logger = logging.getLogger(__name__)

# Bloomberg field set fetched per benchmark.
BENCHMARK_FIELDS: List[str] = [
    "PX_LAST",
    "TURNOVER",
    "VOLATILITY_20D",
    "VOLATILITY_60D",
    "MOV_AVG_30D",
    "MOV_AVG_50D",
    "MOV_AVG_200D",
    "RSI_30D",
]
VOL_INDEX_FIELDS: List[str] = ["PX_LAST"]
ROLLING_WINDOW_252D: int = 252


@dataclass(frozen=True)
class _MarketRef:
    market_code: str
    benchmark: str
    vol_index: Optional[str]


def _load_markets(db_path: Path) -> List[_MarketRef]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT market_code, benchmark, vol_index FROM ref_market_mapping ORDER BY market_code"
        ).fetchall()
    finally:
        conn.close()
    return [_MarketRef(r[0], r[1], r[2]) for r in rows]


def _xbbg_fetcher(ticker: str, fields: List[str], start: dt.date, end: dt.date) -> pd.DataFrame:
    """Default Bloomberg fetcher (lazy-imports xbbg)."""
    from xbbg import blp  # noqa: WPS433
    df = blp.bdh(tickers=ticker, flds=fields,
                 start_date=start.strftime("%Y-%m-%d"),
                 end_date=end.strftime("%Y-%m-%d"))
    if df.empty:
        return pd.DataFrame(columns=fields)
    # xbbg returns MultiIndex columns (ticker, field) — flatten.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[1].upper() for c in df.columns]
    else:
        df.columns = [str(c).upper() for c in df.columns]
    df.index = pd.to_datetime(df.index).date
    return df


# Public type alias for injection (tests pass stubs).
FetcherType = Callable[[str, List[str], dt.date, dt.date], pd.DataFrame]


def load_market_index(
    start_date: str,
    end_date: str,
    db_path: Path = REGIME_DB_PATH,
    fetcher: Optional[FetcherType] = None,
    source_version: Optional[str] = None,
) -> int:
    """Load benchmark + vol index features for all markets in [start_date, end_date].

    Returns rows upserted.
    """
    ensure_schema_current(db_path)
    markets = _load_markets(db_path)
    if not markets:
        logger.warning("ref_market_mapping is empty; nothing to load")
        return 0

    fetcher = fetcher or _xbbg_fetcher
    src_version = source_version or f"xbbg+rolling252@{dt.date.today().isoformat()}"
    ingested_at = dt.datetime.now().isoformat(timespec="seconds")
    start = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)
    # Pull 1 extra year for the rolling 252-day high/low at the left edge.
    fetch_start = start - dt.timedelta(days=400)

    all_rows: List[tuple] = []
    for m in markets:
        try:
            bench_df = fetcher(m.benchmark, BENCHMARK_FIELDS, fetch_start, end)
        except Exception as e:
            logger.warning(f"  [{m.market_code}] benchmark fetch failed: {e}")
            continue
        if bench_df.empty:
            continue

        # Rolling 252d high/low on PX_LAST.
        if "PX_LAST" in bench_df.columns:
            bench_df["HIGH_252D"] = bench_df["PX_LAST"].rolling(ROLLING_WINDOW_252D, min_periods=20).max()
            bench_df["LOW_252D"] = bench_df["PX_LAST"].rolling(ROLLING_WINDOW_252D, min_periods=20).min()

        vol_series: Optional[pd.Series] = None
        if m.vol_index:
            try:
                vix_df = fetcher(m.vol_index, VOL_INDEX_FIELDS, fetch_start, end)
                if not vix_df.empty and "PX_LAST" in vix_df.columns:
                    vol_series = vix_df["PX_LAST"]
            except Exception as e:
                logger.warning(f"  [{m.market_code}] vol_index fetch failed: {e}")

        # Trim to the requested window.
        bench_df = bench_df.loc[(bench_df.index >= start) & (bench_df.index <= end)]
        for d, row in bench_df.iterrows():
            all_rows.append((
                m.market_code,
                d.isoformat(),
                _f(row.get("PX_LAST")),
                _f(vol_series.get(d)) if vol_series is not None else None,
                _f(row.get("TURNOVER")),
                _f(row.get("VOLATILITY_20D")),
                _f(row.get("VOLATILITY_60D")),
                _f(row.get("MOV_AVG_30D")),
                _f(row.get("MOV_AVG_50D")),
                _f(row.get("MOV_AVG_200D")),
                _f(row.get("RSI_30D")),
                _f(row.get("HIGH_252D")),
                _f(row.get("LOW_252D")),
                src_version,
                ingested_at,
            ))

    if not all_rows:
        logger.info("no rows produced")
        return 0

    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Batch in chunks of 5000 (skill rule §6).
        for i in range(0, len(all_rows), 5000):
            batch = all_rows[i:i + 5000]
            conn.executemany(
                """
                INSERT INTO daily_market_index (
                    market_code, trade_date, px_last, vol_index_value, turnover,
                    vol_20d, vol_60d, mov_avg_30d, mov_avg_50d, mov_avg_200d,
                    rsi_30d, high_252d, low_252d, source_version, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market_code, trade_date) DO UPDATE SET
                    px_last         = excluded.px_last,
                    vol_index_value = excluded.vol_index_value,
                    turnover        = excluded.turnover,
                    vol_20d         = excluded.vol_20d,
                    vol_60d         = excluded.vol_60d,
                    mov_avg_30d     = excluded.mov_avg_30d,
                    mov_avg_50d     = excluded.mov_avg_50d,
                    mov_avg_200d    = excluded.mov_avg_200d,
                    rsi_30d         = excluded.rsi_30d,
                    high_252d       = excluded.high_252d,
                    low_252d        = excluded.low_252d,
                    source_version  = excluded.source_version,
                    ingested_at     = excluded.ingested_at
                """,
                batch,
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    logger.info(f"daily_market_index: upserted {len(all_rows)} rows")
    return len(all_rows)


def _f(v) -> Optional[float]:
    """Return float or None for NaN/missing."""
    if v is None:
        return None
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None

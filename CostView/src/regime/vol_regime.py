"""
Stage 7b: classify daily volatility regime per (market_code, trade_date, config_version).

Methods supported (config.vol_method):
  - 'vix_absolute'        : classify by absolute vol_index_value (VIX-style).
                            Markets where vol_index_value is NULL are AUTO-DEGRADED
                            to realized_vol_zscore on a per-market basis (method
                            column records the actual method used per row).
  - 'realized_vol_zscore' : z-score of vol_20d vs trailing 60-day window per market.

Output: daily_vol_regime  (regime ∈ {low,normal,high,extreme})
Idempotent: UPSERT on PK.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from CostView.src.regime.config import get_active_config, get_config
from CostView.src.regime.schema import REGIME_DB_PATH, connect, ensure_schema_current

logger = logging.getLogger(__name__)

# When degrading from vix_absolute -> realized_vol_zscore, pull this many extra
# days of history so the trailing 60-day window has data at the left edge.
_ZSCORE_LOOKBACK_DAYS = 90


def _classify_vix_absolute(value: Optional[float], thr: Dict) -> str:
    if value is None or pd.isna(value):
        return "normal"
    if value < thr["low"]:
        return "low"
    if value < thr["normal"]:
        return "normal"
    if value < thr["high"]:
        return "high"
    return "extreme"


def _classify_zscore(z: Optional[float]) -> str:
    if z is None or pd.isna(z):
        return "normal"
    if z < -1.0:
        return "low"
    if z < 1.0:
        return "normal"
    if z < 2.0:
        return "high"
    return "extreme"


def classify(
    start_date: str,
    end_date: str,
    db_path: Path = REGIME_DB_PATH,
    config_version: Optional[str] = None,
) -> int:
    """Classify daily vol regime for [start_date, end_date]. Returns rows upserted."""
    ensure_schema_current(db_path)
    cfg = get_config(config_version, db_path) if config_version else get_active_config(db_path)
    if not cfg:
        raise RuntimeError("No active regime config; run ensure_default_config() first")

    method = cfg["vol_method"]
    thresholds = cfg["vol_thresholds"]
    version_id = cfg["version_id"]
    ingested_at = dt.datetime.now().isoformat(timespec="seconds")

    # For zscore (whether requested or as a degradation fallback), we need
    # extra history before start_date so the rolling 60d window has data.
    fetch_start_iso = (
        dt.date.fromisoformat(start_date) - dt.timedelta(days=_ZSCORE_LOOKBACK_DAYS)
    ).isoformat()

    conn = connect(db_path)
    try:
        df = pd.read_sql_query(
            """SELECT market_code, trade_date, vol_index_value, vol_20d
               FROM daily_market_index
               WHERE trade_date BETWEEN ? AND ?
               ORDER BY market_code, trade_date""",
            conn,
            params=(fetch_start_iso, end_date),
        )
    finally:
        conn.close()

    if df.empty:
        logger.info("daily_market_index empty for range")
        return 0

    rows: List[tuple] = []
    in_range = (df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)

    if method == "vix_absolute":
        # Per-market degradation: markets with no vol_index_value at all in
        # the loaded window fall back to realized_vol_zscore on vol_20d.
        for mc, group in df.groupby("market_code"):
            has_vix = group["vol_index_value"].notna().any()
            if has_vix:
                used_method = "vix_absolute"
                src_version = f"{used_method}@{version_id}"
                for _i, r in group[in_range.loc[group.index]].iterrows():
                    v = r["vol_index_value"]
                    regime = _classify_vix_absolute(v, thresholds)
                    rows.append((mc, r["trade_date"], version_id, regime,
                                 _f(v), used_method, src_version, ingested_at))
            else:
                used_method = "realized_vol_zscore"  # auto-degraded
                src_version = f"{used_method}@{version_id}(degraded)"
                g = group.sort_values("trade_date").copy()
                mean = g["vol_20d"].rolling(60, min_periods=10).mean()
                std = g["vol_20d"].rolling(60, min_periods=10).std()
                g["zscore"] = (g["vol_20d"] - mean) / std
                logger.info(f"  [{mc}] vol_index_value all-null -> degraded to realized_vol_zscore")
                for _i, r in g[in_range.loc[g.index]].iterrows():
                    regime = _classify_zscore(r["zscore"])
                    rows.append((mc, r["trade_date"], version_id, regime,
                                 _f(r["zscore"]), used_method, src_version, ingested_at))
    elif method == "realized_vol_zscore":
        used_method = "realized_vol_zscore"
        src_version = f"{used_method}@{version_id}"
        for mc, group in df.groupby("market_code"):
            g = group.sort_values("trade_date").copy()
            mean = g["vol_20d"].rolling(60, min_periods=10).mean()
            std = g["vol_20d"].rolling(60, min_periods=10).std()
            g["zscore"] = (g["vol_20d"] - mean) / std
            for _i, r in g[in_range.loc[g.index]].iterrows():
                regime = _classify_zscore(r["zscore"])
                rows.append((mc, r["trade_date"], version_id, regime,
                             _f(r["zscore"]), used_method, src_version, ingested_at))
    else:
        raise ValueError(f"Unknown vol_method: {method!r}")

    return _upsert(db_path, rows)


def _upsert(db_path: Path, rows: List[tuple]) -> int:
    if not rows:
        return 0
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for i in range(0, len(rows), 5000):
            conn.executemany(
                """INSERT INTO daily_vol_regime
                   (market_code, trade_date, config_version, vol_regime, vol_score,
                    method, source_version, ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(market_code, trade_date, config_version) DO UPDATE SET
                       vol_regime     = excluded.vol_regime,
                       vol_score      = excluded.vol_score,
                       method         = excluded.method,
                       source_version = excluded.source_version,
                       ingested_at    = excluded.ingested_at""",
                rows[i:i + 5000],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    logger.info(f"daily_vol_regime: upserted {len(rows)} rows")
    return len(rows)


def _f(v):
    if v is None or pd.isna(v):
        return None
    return float(v)

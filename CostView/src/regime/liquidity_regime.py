"""
Stage 7c: classify daily liquidity regime per (market_code, trade_date, config_version).

Method (config.liq_method):
  - 'turnover_zscore' : z-score of TURNOVER vs trailing N-day window.
                        thresholds: {"thin": -1.0, "thick": 1.0, "lookback_days": 60}

Output: daily_liquidity_regime (regime ∈ {thin, normal, thick})
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import List, Optional

import pandas as pd

from CostView.src.regime.config import get_active_config, get_config
from CostView.src.regime.schema import REGIME_DB_PATH, connect, ensure_schema_current

logger = logging.getLogger(__name__)


def _classify(z, thin: float, thick: float) -> str:
    if z is None or pd.isna(z):
        return "normal"
    if z < thin:
        return "thin"
    if z > thick:
        return "thick"
    return "normal"


def classify(
    start_date: str,
    end_date: str,
    db_path: Path = REGIME_DB_PATH,
    config_version: Optional[str] = None,
) -> int:
    ensure_schema_current(db_path)
    cfg = get_config(config_version, db_path) if config_version else get_active_config(db_path)
    if not cfg:
        raise RuntimeError("No active regime config; run ensure_default_config() first")

    method = cfg["liq_method"]
    thr = cfg["liq_thresholds"]
    version_id = cfg["version_id"]
    src_version = f"{method}@{version_id}"
    ingested_at = dt.datetime.now().isoformat(timespec="seconds")

    if method != "turnover_zscore":
        raise ValueError(f"Unknown liq_method: {method!r}")

    lookback = int(thr.get("lookback_days", 60))
    conn = connect(db_path)
    try:
        df = pd.read_sql_query(
            """SELECT market_code, trade_date, turnover
               FROM daily_market_index
               WHERE trade_date BETWEEN ? AND ?
               ORDER BY market_code, trade_date""",
            conn,
            params=(start_date, end_date),
        )
    finally:
        conn.close()

    if df.empty:
        return 0

    rows: List[tuple] = []
    for mc, group in df.groupby("market_code"):
        g = group.sort_values("trade_date").copy()
        mean = g["turnover"].rolling(lookback, min_periods=10).mean()
        std = g["turnover"].rolling(lookback, min_periods=10).std()
        g["z"] = (g["turnover"] - mean) / std
        for _i, r in g.iterrows():
            regime = _classify(r["z"], thr["thin"], thr["thick"])
            z = None if (r["z"] is None or pd.isna(r["z"])) else float(r["z"])
            rows.append((mc, r["trade_date"], version_id,
                         regime, z, method, src_version, ingested_at))

    if not rows:
        return 0

    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for i in range(0, len(rows), 5000):
            conn.executemany(
                """INSERT INTO daily_liquidity_regime
                   (market_code, trade_date, config_version, liq_regime, turnover_zscore,
                    method, source_version, ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(market_code, trade_date, config_version) DO UPDATE SET
                       liq_regime      = excluded.liq_regime,
                       turnover_zscore = excluded.turnover_zscore,
                       method          = excluded.method,
                       source_version  = excluded.source_version,
                       ingested_at     = excluded.ingested_at""",
                rows[i:i + 5000],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    logger.info(f"daily_liquidity_regime: upserted {len(rows)} rows")
    return len(rows)

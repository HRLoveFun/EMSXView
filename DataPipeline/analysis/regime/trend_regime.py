"""
Stage 7d: classify daily trend regime per (market_code, trade_date, config_version).

Method 'ma_rsi_combo' (default):
  Inputs: px_last, mov_avg_50d, mov_avg_200d, rsi_30d, high_252d
  Derived: dist_52w_high_pct = (px_last - high_252d) / high_252d  (≤ 0)

  Rules (first match wins):
    - dist_52w_high_pct >= dist_high_uptrend_pct AND px_last > mov_avg_50d > mov_avg_200d
                                                                          → 'uptrend'
    - rsi_30d < rsi_low AND px_last < mov_avg_50d < mov_avg_200d           → 'downtrend'
    - else                                                                  → 'range'

Output: daily_trend_regime (regime ∈ {downtrend, range, uptrend})
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import List, Optional

import pandas as pd

from DataPipeline.analysis.regime.config import get_active_config, get_config
from DataPipeline.analysis.regime.schema import REGIME_DB_PATH, connect, ensure_schema_current

logger = logging.getLogger(__name__)


def _safe(v):
    return None if (v is None or pd.isna(v)) else float(v)


def _classify(px, ma50, ma200, rsi, dist_high, thr) -> tuple:
    """Return (regime, ma_signal)."""
    px, ma50, ma200, rsi, dist_high = (_safe(x) for x in (px, ma50, ma200, rsi, dist_high))
    ma_signal = "n/a"
    if ma50 is not None and ma200 is not None:
        if ma50 > ma200:
            ma_signal = "ma50>ma200"
        elif ma50 < ma200:
            ma_signal = "ma50<ma200"
        else:
            ma_signal = "ma50=ma200"

    rsi_low = thr.get("rsi_low", 35.0)
    rsi_high = thr.get("rsi_high", 65.0)
    dist_uptrend = thr.get("dist_high_uptrend_pct", -0.10)

    if (px is not None and ma50 is not None and ma200 is not None and dist_high is not None
            and dist_high >= dist_uptrend and px > ma50 > ma200):
        return ("uptrend", ma_signal)
    if (px is not None and ma50 is not None and ma200 is not None and rsi is not None
            and rsi < rsi_low and px < ma50 < ma200):
        return ("downtrend", ma_signal)
    return ("range", ma_signal)


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

    method = cfg["trend_method"]
    thr = cfg["trend_thresholds"]
    version_id = cfg["version_id"]
    src_version = f"{method}@{version_id}"
    ingested_at = dt.datetime.now().isoformat(timespec="seconds")

    if method != "ma_rsi_combo":
        raise ValueError(f"Unknown trend_method: {method!r}")

    conn = connect(db_path)
    try:
        df = pd.read_sql_query(
            """SELECT market_code, trade_date, px_last, mov_avg_50d, mov_avg_200d,
                      rsi_30d, high_252d
               FROM daily_market_index
               WHERE trade_date BETWEEN ? AND ?""",
            conn,
            params=(start_date, end_date),
        )
    finally:
        conn.close()
    if df.empty:
        return 0

    rows: List[tuple] = []
    for _i, r in df.iterrows():
        dist_high = None
        if r["high_252d"] and not pd.isna(r["high_252d"]) and r["high_252d"] != 0:
            dist_high = (r["px_last"] - r["high_252d"]) / r["high_252d"]
        regime, ma_signal = _classify(r["px_last"], r["mov_avg_50d"], r["mov_avg_200d"],
                                       r["rsi_30d"], dist_high, thr)
        rows.append((
            r["market_code"], r["trade_date"], version_id,
            regime, ma_signal, _safe(r["rsi_30d"]), _safe(dist_high),
            method, src_version, ingested_at,
        ))

    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for i in range(0, len(rows), 5000):
            conn.executemany(
                """INSERT INTO daily_trend_regime
                   (market_code, trade_date, config_version, trend_regime, ma_signal,
                    rsi_30d, dist_52w_high_pct, method, source_version, ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(market_code, trade_date, config_version) DO UPDATE SET
                       trend_regime      = excluded.trend_regime,
                       ma_signal         = excluded.ma_signal,
                       rsi_30d           = excluded.rsi_30d,
                       dist_52w_high_pct = excluded.dist_52w_high_pct,
                       method            = excluded.method,
                       source_version    = excluded.source_version,
                       ingested_at       = excluded.ingested_at""",
                rows[i:i + 5000],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    logger.info(f"daily_trend_regime: upserted {len(rows)} rows")
    return len(rows)

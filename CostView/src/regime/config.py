"""
Helpers for audit_regime_config_versions:
- get_active_config(): return the active config row as a dict.
- ensure_default_config(): seed a default 'v0_default' config if none exist
  (safe to call from any stage at startup).

Config JSON shapes (all stored as TEXT in DB, parsed here):

  vol_thresholds_json     {"low": 12, "normal": 18, "high": 25}
                          comparison applied to vol_index_value (e.g. VIX) percentile or absolute level
                          per `vol_method`.
  liq_thresholds_json     {"thin": -1.0, "thick": 1.0}
                          z-score boundaries for daily turnover vs trailing window.
  trend_thresholds_json   {"rsi_low": 35, "rsi_high": 65,
                           "dist_high_breakout_pct": -0.02,
                           "dist_high_uptrend_pct": -0.10}
  time_buckets_json       [{"name": "open_30m",  "start": "+00:00", "end": "+00:30"},
                           {"name": "midday",    "start": "+00:30", "end": "-00:30"},
                           {"name": "close_30m", "start": "-00:30", "end": "+00:00"}]
                          start/end are offsets from session_open (+) or session_close (-).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Dict, Optional

from CostView.src.regime.schema import REGIME_DB_PATH, connect, ensure_schema_current

logger = logging.getLogger(__name__)

DEFAULT_VERSION_ID = "v0_default"


def _row_to_config(row) -> Dict:
    return {
        "version_id": row[0],
        "created_at": row[1],
        "is_active": int(row[2]),
        "vol_method": row[3],
        "vol_thresholds": json.loads(row[4]),
        "liq_method": row[5],
        "liq_thresholds": json.loads(row[6]),
        "trend_method": row[7],
        "trend_thresholds": json.loads(row[8]),
        "time_buckets": json.loads(row[9]),
        "description": row[10],
    }


def get_active_config(db_path: Path = REGIME_DB_PATH) -> Optional[Dict]:
    """Return the currently active config (is_active=1), or None."""
    ensure_schema_current(db_path)
    conn = connect(db_path)
    try:
        row = conn.execute(
            """SELECT version_id, created_at, is_active,
                      vol_method, vol_thresholds_json,
                      liq_method, liq_thresholds_json,
                      trend_method, trend_thresholds_json,
                      time_buckets_json, description
               FROM audit_regime_config_versions WHERE is_active = 1"""
        ).fetchone()
    finally:
        conn.close()
    return _row_to_config(row) if row else None


def get_config(version_id: str, db_path: Path = REGIME_DB_PATH) -> Dict:
    """Return any config by version_id; raise KeyError if missing."""
    conn = connect(db_path)
    try:
        row = conn.execute(
            """SELECT version_id, created_at, is_active,
                      vol_method, vol_thresholds_json,
                      liq_method, liq_thresholds_json,
                      trend_method, trend_thresholds_json,
                      time_buckets_json, description
               FROM audit_regime_config_versions WHERE version_id = ?""",
            (version_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise KeyError(f"config_version {version_id!r} not found")
    return _row_to_config(row)


def ensure_default_config(db_path: Path = REGIME_DB_PATH) -> str:
    """Insert the v0_default config if no active config exists. Returns active version_id."""
    active = get_active_config(db_path)
    if active:
        return active["version_id"]

    payload = (
        DEFAULT_VERSION_ID,
        dt.datetime.now().isoformat(timespec="seconds"),
        1,                                                       # is_active
        "vix_absolute",
        json.dumps({"low": 12.0, "normal": 18.0, "high": 25.0}),
        "turnover_zscore",
        json.dumps({"thin": -1.0, "thick": 1.0, "lookback_days": 60}),
        "ma_rsi_combo",
        json.dumps({
            "rsi_low": 35.0, "rsi_high": 65.0,
            "dist_high_uptrend_pct": -0.10,
        }),
        json.dumps([
            {"name": "open_30m",  "start": "+00:00", "end": "+00:30"},
            {"name": "midday",    "start": "+00:30", "end": "-00:30"},
            {"name": "close_30m", "start": "-00:30", "end": "+00:00"},
        ]),
        "Default config seeded by ensure_default_config()",
    )

    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO audit_regime_config_versions (
                version_id, created_at, is_active,
                vol_method, vol_thresholds_json,
                liq_method, liq_thresholds_json,
                trend_method, trend_thresholds_json,
                time_buckets_json, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            payload,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    logger.info(f"Seeded default config: {DEFAULT_VERSION_ID}")
    return DEFAULT_VERSION_ID

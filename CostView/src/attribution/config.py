"""
Helpers for audit_attribution_config_versions:
- get_active_config(): return the active attribution config row.
- seed_default_config(): seed 'attr_v0' if none exists.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from CostView.src.regime.schema import REGIME_DB_PATH, connect, ensure_schema_current

logger = logging.getLogger(__name__)

DEFAULT_VERSION_ID = "attr_v0"


@dataclass(frozen=True)
class ActiveAttributionConfig:
    version_id: str
    bench_methods: List[str]          # e.g. ['arrival_mid','interval_vwap']
    reversal_windows_min: List[int]   # e.g. [1, 5, 30]
    winsor_pct: float
    adv_window_days: int
    bootstrap_n: int
    min_cell_n: int
    description: Optional[str]


def _row_to_config(row) -> ActiveAttributionConfig:
    return ActiveAttributionConfig(
        version_id=row[0],
        bench_methods=[s.strip() for s in str(row[1]).split(",") if s.strip()],
        reversal_windows_min=[int(x.strip()) for x in str(row[2]).split(",") if x.strip()],
        winsor_pct=float(row[3]),
        adv_window_days=int(row[4]),
        bootstrap_n=int(row[5]),
        min_cell_n=int(row[6]),
        description=row[7],
    )


def get_active_config(db_path: Path = REGIME_DB_PATH) -> Optional[ActiveAttributionConfig]:
    """Return active attribution config (is_active=1), or None."""
    ensure_schema_current(db_path)
    conn = connect(db_path)
    try:
        row = conn.execute(
            """SELECT version_id, bench_methods, reversal_windows_min,
                      winsor_pct, adv_window_days, bootstrap_n, min_cell_n,
                      description
               FROM audit_attribution_config_versions
               WHERE is_active = 1
               LIMIT 1"""
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_config(row)


def seed_default_config(db_path: Path = REGIME_DB_PATH) -> str:
    """Insert 'attr_v0' default config if no rows exist; return active version_id.

    Defaults match user-approved M2 plan:
      arrival_mid + interval_vwap; reversal 1/5/30 min; winsor 1%;
      adv_window 30d; bootstrap 5000; min_cell 30.
    """
    ensure_schema_current(db_path)
    conn = connect(db_path)
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM audit_attribution_config_versions").fetchone()[0]
        if cnt == 0:
            now = dt.datetime.now().isoformat(timespec="seconds")
            conn.execute(
                """INSERT INTO audit_attribution_config_versions
                   (version_id, created_at, is_active, bench_methods,
                    reversal_windows_min, winsor_pct, adv_window_days,
                    bootstrap_n, min_cell_n, description)
                   VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    DEFAULT_VERSION_ID, now,
                    "arrival_mid,interval_vwap",
                    "1,5,30",
                    0.01,
                    30,
                    5000,
                    30,
                    "M2 default: IS+VWAP+reversal(1,5,30m); 1% winsor; 30d ADV; bootstrap 5000.",
                ),
            )
            logger.info("seeded default attribution config: %s", DEFAULT_VERSION_ID)
        active = conn.execute(
            "SELECT version_id FROM audit_attribution_config_versions WHERE is_active=1 LIMIT 1"
        ).fetchone()
        if active is None:
            raise RuntimeError("no active attribution config and seeding failed")
        return active[0]
    finally:
        conn.close()

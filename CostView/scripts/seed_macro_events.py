"""Seed FOMC + CPI events for 2025-09 to 2026-04 into ref_macro_event_calendar.

Idempotent: uses INSERT OR IGNORE on PK (event_date, market_code, event_type).
Run: python -m CostView.scripts.seed_macro_events
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from DataPipeline.analysis.regime.schema import REGIME_DB_PATH

# Real / projected FOMC announcement dates 2025-09 .. 2026-04.
FOMC_DATES = [
    "2025-09-17",
    "2025-10-29",
    "2025-12-10",
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",  # already in DB
]
# US CPI (BLS release calendar) projected.
CPI_DATES = [
    "2025-09-11",
    "2025-10-15",
    "2025-11-13",
    "2025-12-10",
    "2026-01-13",
    "2026-02-11",
    "2026-03-12",
    "2026-04-15",
]

SOURCE_VERSION = "macro.seed/2025-09..2026-04/v1"


def main() -> int:
    conn = sqlite3.connect(str(REGIME_DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON")
    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    for d in FOMC_DATES:
        rows.append((d, "US", "fomc", "high", 1, f"FOMC rate decision ({d})", SOURCE_VERSION, now))
    for d in CPI_DATES:
        rows.append((d, "US", "cpi", "high", 1, f"US CPI release ({d})", SOURCE_VERSION, now))
    conn.executemany(
        """INSERT OR IGNORE INTO ref_macro_event_calendar
           (event_date, market_code, event_type, severity, window_days,
            description, source_file_version, synced_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    n_total = conn.execute(
        "SELECT COUNT(*) FROM ref_macro_event_calendar"
    ).fetchone()[0]
    n_us_high = conn.execute(
        "SELECT COUNT(*) FROM ref_macro_event_calendar "
        "WHERE market_code='US' AND event_type IN ('fomc','cpi')"
    ).fetchone()[0]
    conn.close()
    print(f"seed_macro_events: total rows={n_total}, US fomc+cpi={n_us_high}, "
          f"submitted {len(rows)} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

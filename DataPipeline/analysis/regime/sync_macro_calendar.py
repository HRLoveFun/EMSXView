"""
Sync CostView/data/macro_calendar.csv → ref_macro_event_calendar.

Pipeline:
  1. validate_macro_calendar (fail-fast on any error)
  2. fill blank severity / window_days from ref_macro_event_dict defaults
  3. UPSERT into ref_macro_event_calendar (transactional)

Run after editing the CSV:
    python -m DataPipeline.analysis.regime.sync_macro_calendar
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from DataPipeline.analysis.regime.schema import connect, ensure_schema_current, REGIME_DB_PATH
from DataPipeline.analysis.regime.validate_macro_calendar import (
    DEFAULT_CSV_PATH,
    _iter_data_rows,
    _read_version,
    validate,
)


def _load_event_defaults(db_path: Path) -> Dict[str, Tuple[str, int]]:
    """Return {event_type: (default_severity, default_window_days)}."""
    conn = connect(db_path)
    try:
        return {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT event_type, default_severity, default_window_days "
                "FROM ref_macro_event_dict"
            )
        }
    finally:
        conn.close()


def sync(csv_path: Path = DEFAULT_CSV_PATH,
         db_path: Path = REGIME_DB_PATH,
         strict: bool = True) -> int:
    """Sync csv → ref_macro_event_calendar. Returns rows upserted."""
    errs = validate(csv_path, db_path)
    if errs:
        msg = "\n".join(errs)
        if strict:
            raise ValueError(f"macro_calendar validation failed:\n{msg}")
        print(f"[sync_macro_calendar] WARNING: validation issues:\n{msg}", file=sys.stderr)

    defaults = _load_event_defaults(db_path)
    source_version = _read_version(csv_path)
    synced_at = dt.datetime.now().isoformat(timespec="seconds")

    rows: List[tuple] = []
    for _lineno, row in _iter_data_rows(csv_path):
        et = row["event_type"].strip()
        default_sev, default_win = defaults[et]  # validated upstream
        sev = (row.get("severity") or "").strip() or default_sev
        wd_raw = (row.get("window_days") or "").strip()
        wd = int(wd_raw) if wd_raw else default_win
        rows.append((
            row["event_date"].strip(),
            row["market_code"].strip(),
            et,
            sev,
            wd,
            (row.get("description") or "").strip() or None,
            source_version,
            synced_at,
        ))

    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            """
            INSERT INTO ref_macro_event_calendar (
                event_date, market_code, event_type, severity, window_days,
                description, source_file_version, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_date, market_code, event_type) DO UPDATE SET
                severity            = excluded.severity,
                window_days         = excluded.window_days,
                description         = excluded.description,
                source_file_version = excluded.source_file_version,
                synced_at           = excluded.synced_at
            """,
            rows,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return len(rows)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync macro_calendar.csv → ref_macro_event_calendar")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--db", type=Path, default=REGIME_DB_PATH)
    args = parser.parse_args(argv)
    n = sync(args.csv, args.db)
    print(f"[sync_macro_calendar] upserted {n} events from {args.csv.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

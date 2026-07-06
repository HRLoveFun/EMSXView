"""Reprocess affected dates (Stage2 + Stage3 + Stage4, optional Stage5).

Use cases:
  1. Generic: re-run Stage2-Stage4 for an explicit list of order_as_of_date.
     python scripts/ops/reprocess_affected_dates.py --dates 20251215,20251216
  2. From a cleanup script log: read dates written by cleanup_processed_fills_mismatches.py.
     python scripts/ops/reprocess_affected_dates.py --from-cleanup
  3. Backfill: from the 13 historical source_dates whose raw data was previously
     skipped by Stage2 (one source_date spans multiple order_as_of_date trading days),
     expand to all distinct order_as_of_date and re-run Stage2-Stage4 (optional st5).
     python scripts/ops/reprocess_affected_dates.py --missing-source-dates
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional, Set

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from DataPipeline.config import Config
from DataPipeline.orchestration.core import run_process, run_aggregate, run_order_labels, run_bdib_integration

logger = logging.getLogger(__name__)


def _parse_dates_from_cleanup_output(dates_file=None):
    if dates_file is None:
        dates_file = Config.LOGGING_DIR / ".cleanup_dates.txt"
    if not dates_file.exists():
        return set()
    content = dates_file.read_text(encoding="utf-8").strip()
    if not content:
        return set()
    return {d.strip() for d in content.split(",") if d.strip()}


def _oad_to_yyyymmdd(oad):
    return oad.replace("-", "").split(" ")[0]


def collect_missing_source_dates_oads(source_dates):
    if not source_dates:
        return []
    raw_db_path = Path(Config.RAW_FILLS_DB)
    if not raw_db_path.exists():
        logger.error("raw_fills.db not found at %s", raw_db_path)
        return []
    conn = sqlite3.connect(str(raw_db_path))
    try:
        placeholders = ",".join("?" * len(source_dates))
        sql = (
            "SELECT DISTINCT order_as_of_date FROM raw_fills "
            + " WHERE source_date IN (" + placeholders + ") "
            + " AND order_as_of_date IS NOT NULL AND order_as_of_date != '' "
            + " AND (ExecType != 'DFD' OR ExecType IS NULL) "
            + " ORDER BY order_as_of_date"
        )
        rows = conn.execute(sql, source_dates).fetchall()
    finally:
        conn.close()
    oads = sorted({_oad_to_yyyymmdd(r[0]) for r in rows if r[0]})
    return oads


DEFAULT_MISSING_SOURCE_DATES = [
    "20250919", "20250926", "20251003", "20251010", "20251017",
    "20251024", "20251031", "20251107", "20251121", "20251128",
    "20251205", "20251212", "20251219",
]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Re-run Stage2-Stage4 for affected dates")
    parser.add_argument("--dates", type=str, default="", help="Comma-separated YYYYMMDD order_as_of_date list")
    parser.add_argument("--from-cleanup", action="store_true", help="Read affected dates from cleanup script output")
    parser.add_argument("--missing-source-dates", nargs="*", default=None, help="Expand each source_date to all distinct order_as_of_date in raw_fills. If no value is given, uses the 13 known missing source_dates.")
    parser.add_argument("--no-s5", action="store_true", help="Skip Stage5 (BDIB integration)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format=Config.LOG_FORMAT)
    Config.initialize_directories()

    dates = set()
    if args.dates:
        dates = {d.strip() for d in args.dates.split(",") if d.strip()}
    elif args.from_cleanup:
        dates = _parse_dates_from_cleanup_output()
    elif args.missing_source_dates is not None:
        src_dates = args.missing_source_dates or DEFAULT_MISSING_SOURCE_DATES
        logger.info("Expanding %d source_date to distinct order_as_of_date...", len(src_dates))
        oads = collect_missing_source_dates_oads(src_dates)
        logger.info("Discovered %d order_as_of_date to re-process", len(oads))
        dates = set(oads)

    if not dates:
        logger.warning("No dates specified; nothing to do")
        return 0

    date_list = sorted(dates)
    logger.info("Reprocessing %d dates: first 10 = %s", len(date_list), date_list[:10])

    logger.info("[1/4] Stage2: raw to processed (order_as_of_date dimension)")
    run_process(dates=date_list, force=True)

    logger.info("[2/4] Stage3: 10s route-level aggregation")
    run_aggregate(dates=date_list, force=True)

    logger.info("[3/4] Stage4: order labels")
    run_order_labels(dates=date_list, force=True)

    if not args.no_s5:
        logger.info("[4/4] Stage5: BDIB integration")
        run_bdib_integration(dates=date_list, force=True)
    else:
        logger.info("[4/4] Stage5: skipped (--no-s5)")

    logger.info("Reprocess complete: %d dates", len(date_list))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

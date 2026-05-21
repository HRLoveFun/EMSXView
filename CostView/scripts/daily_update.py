"""
Daily Update Scheduler — automated CostView pipeline execution.

Runs the full FillFetch + processing pipeline on a configurable schedule.
Designed for post-market-close execution (default: 18:00 local time).

Usage:
    # Run once and exit
    python daily_update.py --once

    # Enter schedule loop (runs daily at 18:00)
    python daily_update.py

    # Custom time
    python daily_update.py --time 17:30
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import logging.handlers
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Add EMSX root to path (parent of CostView/ and DataPipeline/)
_SCRIPT_DIR = Path(__file__).resolve().parent
_COSTVIEW_ROOT = _SCRIPT_DIR.parent
_EMSX_ROOT = _COSTVIEW_ROOT.parent
sys.path.insert(0, str(_EMSX_ROOT))

from DataPipeline.config import Config

logger = logging.getLogger("daily_update")


_KNOWN_DBS = [
    "raw_fills.db",
    "processed_fills.db",
    "raw_bdib.db",
    "fill_bdib.db",
    "regime.db",
]


def _log_mem(stage_label: str = "") -> None:
    """Log current RSS memory usage for OOM diagnosis."""
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        rss_gb = proc.memory_info().rss / (1024 ** 3)
        logger.info("[MEM] %s — RSS=%.2f GB", stage_label, rss_gb)
        print(f"[MEM] {stage_label} — RSS={rss_gb:.2f} GB", flush=True)
    except ImportError:
        pass  # psutil not installed — skip memory logging


def _checkpoint_wal() -> None:
    """Force WAL checkpoint on all known CostView databases.

    After a subprocess write, data may reside only in the WAL file and not
    yet be visible to read-only connections that open via ``?mode=ro`` (as
    ``repositories.py`` does).  Running ``wal_checkpoint(TRUNCATE)`` writes
    all WAL pages into the main DB and resets the WAL, guaranteeing that
    subsequent reads see the latest committed data.

    This is called just before the ``[STAGE] completion 100`` marker so
    that the backend's ``/api/db/overview`` endpoint will see fresh data.
    """
    data_dir = _COSTVIEW_ROOT / "data"
    for db_name in _KNOWN_DBS:
        db_path = data_dir / db_name
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), timeout=2.0)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception as exc:
            logger.warning("WAL checkpoint failed for %s: %s", db_name, exc)
    for _db_name in _KNOWN_DBS:
        _db_path = data_dir / _db_name
        if _db_path.exists():
            _mtime = datetime.fromtimestamp(os.path.getmtime(_db_path))
            logger.info(f"DB state: {_db_name} modified={_mtime}")


def _setup_logging() -> None:
    """Configure logging for the scheduler."""
    Config.initialize_directories()
    fmt = logging.Formatter(Config.LOG_FORMAT, datefmt=Config.LOG_DATE_FORMAT)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    if Config.LOG_FILE.parent.exists():
        fh = logging.handlers.TimedRotatingFileHandler(
            str(Config.LOG_FILE),
            when="midnight",
            backupCount=Config.LOG_RETENTION_DAYS,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)


def run_daily_pipeline() -> dict:
    """Execute the full daily pipeline: fetch + process + aggregate + labels.

    Returns:
        Summary dict with fetch and pipeline results.
    """
    summary = {
        "run_timestamp": datetime.now().isoformat(),
        "fetch": None,
        "pipeline": None,
        "status": "unknown",
    }

    # ── Stage marker: Initialization ──
    print("[STAGE] initialization 50")
    _log_mem("initialization")
    gc.collect()

    try:
        # Stage A: Auto-fetch new fills
        print("[STAGE] fill_fetch 10")
        _log_mem("fill_fetch_before")
        from DataPipeline.ingestion.fill_fetch import FillFetch

        logger.info("=" * 60)
        logger.info("DAILY UPDATE: Starting auto-fetch")
        logger.info("=" * 60)

        fetcher = FillFetch()
        try:
            print("[STAGE] fill_fetch 30")
            fetch_range = fetcher.determine_fetch_range()
            if fetch_range is None:
                logger.info("Already up-to-date. Nothing to fetch.")
                summary["fetch"] = {"status": "up-to-date"}
                print("[STAGE] fill_fetch 100")
            else:
                start, end = fetch_range
                total_calendar_days = (end - start).days + 1
                logger.info(f"Auto-fetch: {start} -> {end} ({total_calendar_days} calendar days)")

                def _on_fetch_progress(day_idx: int, total_days: int, date_str: str, rows: int, detail: str) -> None:
                    # Map per-day progress to fill_fetch stage percentage (range 40–95)
                    pct = 40 + int((day_idx / total_days) * 55) if total_days > 0 else 95
                    pct = min(95, max(40, pct))
                    print(f"[STAGE] fill_fetch {pct} Day {day_idx}/{total_days}: {date_str} — {detail}")

                print(f"[STAGE] fill_fetch 40 Total: {total_calendar_days} calendar days to scan")
                fetch_result = fetcher.fetch_range_aggregated(start, end, progress_callback=_on_fetch_progress)
                summary["fetch"] = fetch_result
                print("[STAGE] fill_fetch 100 Fill fetch complete")
        finally:
            fetcher.close()

        gc.collect()
        _log_mem("fill_fetch_after")

        # Stage B: Run incremental pipeline (with BDIB integration enabled)
        print("[STAGE] processing 10")
        _log_mem("processing_before")
        from DataPipeline.orchestration.core import run_incremental

        logger.info("=" * 60)
        logger.info("DAILY UPDATE: Running incremental pipeline (BDIB enabled)")
        logger.info("=" * 60)

        fetch_status = summary.get("fetch")
        if fetch_status is None:
            logger.info("fetch_range returned None — no new fills beyond last fetched date")
        elif isinstance(fetch_status, dict):
            logger.info("Fetch result: %s", json.dumps(fetch_status, default=str))

        print("[STAGE] processing 50")
        _log_mem("pipeline_before")
        pipeline_result = run_incremental(
            skip_bdib=False,
            stage_marker_name="processing",
            stage_marker_start=55,
            stage_marker_end=95,
        )
        gc.collect()
        _log_mem("pipeline_after")
        summary["pipeline"] = pipeline_result
        logger.info("Pipeline result: %s", json.dumps(pipeline_result, default=str))

        # Stage C: Write downstream manifest and flush databases to disk
        print("[STAGE] completion 20")
        try:
            from DataPipeline.analysis.downstream_interface import write_manifest
            write_manifest()
            logger.info("Downstream manifest updated")
        except Exception as e:
            logger.warning(f"Manifest write skipped: {e}")

        # ── Force WAL checkpoint so /api/db/overview sees fresh data ──
        _checkpoint_wal()
        gc.collect()
        _log_mem("completion_before_checkpoint")

        # ── Build human-readable completion detail for the frontend ──
        fetch_result = summary.get("fetch") or {}
        if isinstance(fetch_result, dict) and fetch_result.get("status") == "up-to-date":
            detail = "Already up to date — no new fills to fetch"
        else:
            fetch_rows = fetch_result.get("total_rows", 0) if isinstance(fetch_result, dict) else 0
            pipeline_processing = (pipeline_result or {}).get("processing", {}) if isinstance(pipeline_result, dict) else {}
            pipeline_rows = pipeline_processing.get("rows_processed", 0) if isinstance(pipeline_processing, dict) else 0
            agg_result = (pipeline_result or {}).get("aggregation", {}) if isinstance(pipeline_result, dict) else {}
            agg_dates = agg_result.get("dates", 0) if isinstance(agg_result, dict) else 0
            if fetch_rows or pipeline_rows:
                detail = f"Fetched {fetch_rows} fills · processed {pipeline_rows} rows · aggregated {agg_dates} dates"
            else:
                detail = "Pipeline ran with no data changes"

        summary["status"] = "success"
        print(f"[STAGE] completion 100 {detail}")
        logger.info(f"DAILY UPDATE complete: {json.dumps(summary, indent=2, default=str)}")
        gc.collect()
        _log_mem("completion_done")

    except Exception as e:
        summary["status"] = "failed"
        summary["error"] = str(e)
        logger.critical(f"DAILY UPDATE FAILED: {e}", exc_info=True)
        gc.collect()
        _log_mem("failed")

    # Write structured summary to log
    logger.info(f"pipeline.summary: {json.dumps(summary, default=str)}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="CostView Daily Update Scheduler")
    parser.add_argument(
        "--once", action="store_true",
        help="Run the pipeline once and exit (no scheduling loop)",
    )
    parser.add_argument(
        "--time", type=str, default="18:00",
        help="Time to run daily (HH:MM format, default: 18:00)",
    )
    args = parser.parse_args()

    _setup_logging()

    if args.once:
        logger.info("Running once (--once mode)")
        result = run_daily_pipeline()
        sys.exit(0 if result["status"] == "success" else 1)

    # Schedule loop
    try:
        import schedule
    except ImportError:
        logger.error(
            "The 'schedule' package is required for scheduling mode. "
            "Install it with: pip install schedule\n"
            "Alternatively, use --once with Windows Task Scheduler."
        )
        sys.exit(1)

    logger.info(f"Scheduling daily pipeline at {args.time}")
    schedule.every().day.at(args.time).do(run_daily_pipeline)

    logger.info("Scheduler started. Press Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            import time
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    main()

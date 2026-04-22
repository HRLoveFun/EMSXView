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
import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path

# Add CostView root to path
_SCRIPT_DIR = Path(__file__).resolve().parent
_COSTVIEW_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_COSTVIEW_ROOT))

from src.processing_config import ProcessingConfig as Config

logger = logging.getLogger("daily_update")


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

    try:
        # Stage A: Auto-fetch new fills
        print("[STAGE] fill_fetch 10")
        from src.fill_fetch import FillFetch

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
                logger.info(f"Auto-fetch: {start} -> {end}")
                print("[STAGE] fill_fetch 60")
                fetch_result = fetcher.fetch_range_aggregated(start, end)
                summary["fetch"] = fetch_result
                print("[STAGE] fill_fetch 100")
        finally:
            fetcher.close()

        # Stage B: Run incremental pipeline (with BDIB integration enabled)
        print("[STAGE] processing 10")
        from src.pipeline import run_incremental

        logger.info("=" * 60)
        logger.info("DAILY UPDATE: Running incremental pipeline (BDIB enabled)")
        logger.info("=" * 60)

        print("[STAGE] processing 50")
        pipeline_result = run_incremental(
            skip_bdib=False,
            stage_marker_name="processing",
            stage_marker_start=55,
            stage_marker_end=95,
        )
        summary["pipeline"] = pipeline_result

        # Stage C: Write downstream manifest
        print("[STAGE] completion 20")
        try:
            from src.downstream_interface import write_manifest
            write_manifest()
            logger.info("Downstream manifest updated")
        except Exception as e:
            logger.warning(f"Manifest write skipped: {e}")

        summary["status"] = "success"
        print("[STAGE] completion 100")
        logger.info(f"DAILY UPDATE complete: {json.dumps(summary, indent=2, default=str)}")

    except Exception as e:
        summary["status"] = "failed"
        summary["error"] = str(e)
        logger.critical(f"DAILY UPDATE FAILED: {e}", exc_info=True)

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

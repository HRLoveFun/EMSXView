"""
Entry point for running CostView as a module (v3, optimized).

Usage:
    python -m src                          # Default: show help
    python -m src --fetch-auto            # Auto-fetch fills (first/incremental)
    python -m src --fetch-auto --parallel 2 # Parallel fetch with 2 sessions
    python -m src --process                # Process raw fills -> processed_fills.db
    python -m src --aggregate              # Aggregate route-level (10s only; 1min disabled)
    python -m src --labels                 # Generate order labels
    python -m src --pipeline               # Full pipeline (process -> aggregate -> labels)
    python -m src --pipeline --force       # Force reprocess all dates
    python -m src --status                 # Show pipeline status

Note: The 1-minute aggregation (--aggregate / pipeline step 3) has been disabled
      in favor of 10-second-only aggregation to reduce storage overhead.
      See pipeline.py run_aggregate() for details.
"""

import argparse
import json
import logging
import logging.handlers
import sys
import warnings
from pathlib import Path

# P2-D6: Ensure CostView root is on sys.path for standalone CLI invocation
# (python -m src). This bootstraps imports when running outside an installed
# environment.
# TODO: Remove when CostView has a proper pyproject.toml [project.scripts].
_COSTVIEW_ROOT = Path(__file__).resolve().parent.parent
if str(_COSTVIEW_ROOT) not in sys.path:
    sys.path.insert(0, str(_COSTVIEW_ROOT))
    warnings.warn(
        "CostView.__main__ sys.path hack is active. "
        "Use pip install -e . for proper package isolation.",
        DeprecationWarning,
        stacklevel=2,
    )

from DataPipeline.config import Config

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    """Configure console + persistent file logging with rotation."""
    Config.initialize_directories()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    fmt = logging.Formatter(Config.LOG_FORMAT, datefmt=Config.LOG_DATE_FORMAT)

    # Console handler (INFO or DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    root_logger.addHandler(console)

    # Main log file — INFO+, rotated daily, kept for LOG_RETENTION_DAYS
    main_handler = logging.handlers.TimedRotatingFileHandler(
        str(Config.LOG_FILE),
        when="midnight",
        backupCount=Config.LOG_RETENTION_DAYS,
        encoding="utf-8",
    )
    main_handler.setLevel(logging.INFO)
    main_handler.setFormatter(fmt)
    root_logger.addHandler(main_handler)

    # Debug log file — DEBUG+, only when verbose, shorter retention
    if verbose:
        debug_handler = logging.handlers.TimedRotatingFileHandler(
            str(Config.LOG_DEBUG_FILE),
            when="midnight",
            backupCount=Config.LOG_DEBUG_RETENTION_DAYS,
            encoding="utf-8",
        )
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(fmt)
        root_logger.addHandler(debug_handler)


def main():
    parser = argparse.ArgumentParser(description="CostView Fill Data Pipeline")

    # FillFetch mode
    parser.add_argument("--fetch", action="store_true", help="Fetch fills from Bloomberg EMSX")
    parser.add_argument("--fetch-auto", action="store_true",
                        help="Auto-detect fetch range and fetch (first/incremental)")

    # Processing pipeline commands
    parser.add_argument("--ingest", action="store_true",
                        help="(Legacy) Ingest Excel files -> raw_fills.db")
    parser.add_argument("--process", action="store_true",
                        help="Process raw fills -> processed_fills.db")
    parser.add_argument("--aggregate", action="store_true",
                        help="Aggregate route-level (10s + 1min)")
    parser.add_argument("--labels", action="store_true", help="Generate order labels")
    parser.add_argument("--pipeline", action="store_true",
                        help="Full pipeline (process -> aggregate -> labels)")
    parser.add_argument("--bdib", action="store_true",
                        help="Include BDIB integration in pipeline")

    # Rebuild options
    parser.add_argument("--rebuild-processed", action="store_true",
                        help="Rebuild processed_fills from raw_fills")
    parser.add_argument("--rebuild-aggregated", action="store_true",
                        help="Rebuild aggregated tables from processed_fills")

    # Query interface (Phase 3)
    parser.add_argument("--query", type=str, metavar="TYPE",
                        choices=["fills", "raw-fills", "log", "order-log",
                                 "orders", "tickers", "summary"],
                        help="Query data: fills|raw-fills|log|order-log|orders|tickers|summary")
    parser.add_argument("--format", type=str, default="table",
                        choices=["table", "csv", "json"],
                        help="Output format for --query (default: table)")
    parser.add_argument("--limit", type=int, default=100,
                        help="Max rows for --query (default: 100)")
    parser.add_argument("--offset", type=int, default=0,
                        help="Row offset for --query pagination")
    parser.add_argument("--last", type=int, default=10,
                        help="Number of recent entries for --query log (default: 10)")
    parser.add_argument("--ticker", type=str, help="Filter by ticker for --query fills")
    parser.add_argument("--order-id", type=str, help="Filter by order ID for --query fills")

    # Database access control (Phase 1)
    parser.add_argument("--db-access", type=str, default=None,
                        choices=["read", "write"],
                        help="Database access tier (default: auto)")
    parser.add_argument("--confirm-delete", action="store_true",
                        help="Confirm destructive DB operations (required for admin)")

    # Scheduler (Phase 2C)
    parser.add_argument("--schedule", action="store_true",
                        help="Enter daily scheduling loop")
    parser.add_argument("--schedule-time", type=str, default="18:00",
                        help="Time for scheduled run (HH:MM, default: 18:00)")
    parser.add_argument("--schedule-once", action="store_true",
                        help="Run the scheduled pipeline once and exit")

    # Date/Range options
    parser.add_argument("--process-date", type=str, help="Process a specific date (YYYYMMDD)")
    parser.add_argument("--process-range", nargs=2, metavar=("START", "END"),
                        help="Process date range (YYYYMMDD YYYYMMDD)")
    parser.add_argument("--from-date", type=str, help="Start date for fetch/process (YYYYMMDD)")
    parser.add_argument("--to-date", type=str, help="End date for fetch/process (YYYYMMDD)")

    # General options
    parser.add_argument("--force", action="store_true", help="Force reprocess all dates")
    parser.add_argument("--archive-excel", action="store_true",
                        help="Save Excel files alongside DB upsert")
    parser.add_argument("--status", action="store_true", help="Show pipeline status")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    args = parser.parse_args()
    _setup_logging(verbose=args.verbose)

    # Resolve access tier
    access_tier = None
    if args.db_access:
        from DataPipeline.storage.connection import AccessTier
        access_tier = AccessTier(args.db_access)
    if args.query or args.status:
        # Query/status commands default to READ access
        if access_tier is None:
            from DataPipeline.storage.connection import AccessTier
            access_tier = AccessTier.READ
    if access_tier is not None:
        import os
        os.environ["COSTVIEW_DB_ACCESS"] = access_tier.value

    # Determine dates
    dates = None
    if args.process_date:
        dates = [args.process_date]
    elif args.process_range:
        dates = _expand_date_range(args.process_range[0], args.process_range[1])

    try:
        # -- Query interface (Phase 3) --
        if args.query:
            from src.query_cli import QueryEngine, format_output

            qe = QueryEngine()
            date_filter = args.process_date or (args.process_range[0] if args.process_range else None)

            if args.query == "fills":
                result = qe.query_fills(
                    date=date_filter, order_id=args.order_id,
                    ticker=args.ticker, limit=args.limit, offset=args.offset,
                )
            elif args.query == "raw-fills":
                result = qe.query_raw_fills(
                    date=date_filter, order_id=args.order_id,
                    limit=args.limit, offset=args.offset,
                )
            elif args.query == "log":
                result = qe.query_fetch_log(last=args.last)
            elif args.query == "order-log":
                result = qe.query_order_fetch_log(date=date_filter, last=args.last)
            elif args.query == "orders":
                result = qe.query_orders(date=date_filter, limit=args.limit,
                                         offset=args.offset)
            elif args.query == "tickers":
                result = qe.query_tickers()
            elif args.query == "summary":
                result = qe.query_summary(date=date_filter)
            else:
                parser.print_help()
                sys.exit(1)

            print(format_output(result, fmt=args.format))

        # -- Schedule mode (Phase 2C) --
        elif args.schedule or args.schedule_once:
            from CostView.scripts.daily_update import run_daily_pipeline
            if args.schedule_once:
                result = run_daily_pipeline()
                print(json.dumps(result, indent=2, default=str))
            else:
                try:
                    import schedule as sched_lib
                except ImportError:
                    print("Install 'schedule' package: pip install schedule")
                    sys.exit(1)
                logger.info(f"Scheduling daily at {args.schedule_time}")
                sched_lib.every().day.at(args.schedule_time).do(run_daily_pipeline)
                try:
                    import time
                    while True:
                        sched_lib.run_pending()
                        time.sleep(60)
                except KeyboardInterrupt:
                    logger.info("Scheduler stopped")

        elif args.status:
            from DataPipeline.orchestration.core import get_pipeline_status
            status = get_pipeline_status()
            print(json.dumps(status, indent=2, default=str))

        elif args.fetch_auto:
            from DataPipeline.ingestion.fill_fetch import FillFetch
            fetcher = FillFetch()
            try:
                fetch_range = fetcher.determine_fetch_range()
                if fetch_range is None:
                    print("Already up-to-date. Nothing to fetch.")
                else:
                    start, end = fetch_range
                    print(f"Auto-fetch: {start} -> {end}")
                    summary = fetcher.fetch_range_aggregated(
                        start, end, archive_excel=args.archive_excel,
                    )
                    print(json.dumps(summary, indent=2, default=str))
            finally:
                fetcher.close()

        elif args.fetch:
            from DataPipeline.ingestion.fill_fetch import main as fetch_main
            fetch_main()

        elif args.pipeline:
            from DataPipeline.orchestration.core import run_full_pipeline
            summary = run_full_pipeline(
                dates=dates,
                force=args.force,
                skip_bdib=not args.bdib,
                skip_ingest=True,
            )
            print(json.dumps(summary, indent=2, default=str))

        elif args.rebuild_processed:
            if not args.confirm_delete:
                print("Rebuild requires --confirm-delete flag (destructive operation)")
                sys.exit(1)
            from DataPipeline.orchestration.core import run_process
            print("Rebuilding processed_fills from raw_fills.db...")
            df = run_process(dates=dates, force=True)
            print(f"Rebuilt {len(df)} processed fills")

        elif args.rebuild_aggregated:
            if not args.confirm_delete:
                print("Rebuild requires --confirm-delete flag (destructive operation)")
                sys.exit(1)
            from DataPipeline.orchestration.core import run_aggregate
            print("Rebuilding aggregated tables from processed_fills...")
            run_aggregate(dates=dates, force=True)
            print("Rebuild complete")

        elif args.ingest:
            from DataPipeline.orchestration.core import run_ingest
            results = run_ingest()
            ingested = sum(1 for r in results if r["success"] and not r["skipped"])
            print(f"Ingested {ingested} files")

        elif args.process:
            from DataPipeline.orchestration.core import run_process
            df = run_process(dates=dates, force=args.force)
            print(f"Processed {len(df)} fills")

        elif args.aggregate:
            from DataPipeline.orchestration.core import run_aggregate
            run_aggregate(dates=dates, force=args.force)
            print("Aggregation complete (route-level)")

        elif args.labels:
            from DataPipeline.orchestration.core import run_order_labels
            labels = run_order_labels(dates=dates, force=args.force)
            print(f"Generated {len(labels)} order labels")

        else:
            parser.print_help()

    except PermissionError as e:
        logger.error(f"Access denied: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        sys.exit(1)


def _expand_date_range(start: str, end: str) -> list:
    """Expand a YYYYMMDD date range to a list of dates."""
    from datetime import datetime, timedelta
    start_dt = datetime.strptime(start, "%Y%m%d")
    end_dt = datetime.strptime(end, "%Y%m%d")
    dates = []
    current = start_dt
    while current <= end_dt:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


if __name__ == "__main__":
    main()

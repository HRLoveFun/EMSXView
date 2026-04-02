"""
Entry point for running CostView as a module.

Usage:
    python -m src                          # Default: fetch fills
    python -m src --ingest                 # Ingest Excel files → raw_fills.db
    python -m src --process                # Process raw fills → processed_fills.db
    python -m src --aggregate              # Aggregate (10s + 1min)
    python -m src --labels                 # Generate order labels
    python -m src --pipeline               # Full pipeline (ingest → process → aggregate → labels)
    python -m src --pipeline --force       # Force reprocess all dates
    python -m src --pipeline --bdib        # Include BDIB integration
    python -m src --process-date 20260309  # Process a specific date
    python -m src --status                 # Show pipeline status
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(description="CostView Fill Data Pipeline")

    # Original FillFetch mode
    parser.add_argument("--fetch", action="store_true", help="Fetch fills from Bloomberg EMSX")

    # Processing pipeline commands
    parser.add_argument("--ingest", action="store_true", help="Ingest Excel files → raw_fills.db")
    parser.add_argument("--process", action="store_true", help="Process raw fills → processed_fills.db")
    parser.add_argument("--aggregate", action="store_true", help="Aggregate (10s + 1min)")
    parser.add_argument("--labels", action="store_true", help="Generate order labels")
    parser.add_argument("--pipeline", action="store_true", help="Full pipeline (ingest → labels)")
    parser.add_argument("--bdib", action="store_true", help="Include BDIB integration in pipeline")

    # Options
    parser.add_argument("--process-date", type=str, help="Process a specific date (YYYYMMDD)")
    parser.add_argument("--process-range", nargs=2, metavar=("START", "END"),
                        help="Process date range (YYYYMMDD YYYYMMDD)")
    parser.add_argument("--force", action="store_true", help="Force reprocess all dates")
    parser.add_argument("--status", action="store_true", help="Show pipeline status")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    args = parser.parse_args()
    _setup_logging(verbose=args.verbose)

    # Determine dates
    dates = None
    if args.process_date:
        dates = [args.process_date]
    elif args.process_range:
        dates = _expand_date_range(args.process_range[0], args.process_range[1])

    try:
        if args.status:
            from src.pipeline import get_pipeline_status
            status = get_pipeline_status()
            print(json.dumps(status, indent=2, default=str))

        elif args.pipeline:
            from src.pipeline import run_full_pipeline
            summary = run_full_pipeline(
                dates=dates,
                force=args.force,
                skip_bdib=not args.bdib,
            )
            print(json.dumps(summary, indent=2, default=str))

        elif args.ingest:
            from src.pipeline import run_ingest
            results = run_ingest()
            ingested = sum(1 for r in results if r["success"] and not r["skipped"])
            print(f"Ingested {ingested} files")

        elif args.process:
            from src.pipeline import run_process
            df = run_process(dates=dates, force=args.force)
            print(f"Processed {len(df)} fills")

        elif args.aggregate:
            from src.pipeline import run_aggregate
            run_aggregate(dates=dates, force=args.force)
            print("Aggregation complete")

        elif args.labels:
            from src.pipeline import run_order_labels
            labels = run_order_labels(dates=dates, force=args.force)
            print(f"Generated {len(labels)} order labels")

        elif args.fetch:
            from src.fill_fetch import main as fetch_main
            fetch_main()

        else:
            # Default: show help
            parser.print_help()

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

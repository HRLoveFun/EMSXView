"""
BDIB History Backfill Script — fetches historical BDIB bars to support ADV calculations.

Reads all distinct (equ_ticker, order_as_of_date) pairs from raw_fills.db.fetch_log,
determines the earliest fill date, then fetches BDIB bars for the 25 trading days
PRIOR to that date so the 20-day ADV window is fully covered.

Also backfills all fill dates that are missing from raw_bdib.db.

Usage:
    python backfill_bdib_history.py
    python backfill_bdib_history.py --lookback 30   # extend lookback window
    python backfill_bdib_history.py --dry-run       # show plan without fetching

Requires: Bloomberg connection (blpapi / xbbg).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_COSTVIEW_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_COSTVIEW_ROOT))

from DataPipeline.config import Config
from src.raw_bdib_db import RawBDIBDB
from src.raw_fills_db import RawFillsDB

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    Config.initialize_directories()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )


def _expand_weekdays(start: date, end: date) -> list[str]:
    """Return sorted list of YYYYMMDD weekday strings between start and end (inclusive)."""
    if start > end:
        return []
    dates: list[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


def _prior_weekdays(ref: date, n: int) -> list[str]:
    """Return n trading days (Mon-Fri) strictly before ref, newest-first."""
    results: list[str] = []
    current = ref - timedelta(days=1)
    while len(results) < n:
        if current.weekday() < 5:
            results.append(current.strftime("%Y%m%d"))
        current -= timedelta(days=1)
    return results


def run_backfill(lookback_days: int = 25, dry_run: bool = False) -> None:
    """Main backfill routine."""
    raw_fills_db = RawFillsDB()
    raw_bdib_db = RawBDIBDB()

    # 1. Determine all fill dates and tickers
    fill_dates = raw_fills_db.get_all_source_dates()
    if not fill_dates:
        logger.warning("raw_fills.db has no data — nothing to backfill.")
        return

    fill_dates_sorted = sorted(fill_dates)
    earliest_fill = datetime.strptime(fill_dates_sorted[0], "%Y%m%d").date()
    latest_fill = datetime.strptime(fill_dates_sorted[-1], "%Y%m%d").date()

    # 2. Dates we need to cover: lookback before earliest fill + all fill dates
    lookback_start = earliest_fill - timedelta(days=lookback_days * 2)  # extra buffer for weekends
    lookback_dates = _prior_weekdays(earliest_fill, lookback_days)
    fill_date_range = _expand_weekdays(earliest_fill, latest_fill)
    all_needed_dates = sorted(set(lookback_dates) | set(fill_date_range))

    # 3. Subtract dates already in raw_bdib
    existing_dates = set(raw_bdib_db.get_distinct_dates())
    missing_dates = [d for d in all_needed_dates if d not in existing_dates]

    logger.info(f"Fill universe: {fill_dates_sorted[0]} → {fill_dates_sorted[-1]} ({len(fill_date_range)} days)")
    logger.info(f"Lookback ({lookback_days}d): adds {len(lookback_dates)} prior trading days")
    logger.info(f"Already in raw_bdib: {len(existing_dates)} dates")
    logger.info(f"To fetch: {len(missing_dates)} dates")

    if not missing_dates:
        logger.info("raw_bdib already covers all required dates. Nothing to fetch.")
        return

    if dry_run:
        logger.info(f"DRY RUN — would fetch dates: {missing_dates[:5]}{'...' if len(missing_dates) > 5 else ''}")
        return

    # 4. Determine tickers from processed_fills ticker_repository
    try:
        from DataPipeline.storage.facade import CostViewDatabase
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            db = CostViewDatabase()
        ticker_exchange_map = db.fills_read.get_ticker_exchange_map()
        tickers = list(ticker_exchange_map.keys())
    except Exception as e:
        logger.error(f"Could not load ticker list: {e}")
        return

    if not tickers:
        logger.warning("No tickers found in ticker_repository. Cannot backfill.")
        return

    logger.info(f"Tickers to fetch BDIB for: {len(tickers)}")

    # 5. Fetch via existing bdib_fetcher
    try:
        from src.bdib_fetcher import fetch_bdib_for_fills, get_bdib_for_date
        from src.processed_raw_bdib_db import ProcessedRawBDIBDB
    except ImportError as e:
        logger.error(f"Bloomberg dependencies unavailable: {e}")
        return

    proc_raw_bdib = ProcessedRawBDIBDB()

    for date_str in missing_dates:
        logger.info(f"Fetching BDIB for {date_str}...")
        try:
            ticker_dates = {ticker: [date_str] for ticker in tickers}
            bdib_map = fetch_bdib_for_fills(
                ticker_dates,
                interval=10,
                ticker_exchange_map=ticker_exchange_map,
            )
            bdib_df = get_bdib_for_date(bdib_map, date_str) if bdib_map else None

            if bdib_df is None or bdib_df.empty:
                logger.info(f"  {date_str}: no data returned (likely non-trading day)")
                continue

            raw_rows = raw_bdib_db.upsert_bdib_data(bdib_df, date_str=date_str)

            # Also populate processed_raw_bdib
            bdib_enriched = ProcessedRawBDIBDB.compute_derived_fields(bdib_df)
            proc_rows = proc_raw_bdib.upsert_processed_bdib(bdib_enriched)

            logger.info(f"  {date_str}: {raw_rows} raw rows, {proc_rows} processed rows")

        except Exception as exc:
            logger.error(f"  Error fetching {date_str}: {exc}")

    # 6. Compute daily metrics for all newly fetched dates
    logger.info("Computing daily metrics (ADV + volatility) for backfilled dates...")
    try:
        from src.daily_metrics_calculator import CalculateDailyMetrics
        calc = CalculateDailyMetrics(db=raw_bdib_db)
        for trade_date in missing_dates:
            try:
                calc.run_for_date(trade_date)
            except Exception as exc:
                logger.error(f"  Metrics error for {trade_date}: {exc}")
    except ImportError as e:
        logger.warning(f"Could not run daily metrics: {e}")

    logger.info("Backfill complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical BDIB data for ADV")
    parser.add_argument(
        "--lookback", type=int, default=25,
        help="Number of trading days to backfill before earliest fill date (default: 25)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print plan without fetching"
    )
    args = parser.parse_args()

    _setup_logging()
    run_backfill(lookback_days=args.lookback, dry_run=args.dry_run)

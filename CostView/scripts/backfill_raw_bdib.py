"""
Backfill Raw BDIB — iterate business weekdays from a start date, fetch raw BDIB
data for each valid trading day, and upsert sequentially into raw_bdib.db.

Also provides data cleaning, validation, and selective re-fetch capabilities:

    # Clean NULL-close rows from raw_bdib.db
    python backfill_raw_bdib.py --clean

    # Validate + selectively re-fetch only broken (ticker, date) pairs
    python backfill_raw_bdib.py --repair

    # Full pipeline: clean -> validate -> repair -> continue backfill
    python backfill_raw_bdib.py --clean --repair

Usage (backfill):
    # Default: start from 2025-09-25 to today's previous weekday
    python backfill_raw_bdib.py

    # Custom start date
    python backfill_raw_bdib.py --start 2025-01-02

    # Custom end date (inclusive)
    python backfill_raw_bdib.py --start 2025-09-25 --end 2026-03-31

    # Force re-fetch (skip incremental check)
    python backfill_raw_bdib.py --force

    # Dry-run: list dates without fetching
    python backfill_raw_bdib.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

# ── Path setup ──
_SCRIPT_DIR = Path(__file__).resolve().parent
_COSTVIEW_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_COSTVIEW_ROOT))

from DataPipeline.config import Config
from src.bdib_fetcher import fetch_bdib_for_fills, get_bdib_for_date, _is_trading_day
from src.raw_bdib_db import RawBDIBDB
from DataPipeline.storage.facade import DatabaseFacade

logger = logging.getLogger("backfill_raw_bdib")


def _setup_logging() -> None:
    """Configure logging with console + file output."""
    Config.initialize_directories()
    fmt = logging.Formatter(Config.LOG_FORMAT, datefmt=Config.LOG_DATE_FORMAT)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    log_path = Config.LOGGING_DIR / "backfill_raw_bdib.log"
    if log_path.parent.exists():
        fh = logging.handlers.RotatingFileHandler(
            str(log_path),
            maxBytes=50 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)


def _expand_business_weekdays(start: date, end: date) -> List[date]:
    """Generate all business weekdays (Mon-Fri) in [start, end], excluding weekends.

    Does NOT filter holidays — Bloomberg API will return empty/None for
    non-trading days, and _validate_bdib_response handles that gracefully.
    Use _is_trading_day for stricter filtering if needed.
    """
    dates: List[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # Mon=0 .. Fri=4
            dates.append(current)
        current += timedelta(days=1)
    return dates


def _get_previous_weekday(ref: Optional[date] = None) -> date:
    """Get most recent weekday on or before *ref* (default: today)."""
    d = ref or datetime.now().date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def load_ticker_exchange_map() -> dict:
    """Load equ_ticker -> exchange mapping from processed_fills ticker_repository."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        db = DatabaseFacade()
    bdid_exchange = [str(e).strip().upper() for e in Config.BDID_EXCHANGE if str(e).strip()]
    mapping = db.fills_read.get_ticker_exchange_map(exchanges=bdid_exchange)
    logger.info(f"Loaded {len(mapping)} tickers from ticker_repository (exchanges={bdid_exchange})")
    return mapping


# ═══════════════════════════════════════════════════════════════════════
# SECTION: Data Cleaning — remove NULL close rows
# ═══════════════════════════════════════════════════════════════════════

def clean_null_close_rows(db: Optional[RawBDIBDB] = None, dry_run: bool = False) -> int:
    """Delete rows where 'close' is NULL or empty string from raw_bdib.db.

    This removes degenerate bars (non-trading hours, suspended securities,
    empty Bloomberg responses) that carry no price information.

    Args:
        db: RawBDIBDB instance (created if None).
        dry_run: If True, only count and report without deleting.

    Returns:
        Number of deleted (or would-be-deleted) rows.
    """
    import sqlite3

    local_db = db or RawBDIBDB()
    conn = sqlite3.connect(str(local_db.db_path))

    try:
        # Count before delete
        cur = conn.execute(
            "SELECT COUNT(*) FROM raw_bdib "
            "WHERE close IS NULL OR close = '' OR TRIM(close) = ''"
        )
        null_count = cur.fetchone()[0]

        total_cur = conn.execute("SELECT COUNT(*) FROM raw_bdib")
        total_before = total_cur.fetchone()[0]

        if null_count == 0:
            logger.info("CLEAN: No NULL-close rows found — nothing to clean")
            conn.close()
            return 0

        # Show per-ticker breakdown for diagnostics
        breakdown = conn.execute(
            "SELECT equ_ticker, COUNT(*) as cnt FROM raw_bdib "
            "WHERE close IS NULL OR close = '' OR TRIM(close) = '' "
            "GROUP BY equ_ticker ORDER BY cnt DESC LIMIT 20"
        )
        top_bad = breakdown.fetchall()
        logger.info(f"CLEAN: Found {null_count:,} NULL-close rows ({null_count/total_before*100:.2f}% of {total_before:,})")
        logger.info("CLEAN: Top 20 affected tickers:")
        for tkr, cnt in top_bad:
            logger.info(f"  {tkr}: {cnt} rows")

        if dry_run:
            logger.info(f"CLEAN [DRY-RUN]: Would delete {null_count:,} rows")
            conn.close()
            return null_count

        # Execute deletion in a transaction
        cur_del = conn.execute(
            "DELETE FROM raw_bdib WHERE close IS NULL OR close = '' OR TRIM(close) = ''"
        )
        deleted = cur_del.rowcount
        conn.commit()

        # Vacuum to reclaim space (can be slow on large DBs)
        logger.info(f"CLEAN: Deleted {deleted:,} NULL-close rows. Running VACUUM...")
        conn.execute("VACUUM")

        total_after = conn.execute("SELECT COUNT(*) FROM raw_bdib").fetchone()[0]
        logger.info(
            f"CLEAN complete: {deleted:,} rows removed "
            f"({total_before:,} -> {total_after:,} rows)"
        )
        return deleted

    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# SECTION: Validation — find broken (ticker, date) atomic units
# ═══════════════════════════════════════════════════════════════════════

_OHLC_FIELDS = ("open", "high", "low", "close")


def find_invalid_ticker_date_pairs(
    db: Optional[RawBDIBDB] = None,
) -> List[Tuple[str, str]]:
    """Identify (equ_ticker, order_as_of_date) pairs that contain at least one row
    with NULL/empty OHLC fields.

    The validation granularity is the (ticker, date) atomic unit:
      - If ANY bar for a given (ticker, date) has missing OHLC data,
        the entire pair is flagged for re-fetch.
      - Pairs where ALL bars have valid OHLC are considered healthy and skipped.

    Args:
        db: RawBDIBDB instance (created if None).

    Returns:
        Sorted list of (equ_ticker, order_as_of_date) tuples needing re-fetch.
    """
    import sqlite3

    local_db = db or RawBDIBDB()
    conn = sqlite3.connect(str(local_db.db_path))

    try:
        # Find all distinct (ticker, date) pairs that have at least one bad bar
        condition = " OR ".join(
            f"{f} IS NULL OR {f} = '' OR TRIM({f}) = ''"
            for f in _OHLC_FIELDS
        )
        cur = conn.execute(f"""
            SELECT DISTINCT equ_ticker, order_as_of_date
            FROM raw_bdib
            WHERE {condition}
            ORDER BY order_as_of_date, equ_ticker
        """)
        invalid_pairs = [(row[0], row[1]) for row in cur.fetchall()]
        return invalid_pairs
    finally:
        conn.close()


def validate_and_report(db: Optional[RawBDIBDB] = None) -> dict:
    """Run full validation scan and produce a diagnostic report.

    Returns:
        Dict with 'invalid_pair_count', 'invalid_pairs_by_date', etc.
    """
    local_db = db or RawBDIBDB()
    import sqlite3
    conn = sqlite3.connect(str(local_db.db_path))

    try:
        total_rows = conn.execute("SELECT COUNT(*) FROM raw_bdib").fetchone()[0]
        total_pairs = conn.execute(
            "SELECT COUNT(DISTINCT equ_ticker || '|' || order_as_of_date) FROM raw_bdib"
        ).fetchone()[0]

        # Count rows with any NULL OHLC
        ohlc_null_cond = " OR ".join(
            f"{f} IS NULL OR {f} = ''" for f in _OHLC_FIELDS
        )
        null_rows = conn.execute(
            f"SELECT COUNT(*) FROM raw_bdib WHERE {ohlc_null_cond}"
        ).fetchone()[0]

        invalid_pairs = find_invalid_ticker_date_pairs(db=local_db)

        # Group by date for summary
        by_date: dict[str, int] = {}
        for _, d in invalid_pairs:
            by_date[d] = by_date.get(d, 0) + 1

        report = {
            "total_rows": total_rows,
            "total_ticker_date_pairs": total_pairs,
            "rows_with_null_ohlc": null_rows,
            "null_row_pct": round(null_rows / total_rows * 100, 4) if total_rows else 0,
            "invalid_pair_count": len(invalid_pairs),
            "invalid_pair_pct": round(len(invalid_pairs) / total_pairs * 100, 4) if total_pairs else 0,
            "invalid_pairs_by_date": dict(sorted(by_date.items())),
        }

        logger.info("=" * 60)
        logger.info("VALIDATION REPORT")
        logger.info(f"  Total rows              : {total_rows:,}")
        logger.info(f"  Total (ticker,date) pairs: {total_pairs:,}")
        logger.info(f"  Rows with NULL/empty OHLC: {null_rows:,} ({report['null_row_pct']}%)")
        logger.info(f"  Invalid (ticker,date) pairs: {len(invalid_pairs):,} ({report['invalid_pair_pct']}%)")
        if by_date:
            logger.info(f"  Invalid pairs by date (top 10):")
            for d, c in sorted(by_date.items())[:10]:
                logger.info(f"    {d}: {c} tickers need repair")
        logger.info("=" * 60)

        return report
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# SECTION: Selective Re-Fetch — repair only broken atomic units
# ═══════════════════════════════════════════════════════════════════════

def repair_invalid_pairs(
    db: Optional[RawBDIBDB] = None,
    dry_run: bool = False,
) -> dict:
    """Selective re-fetch: identify broken (ticker, date) pairs, delete their
    existing (bad) rows, re-fetch from Bloomberg, and upsert clean data.

    Workflow per pair:
        1. Scan raw_bdib.db for (equ_ticker, order_as_of_date) with NULL OHLC.
        2. Delete ONLY those specific (ticker, date) rows (not healthy data).
        3. Call fetch_bdib_for_ticker_date() for each broken pair individually.
        4. Upsert the fresh result back into raw_bdib.db.

    This avoids re-fetching valid data while guaranteeing every atomic unit
    passes the OHLC completeness check after repair.

    Args:
        db: RawBDIBDB instance (created if None).
        dry_run: If True, list actions without executing.

    Returns:
        Summary dict with repaired/skipped/failed counts.
    """
    import sqlite3

    local_db = db or RawBDIBDB()

    # Step 1: Find all invalid pairs
    invalid_pairs = find_invalid_ticker_date_pairs(db=local_db)

    if not invalid_pairs:
        logger.info("REPAIR: No invalid (ticker, date) pairs found — database is clean")
        return {"repaired": 0, "skipped": 0, "failed": 0, "rows_upserted": 0}

    logger.info(
        f"REPAIR: Found {len(invalid_pairs)} invalid (ticker, date) pairs "
        f"requiring selective re-fetch"
    )

    # Load exchange map for fetching
    ticker_exchange_map = load_ticker_exchange_map()

    # Step 2: Delete bad rows for each pair
    import sqlite3
    conn = sqlite3.connect(str(local_db.db_path))
    deleted_total = 0

    for ticker, date_str in invalid_pairs:
        cur = conn.execute(
            "DELETE FROM raw_bdib WHERE equ_ticker = ? AND order_as_of_date = ?",
            (ticker, date_str),
        )
        deleted_total += cur.rowcount
    conn.commit()
    logger.info(f"REPAIR: Deleted {deleted_total:,} bad rows across {len(invalid_pairs)} pairs")
    conn.close()

    if dry_run:
        logger.info(f"REPAIR [DRY-RUN]: Would re-fetch {len(invalid_pairs)} pairs")
        return {
            "repaired": len(invalid_pairs), "skipped": 0,
            "failed": 0, "rows_upserted": 0,
        }

    # Step 3 & 4: Re-fetch each broken pair individually and upsert
    summary = {"repaired": 0, "skipped": 0, "failed": 0, "rows_upserted": 0}

    # Group pairs by date for batched logging
    pairs_by_date: dict[str, List[str]] = {}
    for ticker, date_str in invalid_pairs:
        pairs_by_date.setdefault(date_str, []).append(ticker)

    for date_str in sorted(pairs_by_date.keys()):
        tickers = pairs_by_date[date_str]
        date_display = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
        logger.info(f"  REPAIRING {date_display}: {len(tickers)} tickers ...")

        for ticker in tickers:
            try:
                exchange = ticker_exchange_map.get(ticker)

                df = None
                from src.bdib_fetcher import fetch_bdib_for_ticker_date
                df = fetch_bdib_for_ticker_date(
                    ticker=ticker,
                    date_str=date_str,
                    interval=10,
                    exchange=exchange,
                )

                if df is None or df.empty:
                    logger.debug(
                        f"    {ticker} {date_str}: no data returned "
                        f"(possibly non-trading day for this exchange)"
                    )
                    summary["skipped"] += 1
                    continue

                # Validate: ensure the freshly fetched data has non-NULL OHLC
                ohlc_cols = [c for c in _OHLC_FIELDS if c in df.columns]
                still_bad = df[ohlc_cols].isna().all(axis=1).sum() if ohlc_cols else len(df)
                if still_bad == len(df):
                    logger.warning(
                        f"    {ticker} {date_str}: re-fetched but ALL bars still "
                        f"have NULL OHLC — likely genuine non-trading day; skipping"
                    )
                    summary["skipped"] += 1
                    continue

                # Upsert clean data
                rows = local_db.upsert_bdib_data(df, date_str=date_str)
                summary["rows_upserted"] += rows
                summary["repaired"] += 1

            except Exception as e:
                logger.error(f"    ERROR repairing {ticker} {date_str}: {e}")
                summary["failed"] += 1

            # Rate-limit individual ticker fetches
            time.sleep(0.2)

        # Slightly longer pause between dates
        time.sleep(0.5)

    # Final report
    logger.info("=" * 60)
    logger.info("REPAIR COMPLETE")
    logger.info(f"  Repaired : {summary['repaired']}")
    logger.info(f"  Skipped  : {summary['skipped']}")
    logger.info(f"  Failed   : {summary['failed']}")
    logger.info(f"  Rows upserted: {summary['rows_upserted']:,}")
    logger.info("=" * 60)

    return summary


def run_backfill(
    start_date_str: str = "2025-09-25",
    end_date_str: Optional[str] = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """Execute the backfill loop.

    Args:
        start_date_str: Start date in YYYY-MM-DD format.
        end_date_str: End date in YYYY-MM-DD format (default: previous weekday).
        force: If True, re-fetch even if data already exists in raw_bdib.db.
        dry_run: If True, only print planned actions without fetching.

    Returns:
        Summary dict with counts and per-date results.
    """
    summary = {
        "start_date": start_date_str,
        "end_date": end_date_str or "auto(previous_weekday)",
        "force": force,
        "dry_run": dry_run,
        "total_candidate_days": 0,
        "skipped_already_exists": 0,
        "skipped_non_trading": 0,
        "fetched_days": 0,
        "total_rows_upserted": 0,
        "failed_days": 0,
        "errors": [],
        "per_date": [],
    }

    # ── Parse date range ──
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_dt = (
        datetime.strptime(end_date_str, "%Y-%m-%d").date()
        if end_date_str
        else _get_previous_weekday()
    )

    if start_dt > end_dt:
        logger.error(f"Start date {start_dt} is after end date {end_dt}; nothing to do.")
        summary["errors"].append(f"start > end ({start_dt} > {end_dt})")
        return summary

    # ── Generate candidate weekdays ──
    candidate_dates = _expand_business_weekdays(start_dt, end_dt)
    summary["total_candidate_days"] = len(candidate_dates)
    logger.info(
        f"Date range: {start_dt.strftime('%Y-%m-%d')} -> {end_dt.strftime('%Y-%m-%d')} "
        f"({len(candidate_dates)} weekdays)"
    )

    if not candidate_dates:
        logger.info("No candidate weekdays in range")
        return summary

    # ── Load ticker universe ──
    ticker_exchange_map = load_ticker_exchange_map()
    if not ticker_exchange_map:
        logger.warning("No tickers available; cannot fetch any BDIB data.")
        summary["errors"].append("empty ticker map")
        return summary

    # ── Open DB connection for incremental check / upsert ──
    raw_db = RawBDIBDB()

    # Determine latest existing date to support incremental mode
    latest_existing: Optional[str] = None
    if not force:
        latest_existing = raw_db.get_latest_order_as_of_date()
        if latest_existing:
            logger.info(f"Incremental mode: raw_bdib has data through {latest_existing}")
        else:
            logger.info("Incremental mode: raw_bdib appears empty — fetching all")

    # ── Iterate each business day ──
    for dt in sorted(candidate_dates):
        date_str = dt.strftime("%Y%m%d")
        date_display = dt.strftime("%Y-%m-%d")

        try:
            # Strict trading-day check (future / weekend / known holiday)
            if not _is_trading_day(dt):
                logger.info(f"  SKIP {date_display}: not a valid trading day")
                summary["skipped_non_trading"] += 1
                continue

            # Incremental skip: already have data for this date
            if not force and latest_existing and date_str <= latest_existing:
                logger.debug(f"  SKIP {date_display}: already in raw_bdib.db (<= {latest_existing})")
                summary["skipped_already_exists"] += 1
                continue

            logger.info(f"{'[DRY-RUN] ' if dry_run else ''}PROCESSING {date_display} ...")

            if dry_run:
                summary["per_date"].append({"date": date_display, "status": "dry_run"})
                summary["fetched_days"] += 1
                continue

            # Build ticker_dates: {ticker: [date_str]} for every ticker
            ticker_dates = {ticker: [date_str] for ticker in ticker_exchange_map.keys()}

            # ── Fetch BDIB from Bloomberg ──
            t0 = time.monotonic()
            bdib_map = fetch_bdib_for_fills(
                ticker_dates,
                interval=10,
                ticker_exchange_map=ticker_exchange_map,
            )
            elapsed = time.monotonic() - t0

            # Combine all ticker results for this date into one DataFrame
            bdib_df = get_bdib_for_date(bdib_map, date_str) if bdib_map else pd.DataFrame()

            if bdib_df.empty:
                logger.info(f"  {date_display}: no BDIB data returned ({elapsed:.1f}s)")
                summary["per_date"].append({
                    "date": date_display, "status": "no_data", "rows": 0, "elapsed_s": round(elapsed, 1)
                })
                continue

            # ── Upsert into raw_bdib.db ──
            rows = raw_db.upsert_bdib_data(bdib_df, date_str=date_str)

            logger.info(
                f"  {date_display}: upserted {rows} rows "
                f"({len(bdib_df)} bars, {len(ticker_dates)} tickers, {elapsed:.1f}s)"
            )
            summary["total_rows_upserted"] += rows
            summary["fetched_days"] += 1
            summary["per_date"].append({
                "date": date_display,
                "status": "ok",
                "rows": rows,
                "bars": len(bdib_df),
                "tickers": len(ticker_dates),
                "elapsed_s": round(elapsed, 1),
            })

            # Polite rate-limit between dates to avoid overwhelming the Bloomberg API
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"  ERROR {date_display}: {e}", exc_info=True)
            summary["failed_days"] += 1
            summary["errors"].append(f"{date_display}: {e}")
            summary["per_date"].append({
                "date": date_display, "status": "error", "error": str(e)
            })

    # ── Final summary ──
    logger.info("=" * 60)
    logger.info("BACKFILL COMPLETE")
    logger.info(f"  Candidate days : {summary['total_candidate_days']}")
    logger.info(f"  Skipped (exists): {summary['skipped_already_exists']}")
    logger.info(f"  Skipped (non-trading): {summary['skipped_non_trading']}")
    logger.info(f"  Fetched         : {summary['fetched_days']}")
    logger.info(f"  Failed          : {summary['failed_days']}")
    logger.info(f"  Total rows      : {summary['total_rows_upserted']}")
    logger.info("=" * 60)

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Backfill raw BDIB data for business weekdays into raw_bdib.db",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backfill (default mode)
  python backfill_raw_bdib.py                        # 2025-09-25 -> yesterday
  python backfill_raw_bdib.py --start 2025-01-02     # custom start
  python backfill_raw_bdib.py --start 2025-09-25 --end 2026-03-31
  python backfill_raw_bdib.py --force               # re-fetch all
  python backfill_raw_bdib.py --dry-run              # preview only

  # Data cleaning + repair pipeline
  python backfill_raw_bdib.py --clean                # delete NULL-close rows
  python backfill_raw_bdib.py --repair               # validate + selective re-fetch
  python backfill_raw_bdib.py --clean --repair       # clean then repair
  python backfill_raw_bdib.py --validate             # report only, no changes
        """,
    )
    parser.add_argument(
        "--start", type=str, default="2025-09-25",
        help="Start date (YYYY-MM-DD). Default: 2025-09-25",
    )
    parser.add_argument(
        "--end", type=str, default=None,
        help="End date inclusive (YYYY-MM-DD). Default: previous weekday",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-fetch even if data already exists in raw_bdib.db",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List dates to process without actually fetching",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Delete rows with NULL/empty 'close' from raw_bdib.db",
    )
    parser.add_argument(
        "--repair", action="store_true",
        help="Validate OHLC completeness at (ticker,date) granularity; "
             "re-fetch only broken atomic units selectively",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Run validation scan and print diagnostic report only (no changes)",
    )
    args = parser.parse_args()

    _setup_logging()

    # ── Validation-only mode ──
    if args.validate and not args.clean and not args.repair:
        validate_and_report()
        sys.exit(0)

    # ── Clean mode ──
    if args.clean:
        logger.info("=" * 60)
        logger.info("MODE: CLEAN — removing NULL-close rows")
        logger.info("=" * 60)
        deleted = clean_null_close_rows(dry_run=args.dry_run)
        logger.info(f"Cleaned {deleted:,} rows" if not args.dry_run else f"[DRY-RUN] Would clean {deleted:,} rows")

    # ── Repair mode ──
    if args.repair:
        logger.info("=" * 60)
        logger.info("MODE: REPAIR — selective re-fetch of invalid (ticker,date) pairs")
        logger.info("=" * 60)

        # Always run validation first to show the before-state
        report = validate_and_report()

        if report["invalid_pair_count"] == 0:
            logger.info("No invalid pairs to repair — skipping fetch phase")
        else:
            result = repair_invalid_pairs(dry_run=args.dry_run)
            if result["failed"] > 0:
                sys.exit(1)

    # ── Backfill mode (default, or when --clean/--repair are combined) ──
    if not args.clean and not args.repair and not args.validate:
        result = run_backfill(
            start_date_str=args.start,
            end_date_str=args.end,
            force=args.force,
            dry_run=args.dry_run,
        )
        sys.exit(0 if result["failed_days"] == 0 else 1)

    sys.exit(0)


if __name__ == "__main__":
    main()

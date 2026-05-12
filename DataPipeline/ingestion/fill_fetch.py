"""
FillFetch Module — Bloomberg EMSX History API data retrieval.

Pipeline:
    1. Fetches fill data via Bloomberg EMSX History API (blpapi, TradingSystem scope)
    2. Computes SHA-256 hash for duplicate detection
    3. Deduplicates via in-memory hash index (O(1)) with DB fallback
    4. Upserts raw API data to raw_fills.db (primary storage)
    5. Tracks fetch history in fetch_log table

Optimizations:
    - Session reuse: single Bloomberg connection for entire date range
    - In-memory hash preload: O(1) per-day dedup without DB round-trip
    - Exponential back-off retry on transient failures
    - Schema migration: auto-adds missing derived columns to old DB files

Note on parallelism:
    Parallel Bloomberg sessions do NOT improve throughput because the bottleneck is
    the server-side PARTIAL_RESPONSE streaming (~4000 rows/s fixed rate). Multiple
    sessions share the same server bandwidth. This has been verified by benchmarking.

Migrated from CostView/src/fill_fetch.py.
BloombergFillFetcher extracted to DataPipeline.acquisition.bloomberg_fill_fetcher.
SQLAlchemy FillFetchDatabase replaced with ConnectionManager-based FillFetchDatabase.
"""

import os
import sys
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional, Tuple, Set
from collections import defaultdict

import pandas as pd
from dotenv import load_dotenv

from DataPipeline.storage.connection import ConnectionManager, AccessTier
from DataPipeline.storage.schema.columns import EMSX_FILL_COLUMNS
from DataPipeline.storage.repositories.fetch_history import SqliteFetchHistoryRepository, compute_data_hash
from DataPipeline.acquisition._constants import (
    FILL_FIELD_EXTRACTORS,
)
from DataPipeline.acquisition.bloomberg_fill_fetcher import (
    BloombergFillFetcher,
    EMSXSessionError,
    EMSXServiceError,
    EMSXRequestError,
    _parse_fill_message,
)

load_dotenv()

logger = logging.getLogger(__name__)

def get_previous_weekday(today: Optional[date] = None) -> date:
    """Return the most recent completed weekday (not including today).

    Rules:
        - Mon-Fri -> yesterday
        - Saturday -> Friday
        - Sunday -> Friday
    """
    if today is None:
        today = date.today()
    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:  # Sat=5, Sun=6
        candidate -= timedelta(days=1)
    return candidate


# ── Bloomberg EMSX Constants ─────────────────────────────────────────────

    raise RuntimeError(
        f"FILL_FIELD_EXTRACTORS keys out of sync with EMSX_FILL_COLUMNS. "
        f"Missing: {missing}, Extra: {extra}"
    )

EXPECTED_FILL_COLUMNS: List[str] = EMSX_FILL_COLUMNS


def fills_so_far_str(count: int) -> str:
    """Return a human-readable description of partial fetch progress."""
    return f"{count} fill(s) received so far"


# ── Main FillFetch Class ─────────────────────────────────────────────────

class FillFetch:
    """Main FillFetch class that orchestrates the fetch process.

    Pipeline:
        1. Given a date and optional Team, fetch fill data
        2. Compute the SHA-256 hash
        3. Check for duplicate via in-memory hash index + DB fallback
        4. Upsert raw API data to raw_fills.db
        5. Record in fetch_log
        6. Optionally save Excel file as archive
    """

    def __init__(self, data_dir: Optional[str] = None, db_path: Optional[str] = None):
        self.data_dir = Path(data_dir or os.getenv('FILLFETCH_DATA_DIR', './data/fills'))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Primary DB access via repositories
        self.raw_fill_read = None
        self.raw_fill_write = None
        try:
            from DataPipeline.storage.repositories.raw_fills import SqliteRawFillReadRepository
            from DataPipeline.storage.repositories.raw_fills import SqliteRawFillWriteRepository
            cm = ConnectionManager()
            self.raw_fill_read = SqliteRawFillReadRepository(cm)
            self.raw_fill_write = SqliteRawFillWriteRepository(cm)
        except Exception as e:
            logger.warning(f"raw_fill_read/raw_fill_write init unavailable: {e}")

        # Fetch history DB
        self.db: Optional[SqliteFetchHistoryRepository] = None
        try:
            if db_path is not None:
                p = Path(db_path).resolve()
                p.parent.mkdir(parents=True, exist_ok=True)
                mgr = ConnectionManager(path_overrides={"fill_fetch_history": p})
                self.db = SqliteFetchHistoryRepository(connection_manager=mgr)
            else:
                self.db = SqliteFetchHistoryRepository()
        except Exception:
            pass

        self._known_hashes: Dict[str, Set[str]] = defaultdict(set)
        self._preload_known_hashes()

        logger.info(f"FillFetch initialized: data_dir={self.data_dir}, "
                     f"preloaded_hashes={sum(len(s) for s in self._known_hashes.values())}")

    def _preload_known_hashes(self):
        if self.raw_fill_read is not None:
            try:
                stats = self.raw_fill_read.get_fetch_log_stats()
                for record in stats:
                    date_key = record.get('source_date', '')
                    h = record.get('data_hash', '')
                    if date_key and h:
                        self._known_hashes[date_key].add(h)
                logger.debug(f"Preloaded {sum(len(s) for s in self._known_hashes.values())} hash entries")
            except Exception as e:
                logger.debug(f"Could not preload hashes (non-fatal): {e}")

    def _is_duplicate_in_memory(self, date_compact: str, hash_value: str) -> bool:
        return hash_value in self._known_hashes.get(date_compact, set())

    def _record_hash_in_memory(self, date_compact: str, hash_value: str):
        self._known_hashes[date_compact].add(hash_value)

    def determine_fetch_range(self) -> Optional[Tuple[date, date]]:
        from DataPipeline.config import Config as Cfg
        today = date.today()
        prev_wd = get_previous_weekday(today)
        last_fetch = None
        if self.raw_fill_read is not None:
            try:
                last_fetch = self.raw_fill_read.get_last_fetch_date()
            except Exception as e:
                logger.debug(f"Could not read fetch_log: {e}")
        last_processed = None
        try:
            from DataPipeline.storage.facade import CostViewDatabase
            proc_db = CostViewDatabase()
            dates = proc_db.fills_read.get_processed_dates(stage="processed")
            if dates:
                last_processed = datetime.strptime(dates[-1], "%Y%m%d").date()
        except Exception as e:
            logger.debug(f"Could not read processing_log: {e}")
        if last_fetch is None and last_processed is None:
            first_day = today - timedelta(days=Cfg.FIRST_RUN_LOOKBACK_DAYS)
            logger.info(f"FIRST RUN: fetching {first_day} -> {prev_wd}")
            return first_day, prev_wd
        anchor = max(last_fetch or date.min, last_processed or date.min)
        start = anchor + timedelta(days=1)
        if start > prev_wd:
            logger.info("Already up-to-date (start > previous weekday)")
            return None
        logger.info(f"INCREMENTAL: {start} -> {prev_wd}")
        return start, prev_wd

    def _get_date_range(self, target_date: date) -> Tuple[datetime, datetime]:
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date, datetime.max.time().replace(microsecond=0))
        return start, end

    def _save_to_excel(self, data: List[Dict[str, Any]], file_path: Path) -> bool:
        try:
            df = pd.DataFrame(data)
            for col in EXPECTED_FILL_COLUMNS:
                if col not in df.columns:
                    df[col] = None
            df.to_excel(file_path, index=False, engine='openpyxl')
            logger.info(f"Saved {len(data)} records to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save Excel: {e}")
            return False

    def fetch_day(self, target_date: date, team: Optional[str] = None,
                  skip_duplicates: bool = True, force: bool = False,
                  archive_excel: bool = False) -> Dict[str, Any]:
        if force:
            skip_duplicates = False
        order_date = target_date.strftime('%Y-%m-%d')
        date_compact = target_date.strftime('%Y%m%d')
        scope_desc = f"Team '{team}'" if team else "TradingSystem (login-based)"
        logger.info(f"Fetching fills for {order_date} ({scope_desc})")
        result: Dict[str, Any] = {
            'order_date': order_date, 'team': team, 'success': False,
            'skipped': False, 'rows_fetched': 0, 'hash_value': None,
            'rows_upserted': 0, 'file_path': None, 'error': None,
        }
        try:
            from_dt, to_dt = self._get_date_range(target_date)
            with BloombergFillFetcher() as client:
                fills = client.fetch_fills(from_dt, to_dt, team=team)
            if not fills:
                logger.info(f"No fills found for {order_date}")
                result['success'] = True
                result['message'] = "No fills found"
                return result
            hash_value = compute_data_hash(fills)
            result['hash_value'] = hash_value
            result['rows_fetched'] = len(fills)
            logger.info(f"Fetched {len(fills)} fills, hash={hash_value[:16]}...")
            if skip_duplicates:
                if self._is_duplicate_in_memory(date_compact, hash_value):
                    logger.info(f"Duplicate data found for {order_date} (memory), skipping")
                    result['skipped'] = True; result['success'] = True
                    result['message'] = f"Duplicate (hash={hash_value[:16]}...)"
                    return result
                if self.raw_fill_read is not None:
                    if self.raw_fill_write.check_fetch_duplicate(date_compact, hash_value):
                        logger.info(f"Duplicate data found for {order_date} (DB), skipping")
                        self._record_hash_in_memory(date_compact, hash_value)
                        result['skipped'] = True; result['success'] = True
                        result['message'] = f"Duplicate (hash={hash_value[:16]}...)"
                        return result
            try:
                from DataPipeline.processing.validate_raw_fills import validate_fill_data, save_anomaly_report
                val_result = validate_fill_data(fills, source_date=date_compact)
                result['validation'] = {
                    'success': val_result.success, 'total_orders': val_result.total_orders,
                    'failed_orders': val_result.failed_orders, 'pass_rate': f"{val_result.pass_rate:.2%}",
                }
                if not val_result.success and not val_result.anomalies_df.empty:
                    logger.warning(f"Validation FAILED for {order_date}: {val_result.failed_orders}/{val_result.total_orders}")
                    report_path = save_anomaly_report(val_result)
                    if report_path:
                        result['anomaly_report'] = str(report_path)
            except Exception as val_err:
                logger.warning(f"Fill-share validation skipped (error): {val_err}")
                result['validation'] = {'error': str(val_err)}
            rows_upserted = 0
            if self.raw_fill_read is not None:
                rows_upserted = self.raw_fill_write.upsert_raw_api_data(fills, source_date=date_compact)
            result['rows_upserted'] = rows_upserted
            if self.raw_fill_read is not None:
                self.raw_fill_write.add_fetch_log_record(source_date=date_compact, row_count=len(fills), data_hash=hash_value)
                self.raw_fill_write.upsert_order_fetch_log(fills, source_date=date_compact)
                self._record_hash_in_memory(date_compact, hash_value)
            if archive_excel:
                file_name = f"fills_{date_compact}.xlsx"
                if team:
                    file_name = f"fills_{date_compact}_{team}.xlsx"
                file_path = self.data_dir / file_name
                if self._save_to_excel(fills, file_path):
                    result['file_path'] = str(file_path)
            # Legacy fetch history DB sync (replaces FillFetchDatabase)
            if self.db is not None:
                try:
                    fetch_time = f"{from_dt.strftime('%H:%M:%S')}-{to_dt.strftime('%H:%M:%S')}"
                    self.db.add_fetch_record(order_date=order_date, fetch_time=fetch_time,
                                              row_count=len(fills), hash_value=hash_value,
                                              file_path=result.get('file_path'))
                except Exception:
                    pass
            result['success'] = True
            result['message'] = f"Fetched {len(fills)} fills, upserted {rows_upserted} to raw_fills.db"
            logger.info(f"Fetch completed for {order_date}: {result['message']}")
        except Exception as e:
            logger.error(f"Error fetching fills for {order_date}: {e}")
            result['error'] = str(e)
        return result

    def fetch_range(self, start_date: date, end_date: date,
                    team: Optional[str] = None, force: bool = False,
                    archive_excel: bool = False) -> List[Dict[str, Any]]:
        results = []
        current = start_date
        while current <= end_date:
            result = self.fetch_day(current, team=team, force=force, archive_excel=archive_excel)
            results.append(result)
            current += timedelta(days=1)
        return results

    def fetch_range_aggregated(self, start_date: date, end_date: date,
                               team: Optional[str] = None,
                               skip_duplicates: bool = True, force: bool = False,
                               archive_excel: bool = False,
                               progress_callback: Optional[Callable[[int, int, str, int, str], None]] = None) -> Dict[str, Any]:
        if force:
            skip_duplicates = False
        scope_desc = f"team={team}" if team else "TradingSystem (login-based)"
        logger.info(f"Starting aggregated fetch: {start_date} to {end_date} ({scope_desc})")
        all_records: List[Dict[str, Any]] = []
        day_summaries: List[Dict[str, Any]] = []
        saved_files: List[str] = []
        total_days = (end_date - start_date).days + 1
        skipped_days = 0; no_fill_days = 0; error_days = 0
        with BloombergFillFetcher() as client:
            current = start_date
            day_idx = 0
            while current <= end_date:
                if current.weekday() >= 5:
                    current += timedelta(days=1)
                    continue
                day_idx += 1
                order_date = current.strftime('%Y-%m-%d')
                date_compact = current.strftime('%Y%m%d')
                weekdays_in_range = max(1, sum(1 for i in range((end_date - start_date).days + 1)
                                               if (start_date + timedelta(days=i)).weekday() < 5))
                logger.info(f"[{day_idx}/{weekdays_in_range}] Processing {order_date}...")
                if progress_callback:
                    progress_callback(day_idx - 1, weekdays_in_range, order_date, 0, "Fetching from EMSX/Bloomberg…")
                try:
                    from_dt, to_dt = self._get_date_range(current)
                    fills = client.fetch_fills(from_dt, to_dt, team=team)
                    if not fills:
                        day_summaries.append({'order_date': order_date, 'rows': 0, 'status': 'empty'})
                        no_fill_days += 1
                        if progress_callback:
                            progress_callback(day_idx, weekdays_in_range, order_date, 0, "No fills found")
                        current += timedelta(days=1)
                        continue
                    hash_value = compute_data_hash(fills)
                    if skip_duplicates:
                        if self._is_duplicate_in_memory(date_compact, hash_value):
                            day_summaries.append({'order_date': order_date, 'rows': len(fills), 'status': 'skipped'})
                            skipped_days += 1
                            if progress_callback:
                                progress_callback(day_idx, weekdays_in_range, order_date, len(fills), "Duplicate (memory)")
                            current += timedelta(days=1)
                            continue
                        if self.raw_fill_read is not None:
                            if self.raw_fill_write.check_fetch_duplicate(date_compact, hash_value):
                                self._record_hash_in_memory(date_compact, hash_value)
                                day_summaries.append({'order_date': order_date, 'rows': len(fills), 'status': 'skipped'})
                                skipped_days += 1
                                if progress_callback:
                                    progress_callback(day_idx, weekdays_in_range, order_date, len(fills), "Duplicate (DB)")
                                current += timedelta(days=1)
                                continue
                    all_records.extend(fills)
                    try:
                        from DataPipeline.processing.validate_raw_fills import validate_fill_data, save_anomaly_report
                        val_result = validate_fill_data(fills, source_date=date_compact)
                        if not val_result.success and not val_result.anomalies_df.empty:
                            logger.warning(f"Validation FAILED for {order_date}: {val_result.failed_orders}/{val_result.total_orders}")
                            report_path = save_anomaly_report(val_result)
                            if report_path:
                                logger.warning(f"Anomaly report saved: {report_path}")
                    except Exception as val_err:
                        logger.warning(f"Fill-share validation skipped (error): {val_err}")
                    rows_upserted = 0
                    if self.raw_fill_read is not None:
                        rows_upserted = self.raw_fill_write.upsert_raw_api_data(fills, source_date=date_compact)
                        self.raw_fill_write.add_fetch_log_record(source_date=date_compact, row_count=len(fills), data_hash=hash_value)
                        self.raw_fill_write.upsert_order_fetch_log(fills, source_date=date_compact)
                        self._record_hash_in_memory(date_compact, hash_value)
                    if archive_excel:
                        day_file_name = f"fills_{date_compact}.xlsx"
                        if team:
                            day_file_name = f"fills_{date_compact}_{team}.xlsx"
                        day_file_path = self.data_dir / day_file_name
                        if self._save_to_excel(fills, day_file_path):
                            saved_files.append(str(day_file_path))
                    day_summaries.append({'order_date': order_date, 'rows': len(fills), 'rows_upserted': rows_upserted, 'status': 'fetched'})
                    logger.info(f"  Fetched {len(fills)} fills for {order_date} (upserted {rows_upserted})")
                    if progress_callback:
                        detail = f"{len(fills)} rows, upserted {rows_upserted}" if rows_upserted else f"{len(fills)} rows"
                        progress_callback(day_idx, weekdays_in_range, order_date, len(fills), detail)
                    if self.db is not None:
                        try:
                            fetch_time = f"{from_dt.strftime('%H:%M:%S')}-{to_dt.strftime('%H:%M:%S')}"
                            self.db.add_fetch_record(order_date=order_date, fetch_time=fetch_time,
                                                      row_count=len(fills), hash_value=hash_value,
                                                      file_path=saved_files[-1] if saved_files else None)
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"  Error fetching {order_date}: {e}")
                    day_summaries.append({'order_date': order_date, 'rows': 0, 'status': 'error', 'error': str(e)})
                    error_days += 1
                    if progress_callback:
                        progress_callback(day_idx, weekdays_in_range, order_date, 0, f"Error: {e}")
                current += timedelta(days=1)
        summary = {
            'start_date': start_date.strftime('%Y%m%d'),
            'end_date': end_date.strftime('%Y%m%d'),
            'scope': scope_desc, 'total_days': total_days,
            'days_fetched': len([s for s in day_summaries if s['status'] == 'fetched']),
            'days_skipped': skipped_days, 'days_empty': no_fill_days, 'days_error': error_days,
            'total_rows': len(all_records), 'files': saved_files, 'success': error_days == 0,
        }
        logger.info(f"Range fetch complete: {summary['total_rows']} rows across {summary['days_fetched']} days")
        return summary

    def get_history(self, order_date: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if self.raw_fill_read is not None:
            try:
                stats = self.raw_fill_read.get_fetch_log_stats()
                if order_date:
                    stats = [s for s in stats if s.get('source_date') == order_date.replace('-', '')]
                return stats[:limit]
            except Exception:
                pass
        if self.db is not None:
            return self.db.get_fetch_history(order_date, limit)
        return []

    def get_stats(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        if self.raw_fill_read is not None:
            try:
                stats['raw_fills_rows'] = self.raw_fill_read.get_row_count()
                stats['raw_fills_dates'] = self.raw_fill_read.get_date_row_counts()
            except Exception:
                pass
        if self.db is not None:
            try:
                stats['legacy'] = self.db.get_stats()
            except Exception:
                pass
        try:
            from DataPipeline.storage.facade import CostViewDatabase
            proc_db = CostViewDatabase()
            stats['execution_history'] = proc_db.fills_read.get_execution_history_stats()
        except Exception:
            pass
        return stats

    def close(self):
        if self.db is not None:
            self.db.close()


def setup_logging(level: str = "INFO"):
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )


def main():
    import argparse
    parser = argparse.ArgumentParser(description='FillFetch - EMSX Fill Data Fetcher')
    parser.add_argument('--date', type=str, help='Date to fetch (YYYY-MM-DD)')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--team', type=str, default=None, help='Team name')
    parser.add_argument('--force', action='store_true', help='Force re-fetch')
    parser.add_argument('--aggregate', action='store_true', help='Aggregate range fetch')
    parser.add_argument('--data-dir', type=str, help='Data directory')
    parser.add_argument('--db-path', type=str, help='Legacy database path')
    parser.add_argument('--history', action='store_true', help='Show fetch history')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    parser.add_argument('--get-teams', action='store_true', help='List EMSX teams')
    parser.add_argument('--get-trade-desks', action='store_true', help='List EMSX trade desks')
    parser.add_argument('--log-level', type=str, default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    parser.add_argument('--auto', action='store_true', help='Auto mode')
    parser.add_argument('--archive-excel', action='store_true', help='Save Excel archives')
    args = parser.parse_args()
    setup_logging(args.log_level)
    if args.get_teams or args.get_trade_desks:
        from DataPipeline.acquisition.emsx_client import EMSXHistoryClient
        with EMSXHistoryClient() as client:
            if args.get_trade_desks:
                desks = client.get_trade_desks()
                print("\n=== EMSX Trade Desks ===")
                for d in desks: print(f"  {d}")
            if args.get_teams:
                teams = client.get_teams()
                print("\n=== EMSX Teams ===")
                for t in teams: print(f"  {t}")
        return
    fetcher = FillFetch(data_dir=args.data_dir, db_path=args.db_path)
    try:
        if args.auto:
            fetch_range = fetcher.determine_fetch_range()
            if fetch_range is None:
                print("Already up-to-date. Nothing to fetch.")
                return
            start, end = fetch_range
            print(f"Auto mode: fetching {start} -> {end}")
            summary = fetcher.fetch_range_aggregated(start, end, team=args.team, force=args.force, archive_excel=args.archive_excel)
        elif args.date:
            d = datetime.strptime(args.date, '%Y-%m-%d').date()
            result = fetcher.fetch_day(d, team=args.team, force=args.force, archive_excel=args.archive_excel)
            _print_result(result)
            return
        elif args.start_date and args.end_date:
            start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
            end = datetime.strptime(args.end_date, '%Y-%m-%d').date()
            if args.aggregate:
                summary = fetcher.fetch_range_aggregated(start, end, team=args.team, force=args.force, archive_excel=args.archive_excel)
                _print_summary(summary)
            else:
                results = fetcher.fetch_range(start, end, team=args.team, force=args.force, archive_excel=args.archive_excel)
                for r in results:
                    _print_result(r)
            return
        elif args.history:
            history = fetcher.get_history()
            print(f"\nFetch History ({len(history)} records):")
            for h in history:
                print(f"  {h}")
            return
        elif args.stats:
            stats = fetcher.get_stats()
            print("\nFillFetch Statistics:")
            for k, v in stats.items():
                print(f"  {k}: {v}")
            return
        else:
            parser.print_help()
    finally:
        fetcher.close()


def _print_result(result: Dict[str, Any]):
    print(f"\n=== Fetch Result: {result['order_date']} ===")
    print(f"  Success: {result['success']}")
    print(f"  Skipped: {result.get('skipped', False)}")
    print(f"  Rows: {result['rows_fetched']} fetched, {result['rows_upserted']} upserted")
    if result.get('error'):
        print(f"  Error: {result['error']}")
    if result.get('validation'):
        print(f"  Validation: {result['validation']}")


def _print_summary(summary: Dict[str, Any]):
    print(f"\n=== Range Fetch Summary ===")
    print(f"  Range: {summary['start_date']} -> {summary['end_date']}")
    print(f"  Total days: {summary['total_days']}")
    print(f"  Fetched: {summary['days_fetched']}, Skipped: {summary['days_skipped']}")
    print(f"  Empty: {summary['days_empty']}, Errors: {summary['days_error']}")
    print(f"  Total rows: {summary['total_rows']}")


if __name__ == "__main__":
    main()

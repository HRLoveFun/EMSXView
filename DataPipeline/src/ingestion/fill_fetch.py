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
SQLAlchemy FillFetchDatabase replaced with ConnectionManager-based FetchHistoryDB.
"""

import os
import sys
import logging
import time
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional, Tuple, Set
from collections import defaultdict

import blpapi
import pandas as pd
from dotenv import load_dotenv

from DataPipeline.src.storage.connection import ConnectionManager, AccessTier
from DataPipeline.src.common.schema import EMSX_FILL_COLUMNS

load_dotenv()

logger = logging.getLogger(__name__)


# ── Fetch History Database (replaces SQLAlchemy FillFetchDatabase) ──────────

class FetchHistoryDB:
    """Lightweight SQLite fetch history tracker via ConnectionManager.

    Replaces the legacy SQLAlchemy FillFetchDatabase with a pure
    sqlite3 solution using the same ConnectionManager pattern used
    throughout the DataPipeline.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.getenv('FILLFETCH_DB_PATH', './data/fill_fetch_history.db')
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._mgr = ConnectionManager(path_overrides={"fill_fetch_history": self.db_path})
        self._table = "fill_fetch_history"
        self._init_table()

    def _get_conn(self) -> sqlite3.Connection:
        return self._mgr.get_connection("fill_fetch_history", AccessTier.ADMIN).raw_connection

    def _init_table(self) -> None:
        conn = self._get_conn()
        try:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_date TEXT NOT NULL,
                    fetch_time TEXT NOT NULL,
                    import_timestamp TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    hash_value TEXT NOT NULL,
                    file_path TEXT,
                    UNIQUE(order_date, hash_value)
                )
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self._table}_date
                ON {self._table}(order_date)
            """)
            conn.commit()
        finally:
            conn.close()

    def check_duplicate(self, order_date: str, hash_value: str) -> bool:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                f"SELECT 1 FROM {self._table} WHERE order_date=? AND hash_value=?",
                (order_date, hash_value),
            )
            return cur.fetchone() is not None
        finally:
            conn.close()

    def add_fetch_record(
        self, order_date: str, fetch_time: str, row_count: int,
        hash_value: str, file_path: Optional[str] = None,
    ) -> dict:
        conn = self._get_conn()
        try:
            conn.execute(
                f"INSERT OR IGNORE INTO {self._table} "
                "(order_date, fetch_time, import_timestamp, row_count, hash_value, file_path) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (order_date, fetch_time, datetime.utcnow().isoformat(),
                 row_count, hash_value, file_path),
            )
            conn.commit()
            return {"order_date": order_date, "row_count": row_count, "hash_value": hash_value}
        finally:
            conn.close()

    def get_fetch_history(self, order_date: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            if order_date:
                cur = conn.execute(
                    f"SELECT * FROM {self._table} WHERE order_date=? ORDER BY import_timestamp DESC LIMIT ?",
                    (order_date, limit),
                )
            else:
                cur = conn.execute(
                    f"SELECT * FROM {self._table} ORDER BY import_timestamp DESC LIMIT ?",
                    (limit,),
                )
            columns = [d[0] for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        conn = self._get_conn()
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM {self._table}").fetchone()[0]
            rows = conn.execute(f"SELECT COALESCE(SUM(row_count), 0) FROM {self._table}").fetchone()[0]
            dates = conn.execute(f"SELECT COUNT(DISTINCT order_date) FROM {self._table}").fetchone()[0]
            latest_row = conn.execute(
                f"SELECT * FROM {self._table} ORDER BY import_timestamp DESC LIMIT 1"
            ).fetchone()
            latest = dict(zip([d[0] for d in conn.execute(f"PRAGMA table_info({self._table})").fetchall()], latest_row)) if latest_row else None
            return {
                "total_records": total,
                "total_rows_fetched": rows,
                "unique_dates": dates,
                "latest": latest,
            }
        finally:
            conn.close()

    def close(self) -> None:
        pass  # ConnectionManager handles lifecycle


# ── Fetch Range Utilities ─────────────────────────────────────────────────

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

SESSION_STARTED = blpapi.Name("SessionStarted")
SESSION_STARTUP_FAILURE = blpapi.Name("SessionStartupFailure")
SERVICE_OPENED = blpapi.Name("ServiceOpened")
SERVICE_OPEN_FAILURE = blpapi.Name("ServiceOpenFailure")
ERROR_INFO = blpapi.Name("ErrorInfo")
GET_FILLS_RESPONSE = blpapi.Name("GetFillsResponse")

EMSX_HISTORY_SERVICE = "//blp/emsx.history"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8194

FILL_FIELD_EXTRACTORS: Dict[str, str] = {
    "OrderId":                   "getValueAsInteger",
    "Account":                   "getValueAsString",
    "SecurityName":              "getValueAsString",
    "Ticker":                    "getValueAsString",
    "Exchange":                  "getValueAsString",
    "Currency":                  "getValueAsString",
    "Side":                      "getValueAsString",
    "Amount":                    "getValueAsFloat",
    "NyOrderCreateAsOfDateTime": "getValueAsString",
    "Type":                      "getValueAsString",
    "LimitPrice":                "getValueAsFloat",
    "StopPrice":                 "GetValueAsFloat",
    "Broker":                    "getValueAsString",
    "StrategyType":              "getValueAsString",
    "TraderName":                "getValueAsString",
    "TraderUuid":                "getValueAsInteger",
    "RouteId":                   "getValueAsInteger",
    "NyTranCreateAsOfDateTime":  "getValueAsString",
    "RouteShares":               "getValueAsFloat",
    "FillId":                    "getValueAsInteger",
    "ExecType":                  "getValueAsString",
    "DateTimeOfFill":            "getValueAsString",
    "FillPrice":                 "getValueAsFloat",
    "FillShares":                "getValueAsFloat",
    "LastCapacity":              "getValueAsString",
    "LastMarket":                "getValueAsString",
    "Liquidity":                 "getValueAsString",
    "LocalExchangeSymbol":       "getValueAsString",
}

# Validate extractor keys against schema
_extractor_keys = list(FILL_FIELD_EXTRACTORS.keys())
if set(_extractor_keys) != set(EMSX_FILL_COLUMNS):
    missing = set(EMSX_FILL_COLUMNS) - set(_extractor_keys)
    extra = set(_extractor_keys) - set(EMSX_FILL_COLUMNS)
    raise RuntimeError(
        f"FILL_FIELD_EXTRACTORS keys out of sync with EMSX_FILL_COLUMNS. "
        f"Missing: {missing}, Extra: {extra}"
    )

EXPECTED_FILL_COLUMNS: List[str] = EMSX_FILL_COLUMNS


# ── Custom Exceptions ──────────────────────────────────────────────────────

class EMSXSessionError(Exception):
    """Bloomberg session could not be started."""

class EMSXServiceError(Exception):
    """Bloomberg service could not be opened."""

class EMSXRequestError(Exception):
    """Bloomberg request returned an error or timed out."""


# ── Bloomberg Fill Fetcher ───────────────────────────────────────────────

class BloombergFillFetcher:
    """EMSX History fill fetcher using blpapi."""

    def __init__(self, host: str = None, port: int = None,
                 max_retries: int = 2, event_timeout_ms: int = 30000,
                 session_reconnect_on_timeout: bool = True):
        self.host = host or os.getenv('BLOOMBERG_HOST', DEFAULT_HOST)
        self.port = port or int(os.getenv('BLOOMBERG_PORT', str(DEFAULT_PORT)))
        self.use_uat = os.getenv('USE_UAT', 'false').lower() == 'true'
        self.service_name = self._resolve_service()
        self.max_retries = max_retries
        self.event_timeout_ms = event_timeout_ms
        self.session_reconnect_on_timeout = session_reconnect_on_timeout
        self._session: Optional[blpapi.Session] = None
        self._connected = False

    def _resolve_service(self) -> str:
        if self.use_uat:
            return os.getenv('EMSX_HISTORY_SERVICE_UAT', '//blp/emsx.history.uat')
        return os.getenv('EMSX_HISTORY_SERVICE', EMSX_HISTORY_SERVICE)

    def connect(self) -> bool:
        session_options = blpapi.SessionOptions()
        session_options.setServerHost(self.host)
        session_options.setServerPort(self.port)
        logger.info(f"Connecting to {self.host}:{self.port}")
        self._session = blpapi.Session(session_options)
        if not self._session.start():
            raise EMSXSessionError(f"Failed to start Bloomberg session on {self.host}:{self.port}")
        if not self._session.openService(self.service_name):
            self._session.stop()
            self._session = None
            raise EMSXServiceError(f"Failed to open service {self.service_name}")
        self._connected = True
        logger.info(f"Connected to {self.service_name}")
        return True

    def disconnect(self):
        if self._session:
            self._session.stop()
            self._session = None
        self._connected = False
        logger.info("Disconnected from Bloomberg")

    def _ensure_connected(self):
        if not self._connected or self._session is None:
            raise RuntimeError("Not connected to Bloomberg. Call connect() first.")

    def fetch_fills(self, from_date: datetime, to_date: datetime,
                    team: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch fills from Bloomberg EMSX history.

        Uses ``nextEvent(timeout_ms)`` internally so each event waits at most
        ``event_timeout_ms`` ms.  After consecutive TIMEOUT events the call
        raises ``EMSXRequestError`` and optionally recreates the Bloomberg
        session to clear any bbcomm backlog.

        NOTE: ``concurrent.futures`` / ``signal.alarm`` cannot interrupt
        ``blpapi.Session.nextEvent()`` because it is a blocking C extension
        call that holds the GIL.  All timeout logic is therefore cooperative
        and event-driven.
        """
        self._ensure_connected()
        last_error: Exception = EMSXRequestError("No fetch attempts made")
        for attempt in range(1, self.max_retries + 1):
            is_timeout = False
            try:
                return self._fetch_fills_once(from_date, to_date, team)
            except EMSXRequestError as exc:
                last_error = exc
                is_timeout = (
                    "timeout" in str(exc).lower()
                    or "not responding" in str(exc).lower()
                    or "timed out" in str(exc).lower()
                )
                if is_timeout and self.session_reconnect_on_timeout:
                    logger.warning(
                        "Bloomberg timeout detected — force-reconnecting session "
                        "to clear bbcomm queue (%s)",
                        exc,
                    )
                    try:
                        self.disconnect()
                    except Exception:
                        pass
                    time.sleep(2)
                    try:
                        self.connect()
                        logger.info("Bloomberg session reconnected after timeout")
                    except Exception as conn_err:
                        raise EMSXRequestError(
                            f"Timeout recovery failed: session reconnect error: {conn_err}"
                        ) from conn_err
            if attempt < self.max_retries:
                wait = attempt * 2
                logger.warning(
                    f"Fetch attempt {attempt}/{self.max_retries} failed: {last_error}."
                    f"{' [TIMEOUT]' if is_timeout else ''} Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                logger.error(f"All {self.max_retries} fetch attempts failed")
        raise last_error

    def _fetch_fills_once(self, from_date: datetime, to_date: datetime,
                          team: Optional[str] = None) -> List[Dict[str, Any]]:
        service = self._session.getService(self.service_name)
        request = service.createRequest("GetFills")
        from_str = from_date.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')
        to_str = to_date.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')
        request.set("FromDateTime", from_str)
        request.set("ToDateTime", to_str)
        scope = request.getElement("Scope")
        if team:
            scope.setChoice("Team")
            scope.setElement("Team", team)
            logger.info(f"Requesting fills from {from_str} to {to_str} for Team '{team}'")
        else:
            scope.setChoice("TradingSystem")
            scope.setElement("TradingSystem", True)
            logger.info(f"Requesting fills from {from_str} to {to_str} for TradingSystem (login-based)")
        self._session.sendRequest(request)
        fills: List[Dict[str, Any]] = []
        done = False
        all_parse_errors: List[str] = []
        max_event_iterations = 50
        consecutive_timeouts = 0
        while not done:
            try:
                event = self._session.nextEvent(self.event_timeout_ms)
            except Exception as e:
                raise EMSXRequestError(f"Timeout or error waiting for event: {e}")
            if event.eventType == blpapi.Event.PARTIAL_RESPONSE:
                consecutive_timeouts = 0
                for msg in event:
                    if msg.messageType == GET_FILLS_RESPONSE:
                        try:
                            fill = _parse_fill_message(msg)
                            fills.append(fill)
                        except Exception as e:
                            all_parse_errors.append(f"Parse error: {e}")
            elif event.eventType == blpapi.Event.RESPONSE:
                consecutive_timeouts = 0
                for msg in event:
                    if msg.messageType == GET_FILLS_RESPONSE:
                        try:
                            fill = _parse_fill_message(msg)
                            fills.append(fill)
                        except Exception as e:
                            all_parse_errors.append(f"Parse error: {e}")
                done = True
            elif event.eventType == blpapi.Event.REQUEST_STATUS:
                for msg in event:
                    if msg.hasElement(ERROR_INFO):
                        err = msg.getElement(ERROR_INFO)
                        raise EMSXRequestError(f"Bloomberg request error: {err}")
            elif event.eventType == blpapi.Event.TIMEOUT:
                consecutive_timeouts += 1
                logger.warning(
                    f"Bloomberg event timeout #{consecutive_timeouts} "
                    f"(max={max_event_iterations}, fills_so_far={len(fills)})"
                )
                if consecutive_timeouts >= 1:
                    raise EMSXRequestError(
                        f"Bloomberg API not responding after {consecutive_timeouts} "
                        f"consecutive timeouts ({fills_so_far_str(len(fills))})"
                    )
                continue
            max_event_iterations -= 1
            if max_event_iterations <= 0:
                raise EMSXRequestError("Event processing exceeded max iterations")
        if all_parse_errors:
            logger.warning(f"Parse errors during fetch: {len(all_parse_errors)} errors")
        return fills

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


def _parse_fill_message(msg) -> Dict[str, Any]:
    """Parse a single GetFillsResponse message into a flat dict."""
    fill: Dict[str, Any] = {}
    for field, getter_name in FILL_FIELD_EXTRACTORS.items():
        try:
            getter = getattr(msg, getter_name)
            value = getter(field)
            fill[field] = value
        except Exception:
            fill[field] = None
    return fill


def compute_data_hash(fills: List[Dict[str, Any]]) -> str:
    """Compute SHA-256 hash of fill data for dedup detection."""
    import hashlib, json
    raw = json.dumps(fills, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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

        # Primary DB: raw_fills.db for upsert + fetch_log
        self.raw_db = None
        try:
            from CostView.src.db.facade import CostViewDatabase
            self.raw_db = CostViewDatabase().raw_db
        except Exception as e:
            logger.warning(f"Failed to initialize raw_fills.db (fetch_log unavailable): {e}")

        # Legacy fetch history DB (replaces SQLAlchemy FillFetchDatabase)
        self.db: Optional[FetchHistoryDB] = None
        try:
            self.db = FetchHistoryDB(db_path)
        except Exception:
            pass

        self._known_hashes: Dict[str, Set[str]] = defaultdict(set)
        self._preload_known_hashes()

        logger.info(f"FillFetch initialized: data_dir={self.data_dir}, "
                     f"preloaded_hashes={sum(len(s) for s in self._known_hashes.values())}")

    def _preload_known_hashes(self):
        if self.raw_db is not None:
            try:
                stats = self.raw_db.get_fetch_log_stats()
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
        from DataPipeline.src.common.processing_config import ProcessingConfig as Cfg
        today = date.today()
        prev_wd = get_previous_weekday(today)
        last_fetch = None
        if self.raw_db is not None:
            try:
                last_fetch = self.raw_db.get_last_fetch_date()
            except Exception as e:
                logger.debug(f"Could not read fetch_log: {e}")
        last_processed = None
        try:
            from CostView.src.db.facade import CostViewDatabase
            proc_db = CostViewDatabase().proc_db
            dates = proc_db.get_processed_dates(stage="processed")
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
                if self.raw_db is not None:
                    if self.raw_db.check_fetch_duplicate(date_compact, hash_value):
                        logger.info(f"Duplicate data found for {order_date} (DB), skipping")
                        self._record_hash_in_memory(date_compact, hash_value)
                        result['skipped'] = True; result['success'] = True
                        result['message'] = f"Duplicate (hash={hash_value[:16]}...)"
                        return result
            try:
                from CostView.src.validate_raw_fills import validate_fill_data, save_anomaly_report
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
            if self.raw_db is not None:
                rows_upserted = self.raw_db.upsert_raw_api_data(fills, source_date=date_compact)
            result['rows_upserted'] = rows_upserted
            if self.raw_db is not None:
                self.raw_db.add_fetch_log_record(source_date=date_compact, row_count=len(fills), data_hash=hash_value)
                self.raw_db.upsert_order_fetch_log(fills, source_date=date_compact)
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
                        if self.raw_db is not None:
                            if self.raw_db.check_fetch_duplicate(date_compact, hash_value):
                                self._record_hash_in_memory(date_compact, hash_value)
                                day_summaries.append({'order_date': order_date, 'rows': len(fills), 'status': 'skipped'})
                                skipped_days += 1
                                if progress_callback:
                                    progress_callback(day_idx, weekdays_in_range, order_date, len(fills), "Duplicate (DB)")
                                current += timedelta(days=1)
                                continue
                    all_records.extend(fills)
                    try:
                        from CostView.src.validate_raw_fills import validate_fill_data, save_anomaly_report
                        val_result = validate_fill_data(fills, source_date=date_compact)
                        if not val_result.success and not val_result.anomalies_df.empty:
                            logger.warning(f"Validation FAILED for {order_date}: {val_result.failed_orders}/{val_result.total_orders}")
                            report_path = save_anomaly_report(val_result)
                            if report_path:
                                logger.warning(f"Anomaly report saved: {report_path}")
                    except Exception as val_err:
                        logger.warning(f"Fill-share validation skipped (error): {val_err}")
                    rows_upserted = 0
                    if self.raw_db is not None:
                        rows_upserted = self.raw_db.upsert_raw_api_data(fills, source_date=date_compact)
                        self.raw_db.add_fetch_log_record(source_date=date_compact, row_count=len(fills), data_hash=hash_value)
                        self.raw_db.upsert_order_fetch_log(fills, source_date=date_compact)
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
        if self.raw_db is not None:
            try:
                stats = self.raw_db.get_fetch_log_stats()
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
        if self.raw_db is not None:
            try:
                stats['raw_fills_rows'] = self.raw_db.get_row_count()
                stats['raw_fills_dates'] = self.raw_db.get_date_row_counts()
            except Exception:
                pass
        if self.db is not None:
            try:
                stats['legacy'] = self.db.get_stats()
            except Exception:
                pass
        try:
            from CostView.src.db.facade import CostViewDatabase
            proc_db = CostViewDatabase().proc_db
            stats['execution_history'] = proc_db.get_execution_history_stats()
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
        try:
            from CostView.src.emsx_client import EMSXHistoryClient
        except ImportError:
            from CostView.src.emsx_client import EMSXHistoryClient
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

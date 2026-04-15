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
"""

import os
import sys
import logging
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from collections import defaultdict

import blpapi
import pandas as pd
from dotenv import load_dotenv

try:
    from src.database import FillFetchDatabase, compute_data_hash
except ImportError:
    from .database import FillFetchDatabase, compute_data_hash

try:
    from src.schema import EMSX_FILL_COLUMNS
except ImportError:
    from .schema import EMSX_FILL_COLUMNS

load_dotenv()

logger = logging.getLogger(__name__)


# ── Fetch Range Utilities ─────────────────────────────────────────────────

def get_previous_weekday(today: Optional[date] = None) -> date:
    """Return the most recent completed weekday (not including today).

    Rules:
        - Mon–Fri → yesterday
        - Saturday → Friday
        - Sunday → Friday
    """
    if today is None:
        today = date.today()
    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:  # Sat=5, Sun=6
        candidate -= timedelta(days=1)
    return candidate


# ── Bloomberg EMSX Constants (from explore_fill_history.ipynb) ─────────────

SESSION_STARTED = blpapi.Name("SessionStarted")
SESSION_STARTUP_FAILURE = blpapi.Name("SessionStartupFailure")
SERVICE_OPENED = blpapi.Name("ServiceOpened")
SERVICE_OPEN_FAILURE = blpapi.Name("ServiceOpenFailure")
ERROR_INFO = blpapi.Name("ErrorInfo")
GET_FILLS_RESPONSE = blpapi.Name("GetFillsResponse")

EMSX_HISTORY_SERVICE = "//blp/emsx.history"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8194

# Fill field -> blpapi getter, matching notebook's explicit extraction order
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

    # -- Commented fields --
    # "AssetClass":                "getValueAsString",
    # "BasketId":                  "getValueAsInteger",
    # "BasketName":                "getValueAsString",
    # "BBGID":                     "getValueAsString",
    # "BlockId":                   "getValueAsString",
    # "ClearingAccount":           "getValueAsString",
    # "ClearingFirm":              "GetValueAsString",
    # "ContractExpDate":           "GetValueAsString",
    # "CorrectedFillId":           "GetValueAsInteger",
    # "Cusip":                     "GetValueAsString",
    # "ExecPrevSeqNo":             "GetValueAsInteger",
    # "RouteNotes":                "GetValueAsString",
    # "ExecutingBroker":           "GetValueAsString",
    # "InvestorID":                "GetValueAsString",
    # "IsCfd":                     "GetValueAsBool",
    # "Isin":                      "GetValueAsString",
    # "IsLeg":                     "GetValueAsBool",
    # "LocateBroker":              "GetValueAsString",
    # "LocateId":                  "GetValueAsString",
    # "LocateRequired":            "GetValueAsBool",
    # "MultilegId":                "GetValueAsString",
    # "OCCSymbol":                 "GetValueAsString",
    # "OrderExecutionInstruction": "GetValueAsString",
    # "OrderHandlingInstruction":  "GetValueAsString",
    # "OrderInstruction":          "GetValueAsString",
    # "OrderOrigin":               "GetValueAsString",
    # "OrderReferenceId":          "GetValueAsString",
    # "OriginatingTraderUuid":     "GetValueAsInteger",
    # "ReroutedBroker":            "GetValueAsString",
    # "RouteCommissionAmount":     "GetValueAsFloat",
    # "RouteCommissionRate":       "GetValueAsFloat",
    # "RouteExecutionInstruction": "GetValueAsString",
    # "RouteHandlingInstruction":  "GetValueAsString",
    # "RouteNetMoney":             "GetValueAsFloat",
    # "Sedol":                     "GetValueAsString",
    # "SettlementDate":            "GetValueAsString",
    # "TIF":                       "GetValueAsString",
    # "UserCommissionAmount":      "GetValueAsFloat",
    # "UserCommissionRate":        "GetValueAsFloat",
    # "UserFees":                  "GetValueAsFloat",
    # "UserNetMoney":              "GetValueAsFloat",
    # "YellowKey":                 "GetValueAsString",
}

# Validate FILL_FIELD_EXTRACTORS keys against authoritative schema
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


# ── Bloomberg Fill Fetcher (from explore_fill_history.ipynb) ───────────────

class BloombergFillFetcher:
    """
    EMSX History fill fetcher using blpapi.

    Implements the event-driven pattern from explore_fill_history.ipynb with
    a synchronous wrapper. Supports session reuse across multiple fetch_fills()
    calls and configurable retry with exponential back-off.

    Context manager usage:
        with BloombergFillFetcher() as client:
            fills = client.fetch_fills(start, end)
            more = client.fetch_fills(next_start, next_end)  # reuses same session
    """

    def __init__(self, host: str = None, port: int = None,
                 max_retries: int = 3, event_timeout_ms: int = 30000):
        self.host = host or os.getenv('BLOOMBERG_HOST', DEFAULT_HOST)
        self.port = port or int(os.getenv('BLOOMBERG_PORT', str(DEFAULT_PORT)))
        self.use_uat = os.getenv('USE_UAT', 'false').lower() == 'true'
        self.service_name = self._resolve_service()
        self.max_retries = max_retries
        self.event_timeout_ms = event_timeout_ms
        self._session: Optional[blpapi.Session] = None
        self._connected = False

    def _resolve_service(self) -> str:
        if self.use_uat:
            return os.getenv('EMSX_HISTORY_SERVICE_UAT', '//blp/emsx.history.uat')
        return os.getenv('EMSX_HISTORY_SERVICE', EMSX_HISTORY_SERVICE)

    def connect(self) -> bool:
        """Establish Bloomberg session and open EMSX History service."""
        session_options = blpapi.SessionOptions()
        session_options.setServerHost(self.host)
        session_options.setServerPort(self.port)

        logger.info(f"Connecting to {self.host}:{self.port}")

        self._session = blpapi.Session(session_options)

        if not self._session.start():
            raise EMSXSessionError(
                f"Failed to start Bloomberg session on {self.host}:{self.port}")

        if not self._session.openService(self.service_name):
            self._session.stop()
            self._session = None
            raise EMSXServiceError(f"Failed to open service {self.service_name}")

        self._connected = True
        logger.info(f"Connected to {self.service_name}")
        return True

    def disconnect(self):
        """Close Bloomberg session."""
        if self._session:
            self._session.stop()
            self._session = None
        self._connected = False
        logger.info("Disconnected from Bloomberg")

    def _ensure_connected(self):
        """Ensure we are connected."""
        if not self._connected or self._session is None:
            raise RuntimeError("Not connected to Bloomberg. Call connect() first.")

    def fetch_fills(self, from_date: datetime, to_date: datetime,
                    team: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch fills with automatic retry (exponential back-off)."""
        self._ensure_connected()

        last_error: Exception = EMSXRequestError("No fetch attempts made")
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._fetch_fills_once(from_date, to_date, team)
            except (EMSXRequestError, RuntimeError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    wait = attempt * 2
                    logger.warning(
                        f"Fetch attempt {attempt}/{self.max_retries} failed: {exc}. "
                        f"Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    logger.error(f"All {self.max_retries} fetch attempts failed")
        raise last_error

    def _fetch_fills_once(self, from_date: datetime, to_date: datetime,
                          team: Optional[str] = None) -> List[Dict[str, Any]]:
        """Single-attempt fill fetch matching notebook request pattern."""
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
        max_event_iterations = 500
        iteration = 0

        while not done:
            iteration += 1
            if iteration > max_event_iterations:
                raise EMSXRequestError(
                    f"Event loop safety limit reached ({max_event_iterations} iterations) "
                    f"without receiving final RESPONSE")

            event = self._session.nextEvent(self.event_timeout_ms)

            if event.eventType() == blpapi.Event.TIMEOUT:
                raise EMSXRequestError(
                    f"Request timed out after {self.event_timeout_ms}ms")

            if event.eventType() in (blpapi.Event.RESPONSE,
                                     blpapi.Event.PARTIAL_RESPONSE):
                for msg in event:
                    if msg.messageType() == ERROR_INFO:
                        error_code = msg.getElementAsInteger("ErrorCode")
                        error_msg = msg.getElementAsString("ErrorMsg")
                        raise EMSXRequestError(
                            f"EMSX Error {error_code}: {error_msg}")

                    if msg.messageType() == GET_FILLS_RESPONSE:
                        fills_elem = msg.getElement("Fills")
                        total = fills_elem.numValues()
                        logger.info(f"Received {total} fills in response")

                        for fill_val in fills_elem.values():
                            record, errors = self._parse_fill(fill_val)
                            if record is not None:
                                fills.append(record)
                            if errors:
                                all_parse_errors.extend(errors)

                if event.eventType() == blpapi.Event.RESPONSE:
                    done = True

        if all_parse_errors:
            from collections import Counter
            error_counts = Counter(all_parse_errors)
            summary_parts = [f"{field}({cnt}x)" for field, cnt in error_counts.most_common(10)]
            logger.warning(
                f"Field parse issues across {len(fills)} fills: "
                f"{', '.join(summary_parts)}"
                f"{'...' if len(error_counts) > 10 else ''}")

        logger.info(f"Parsed {len(fills)} fill records ({len(EXPECTED_FILL_COLUMNS)} columns)")
        return fills

    @staticmethod
    def _parse_fill(fill) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        """Extract fields using type-specific getters from explore_fill_history.ipynb."""
        record: Dict[str, Any] = {}
        failed_fields: List[str] = []
        for field_name, getter_name in FILL_FIELD_EXTRACTORS.items():
            try:
                element = fill.getElement(field_name)
                record[field_name] = getattr(element, getter_name)()
            except Exception:
                record[field_name] = None
                failed_fields.append(field_name)

        if not any(v is not None for v in record.values()):
            logger.warning("Parsed fill resulted in all-None record")
            return None, failed_fields

        return record, failed_fields

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


# ── FillFetch Orchestrator ─────────────────────────────────────────────────

class FillFetch:
    """
    Main FillFetch class that orchestrates the fetch process.

    Pipeline:
        1. Given a date and optional Team, fetch fill data (TradingSystem scope by default)
        2. Compute the SHA-256 hash value of the fetched fill data
        3. Check for duplicate via in-memory hash index + DB fallback
        4. Upsert raw API data to raw_fills.db (primary storage)
        5. Record in fetch_log
        6. Optionally save Excel file as archive

    CLI usage:
        python -m src.fill_fetch --auto              # Auto-detect range & fetch
        python -m src.fill_fetch --start-date X --end-date Y  # Specific range
        python -m src.fill_fetch --date YYYY-MM-DD   # Single day
    """

    def __init__(self, data_dir: Optional[str] = None, db_path: Optional[str] = None):
        self.data_dir = Path(data_dir or os.getenv('FILLFETCH_DATA_DIR', './data/fills'))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Primary DB: raw_fills.db for upsert + fetch_log
        self.raw_db = None
        try:
            try:
                from src.raw_fills_db import RawFillsDB
            except ImportError:
                from .raw_fills_db import RawFillsDB
            self.raw_db = RawFillsDB()
        except Exception as e:
            logger.warning(f"Failed to initialize raw_fills.db (fetch_log unavailable): {e}")

        # Legacy DB: fill_fetch_history.db (deprecated, optional)
        self.db: Optional[FillFetchDatabase] = None
        try:
            self.db = FillFetchDatabase(db_path)
        except Exception:
            pass

        # In-memory hash index: preload all known hashes at init time for O(1) dedup
        self._known_hashes: Dict[str, Set[str]] = defaultdict(set)  # date_compact -> set[hash]
        self._preload_known_hashes()

        logger.info(f"FillFetch initialized: data_dir={self.data_dir}, "
                     f"preloaded_hashes={sum(len(s) for s in self._known_hashes.values())}")

    # ── In-memory Hash Index ─────────────────────────────────────────────

    def _preload_known_hashes(self):
        """Load all existing (date, hash) pairs into memory for O(1) dedup."""
        if self.raw_db is not None:
            try:
                stats = self.raw_db.get_fetch_log_stats()
                for record in stats:
                    date_key = record.get('source_date', '')
                    h = record.get('data_hash', '')
                    if date_key and h:
                        self._known_hashes[date_key].add(h)
                logger.debug(
                    f"Preloaded {sum(len(s) for s in self._known_hashes.values())} "
                    f"hash entries across {len(self._known_hashes)} dates"
                )
            except Exception as e:
                logger.debug(f"Could not preload hashes (non-fatal): {e}")

    def _is_duplicate_in_memory(self, date_compact: str, hash_value: str) -> bool:
        """O(1) in-memory dedup check without DB round-trip."""
        return hash_value in self._known_hashes.get(date_compact, set())

    def _record_hash_in_memory(self, date_compact: str, hash_value: str):
        """Record a new hash in the in-memory index."""
        self._known_hashes[date_compact].add(hash_value)

    # ── Determine Fetch Range ─────────────────────────────────────────────

    def determine_fetch_range(self) -> Optional[Tuple[date, date]]:
        """Determine whether to run first-time or incremental update.

        Stability design:
            - Dual anchor: fetch_log + processing_log, take the later one
            - If either is deleted, degrades to first-run (fetches more but loses nothing)
            - End date = previous weekday (excludes today and weekends)

        Returns:
            (start_date, end_date) or None if already up-to-date.
        """
        from .processing_config import ProcessingConfig as Cfg

        today = date.today()
        prev_wd = get_previous_weekday(today)

        # Anchor 1: fetch_log in raw_fills.db
        last_fetch = None
        if self.raw_db is not None:
            try:
                last_fetch = self.raw_db.get_last_fetch_date()
            except Exception as e:
                logger.debug(f"Could not read fetch_log: {e}")

        # Anchor 2: processing_log in processed_fills.db
        last_processed = None
        try:
            try:
                from src.processed_fills_db import ProcessedFillsDB
            except ImportError:
                from .processed_fills_db import ProcessedFillsDB
            proc_db = ProcessedFillsDB()
            dates = proc_db.get_processed_dates(stage="processed")
            if dates:
                last_processed = datetime.strptime(dates[-1], "%Y%m%d").date()
        except Exception as e:
            logger.debug(f"Could not read processing_log: {e}")

        if last_fetch is None and last_processed is None:
            first_day = today - timedelta(days=Cfg.FIRST_RUN_LOOKBACK_DAYS)
            logger.info(f"FIRST RUN: fetching {first_day} -> {prev_wd}")
            return first_day, prev_wd

        # Incremental: use the later anchor + 1 day
        anchor = max(
            last_fetch or date.min,
            last_processed or date.min,
        )
        start = anchor + timedelta(days=1)

        if start > prev_wd:
            logger.info("Already up-to-date (start > previous weekday)")
            return None

        logger.info(f"INCREMENTAL: {start} -> {prev_wd}")
        return start, prev_wd

    # ── Date Range Helper ─────────────────────────────────────────────────

    def _get_date_range(self, target_date: date) -> Tuple[datetime, datetime]:
        """Get start and end datetime for a given date."""
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date, datetime.max.time().replace(microsecond=0))
        return start, end

    # ── Excel Archive ─────────────────────────────────────────────────────

    def _save_to_excel(self, data: List[Dict[str, Any]], file_path: Path) -> bool:
        """Save fill data to Excel file (preserving original column names)."""
        try:
            df = pd.DataFrame(data)

            for col in EXPECTED_FILL_COLUMNS:
                if col not in df.columns:
                    df[col] = None
                    logger.debug(f"Added missing expected column: {col}")

            extra_cols = set(df.columns) - set(EXPECTED_FILL_COLUMNS)
            if extra_cols:
                logger.info(f"Extra columns from API (not in expected list): {extra_cols}")

            logger.info(f"Excel output: {len(df)} rows x {len(df.columns)} columns")

            df.to_excel(file_path, index=False, engine='openpyxl')
            logger.info(f"Saved {len(data)} records to {file_path}")
            return True
        except PermissionError as e:
            logger.error(f"Permission denied writing to {file_path}: {e}")
            return False
        except IOError as e:
            logger.error(f"I/O error writing Excel to {file_path}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to save Excel: {e}")
            return False

    # ── Core Fetch Methods ────────────────────────────────────────────────

    def fetch_day(self, target_date: date, team: Optional[str] = None,
                  skip_duplicates: bool = True, force: bool = False,
                  archive_excel: bool = False) -> Dict[str, Any]:
        """Fetch fills for a specific day and upsert to raw_fills.db.

        Steps:
            1. BloombergFillFetcher.fetch_fills() -> List[Dict]
            2. compute_data_hash()
            3. check_duplicate via in-memory index + DB fallback
            4. upsert_raw_api_data() -> raw_fills.db
            5. record in fetch_log
            6. [optional] _save_to_excel() as archive

        Args:
            target_date: The date to fetch fills for
            team: Team name to scope fills
            skip_duplicates: Skip if duplicate hash found in fetch_log
            force: Force re-fetch (bypass dedup)
            archive_excel: Also save Excel file as backup
        """
        if force:
            skip_duplicates = False

        order_date = target_date.strftime('%Y-%m-%d')
        date_compact = target_date.strftime('%Y%m%d')
        scope_desc = f"Team '{team}'" if team else "TradingSystem (login-based)"
        logger.info(f"Fetching fills for {order_date} ({scope_desc})")

        result: Dict[str, Any] = {
            'order_date': order_date,
            'team': team,
            'success': False,
            'skipped': False,
            'rows_fetched': 0,
            'hash_value': None,
            'rows_upserted': 0,
            'file_path': None,
            'error': None,
        }

        try:
            # Step 1: Fetch from Bloomberg
            from_dt, to_dt = self._get_date_range(target_date)
            with BloombergFillFetcher() as client:
                fills = client.fetch_fills(from_dt, to_dt, team=team)

            if not fills:
                logger.info(f"No fills found for {order_date}")
                result['success'] = True
                result['message'] = "No fills found"
                return result

            # Step 2: Hash
            hash_value = compute_data_hash(fills)
            result['hash_value'] = hash_value
            result['rows_fetched'] = len(fills)
            logger.info(f"Fetched {len(fills)} fills, hash={hash_value[:16]}...")

            # Step 3: Dedup check via in-memory hash index with DB fallback
            if skip_duplicates:
                # O(1) memory check first
                if self._is_duplicate_in_memory(date_compact, hash_value):
                    logger.info(f"Duplicate data found for {order_date} (memory), skipping")
                    result['skipped'] = True
                    result['success'] = True
                    result['message'] = f"Duplicate (hash={hash_value[:16]}...)"
                    return result
                # Fallback to DB check for safety
                if self.raw_db is not None:
                    if self.raw_db.check_fetch_duplicate(date_compact, hash_value):
                        logger.info(f"Duplicate data found for {order_date} (DB), skipping")
                        self._record_hash_in_memory(date_compact, hash_value)
                        result['skipped'] = True
                        result['success'] = True
                        result['message'] = f"Duplicate (hash={hash_value[:16]}...)"
                        return result

            # Step 3.5: Validate fill data integrity (SUM(FillShares)==Amount per OrderId)
            try:
                from .validate_raw_fills import validate_fill_data, save_anomaly_report
                val_result = validate_fill_data(fills, source_date=date_compact)
                result['validation'] = {
                    'success': val_result.success,
                    'total_orders': val_result.total_orders,
                    'failed_orders': val_result.failed_orders,
                    'pass_rate': f"{val_result.pass_rate:.2%}",
                }
                if not val_result.success and not val_result.anomalies_df.empty:
                    logger.warning(
                        f"Validation FAILED for {order_date}: "
                        f"{val_result.failed_orders}/{val_result.total_orders} orders have "
                        f"SUM(FillShares) != Amount"
                    )
                    report_path = save_anomaly_report(val_result)
                    if report_path:
                        logger.warning(f"Anomaly report saved: {report_path}")
                        result['anomaly_report'] = str(report_path)
            except Exception as val_err:
                logger.warning(f"Fill-share validation skipped (error): {val_err}")
                result['validation'] = {'error': str(val_err)}

            # Step 4: Upsert to raw_fills.db
            rows_upserted = 0
            if self.raw_db is not None:
                rows_upserted = self.raw_db.upsert_raw_api_data(fills, source_date=date_compact)
            result['rows_upserted'] = rows_upserted

            # Step 5: Record in fetch_log + order_fetch_log + update memory index
            if self.raw_db is not None:
                self.raw_db.add_fetch_log_record(
                    source_date=date_compact,
                    row_count=len(fills),
                    data_hash=hash_value,
                )
                self.raw_db.upsert_order_fetch_log(fills, source_date=date_compact)
                self._record_hash_in_memory(date_compact, hash_value)

            # Step 6: Optional Excel archive
            if archive_excel:
                file_name = f"fills_{date_compact}.xlsx"
                if team:
                    file_name = f"fills_{date_compact}_{team}.xlsx"
                file_path = self.data_dir / file_name
                if self._save_to_excel(fills, file_path):
                    result['file_path'] = str(file_path)

            # Step 7: Legacy DB sync (optional, backward compat)
            if self.db is not None:
                try:
                    fetch_time = f"{from_dt.strftime('%H:%M:%S')}-{to_dt.strftime('%H:%M:%S')}"
                    self.db.add_fetch_record(
                        order_date=order_date,
                        fetch_time=fetch_time,
                        row_count=len(fills),
                        hash_value=hash_value,
                        file_path=result.get('file_path'),
                    )
                except Exception:
                    pass

            result['success'] = True
            result['message'] = (
                f"Fetched {len(fills)} fills, upserted {rows_upserted} to raw_fills.db"
            )
            logger.info(f"Fetch completed for {order_date}: {result['message']}")

        except Exception as e:
            logger.error(f"Error fetching fills for {order_date}: {e}")
            result['error'] = str(e)

        return result

    def fetch_range(self, start_date: date, end_date: date,
                    team: Optional[str] = None,
                    force: bool = False,
                    archive_excel: bool = False) -> List[Dict[str, Any]]:
        """Fetch fills for a date range (inclusive).

        Opens one Bloomberg session reused across all days.
        """
        results = []
        current = start_date

        while current <= end_date:
            result = self.fetch_day(
                current, team=team, force=force, archive_excel=archive_excel,
            )
            results.append(result)
            current += timedelta(days=1)

        return results

    def fetch_range_aggregated(self, start_date: date, end_date: date,
                               team: Optional[str] = None,
                               skip_duplicates: bool = True,
                               force: bool = False,
                               archive_excel: bool = False) -> Dict[str, Any]:
        """Fetch fills for a date range using a single Bloomberg session.

        Uses in-memory dedup (O(1)) before DB queries and reuses one Bloomberg
        connection for all dates in the range.

        Args:
            start_date: First day to fetch.
            end_date: Last day to fetch.
            team: Optional team scope. None = TradingSystem (login-based).
            skip_duplicates: If True, skip days whose data hash matches existing records.
            force: When True, ignore all dedup checks and refetch everything.
            archive_excel: If True, also save daily Excel files.

        Returns:
            Dict with keys: start_date, end_date, scope, total_days, days_fetched,
            days_skipped, days_empty, days_error, total_rows, files, success.
        """
        if force:
            skip_duplicates = False
        start_str = start_date.strftime('%Y%m%d')
        end_str = end_date.strftime('%Y%m%d')
        scope_desc = f"team={team}" if team else "TradingSystem (login-based)"

        logger.info(f"Starting aggregated fetch: {start_date} to {end_date} ({scope_desc})")

        all_records: List[Dict[str, Any]] = []
        day_summaries: List[Dict[str, Any]] = []
        saved_files: List[str] = []
        total_days = (end_date - start_date).days + 1
        skipped_days = 0
        no_fill_days = 0
        error_days = 0

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
                logger.info(f"[{day_idx}/{total_days}] Processing {order_date}...")

                try:
                    from_dt, to_dt = self._get_date_range(current)
                    fills = client.fetch_fills(from_dt, to_dt, team=team)

                    if not fills:
                        logger.info(f"  No fills for {order_date}")
                        day_summaries.append({
                            'order_date': order_date, 'rows': 0, 'status': 'empty',
                        })
                        no_fill_days += 1
                        current += timedelta(days=1)
                        continue

                    hash_value = compute_data_hash(fills)

                    # In-memory dedup first (O(1)), then DB fallback
                    if skip_duplicates:
                        if self._is_duplicate_in_memory(date_compact, hash_value):
                            logger.info(f"  Duplicate found for {order_date} (memory), skipping")
                            day_summaries.append({
                                'order_date': order_date,
                                'rows': len(fills),
                                'status': 'skipped',
                            })
                            skipped_days += 1
                            current += timedelta(days=1)
                            continue
                        if self.raw_db is not None:
                            if self.raw_db.check_fetch_duplicate(date_compact, hash_value):
                                logger.info(f"  Duplicate found for {order_date} (DB), skipping")
                                self._record_hash_in_memory(date_compact, hash_value)
                                day_summaries.append({
                                    'order_date': order_date,
                                    'rows': len(fills),
                                    'status': 'skipped',
                                })
                                skipped_days += 1
                                current += timedelta(days=1)
                                continue

                    all_records.extend(fills)

                    # Validate fill data integrity before upsert
                    try:
                        from .validate_raw_fills import validate_fill_data, save_anomaly_report
                        val_result = validate_fill_data(fills, source_date=date_compact)
                        if not val_result.success and not val_result.anomalies_df.empty:
                            logger.warning(
                                f"Validation FAILED for {order_date}: "
                                f"{val_result.failed_orders}/{val_result.total_orders} orders "
                                f"have SUM(FillShares) != Amount"
                            )
                            report_path = save_anomaly_report(val_result)
                            if report_path:
                                logger.warning(f"Anomaly report saved: {report_path}")
                    except Exception as val_err:
                        logger.warning(f"Fill-share validation skipped (error): {val_err}")

                    # Upsert to raw_fills.db
                    rows_upserted = 0
                    if self.raw_db is not None:
                        rows_upserted = self.raw_db.upsert_raw_api_data(
                            fills, source_date=date_compact,
                        )
                        self.raw_db.add_fetch_log_record(
                            source_date=date_compact,
                            row_count=len(fills),
                            data_hash=hash_value,
                        )
                        self.raw_db.upsert_order_fetch_log(fills, source_date=date_compact)
                        self._record_hash_in_memory(date_compact, hash_value)

                    # Optional Excel archive
                    if archive_excel:
                        day_file_name = f"fills_{date_compact}.xlsx"
                        if team:
                            day_file_name = f"fills_{date_compact}_{team}.xlsx"
                        day_file_path = self.data_dir / day_file_name

                        if self._save_to_excel(fills, day_file_path):
                            saved_files.append(str(day_file_path))

                    day_summaries.append({
                        'order_date': order_date,
                        'rows': len(fills),
                        'rows_upserted': rows_upserted,
                        'status': 'fetched',
                    })
                    logger.info(f"  Fetched {len(fills)} fills for {order_date} "
                                f"(upserted {rows_upserted})")

                    # Legacy DB sync
                    if self.db is not None:
                        try:
                            fetch_time = f"{from_dt.strftime('%H:%M:%S')}-{to_dt.strftime('%H:%M:%S')}"
                            self.db.add_fetch_record(
                                order_date=order_date,
                                fetch_time=fetch_time,
                                row_count=len(fills),
                                hash_value=hash_value,
                                file_path=saved_files[-1] if saved_files else None,
                            )
                        except Exception:
                            pass

                except Exception as e:
                    logger.error(f"  Error fetching {order_date}: {e}")
                    day_summaries.append({
                        'order_date': order_date, 'rows': 0,
                        'status': 'error', 'error': str(e),
                    })
                    error_days += 1

                current += timedelta(days=1)

        summary = {
            'start_date': start_str,
            'end_date': end_str,
            'scope': scope_desc,
            'total_days': total_days,
            'days_fetched': len([s for s in day_summaries if s['status'] == 'fetched']),
            'days_skipped': skipped_days,
            'days_empty': no_fill_days,
            'days_error': error_days,
            'total_rows': len(all_records),
            'files': saved_files,
            'success': error_days == 0,
        }

        logger.info(
            f"Range fetch complete: {summary['total_rows']} rows across "
            f"{summary['days_fetched']} days, {skipped_days} skipped, "
            f"{error_days} errors"
        )

        return summary

    # ── History & Stats ───────────────────────────────────────────────────

    def get_history(self, order_date: Optional[str] = None,
                    limit: int = 100) -> List[Dict[str, Any]]:
        """Get fetch history from raw_fills.db fetch_log (primary) or legacy DB."""
        if self.raw_db is not None:
            try:
                stats = self.raw_db.get_fetch_log_stats()
                if order_date:
                    stats = [s for s in stats if s.get('source_date') == order_date.replace('-', '')]
                return stats[:limit]
            except Exception:
                pass

        # Fallback to legacy DB
        if self.db is not None:
            records = self.db.get_fetch_history(order_date, limit)
            return [{
                'order_date': r.order_date,
                'fetch_time': r.fetch_time,
                'import_timestamp': r.import_timestamp.isoformat(),
                'row_count': r.row_count,
                'hash_value': r.hash_value,
                'file_path': r.file_path,
            } for r in records]

        return []

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics from raw_fills.db + legacy DB."""
        stats: Dict[str, Any] = {}

        if self.raw_db is not None:
            try:
                stats['raw_fills_rows'] = self.raw_db.get_row_count()
                stats['raw_fills_dates'] = self.raw_db.get_date_row_counts()
            except Exception:
                pass

        if self.db is not None:
            try:
                legacy_stats = self.db.get_stats()
                stats['legacy'] = legacy_stats
            except Exception:
                pass

        return stats

    def close(self):
        """Close database connections."""
        if self.db is not None:
            self.db.close()


def setup_logging(level: str = "INFO"):
    """Configure logging (idempotent -- avoids duplicate handlers)."""
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='FillFetch - EMSX Fill Data Fetcher')

    parser.add_argument('--date', type=str, help='Date to fetch (YYYY-MM-DD)')
    parser.add_argument('--start-date', type=str, help='Start date for range (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date for range (YYYY-MM-DD)')
    parser.add_argument('--team', type=str, default=None,
                        help='Team name to scope fills')
    parser.add_argument('--force', action='store_true',
                        help='Force re-fetch: bypass dedup, overwrite data')
    parser.add_argument('--aggregate', action='store_true',
                        help='Aggregate range fetch (single Bloomberg session)')
    parser.add_argument('--data-dir', type=str, help='Data directory')
    parser.add_argument('--db-path', type=str, help='Legacy database path')
    parser.add_argument('--history', action='store_true', help='Show fetch history')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    parser.add_argument('--get-teams', action='store_true', help='List EMSX teams')
    parser.add_argument('--get-trade-desks', action='store_true', help='List EMSX trade desks')
    parser.add_argument('--log-level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])

    parser.add_argument('--auto', action='store_true',
                        help='Auto mode: determine range (first/incremental) and fetch')
    parser.add_argument('--archive-excel', action='store_true',
                        help='Also save Excel files as backup archive')

    args = parser.parse_args()

    setup_logging(args.log_level)

    # Handle discovery commands
    if args.get_teams or args.get_trade_desks:
        try:
            from src.emsx_client import EMSXHistoryClient
        except ImportError:
            from .emsx_client import EMSXHistoryClient
        with EMSXHistoryClient() as client:
            if args.get_trade_desks:
                desks = client.get_trade_desks()
                print("\n=== EMSX Trade Desks ===")
                for d in desks:
                    print(f"  {d}")
            if args.get_teams:
                teams = client.get_teams()
                print("\n=== EMSX Teams ===")
                for t in teams:
                    print(f"  {t}")
        return

    fetcher = FillFetch(data_dir=args.data_dir, db_path=args.db_path)

    try:
        # --auto mode: determine range and fetch
        if args.auto:
            fetch_range = fetcher.determine_fetch_range()
            if fetch_range is None:
                print("Already up-to-date. Nothing to fetch.")
                return
            start, end = fetch_range
            print(f"Auto mode: fetching {start} -> {end}")

            summary = fetcher.fetch_range_aggregated(
                start, end, team=args.team, force=args.force,
                archive_excel=args.archive_excel,
            )
            print(f"\n=== Auto Fetch Summary ===")
            for key, value in summary.items():
                if key != 'files':
                    print(f"  {key}: {value}")
            if summary.get('files'):
                print("\n  Files saved:")
                for f in summary['files']:
                    print(f"    {f}")
            return

        if args.stats:
            stats = fetcher.get_stats()
            print("\n=== FillFetch Statistics ===")
            for key, value in stats.items():
                print(f"  {key}: {value}")

        elif args.history:
            history = fetcher.get_history()
            print("\n=== Fetch History ===")
            for record in history[:20]:
                date_key = record.get('source_date', record.get('order_date', '?'))
                rows = record.get('row_count', 0)
                ts = record.get('fetch_timestamp', record.get('import_timestamp', '?'))
                print(f"  {date_key}: {rows} rows ({ts})")

        elif args.date:
            target = datetime.strptime(args.date, '%Y-%m-%d').date()
            result = fetcher.fetch_day(
                target, team=args.team, force=args.force,
                archive_excel=args.archive_excel,
            )
            print(f"\nResult: {result.get('message', result.get('error', '?'))}")
            if result.get('file_path'):
                print(f"File: {result['file_path']}")
            if result.get('rows_upserted'):
                print(f"Upserted: {result['rows_upserted']} rows")

        elif args.start_date and args.end_date:
            start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
            end = datetime.strptime(args.end_date, '%Y-%m-%d').date()

            if args.aggregate:
                summary = fetcher.fetch_range_aggregated(
                    start, end, team=args.team, force=args.force,
                    archive_excel=args.archive_excel,
                )
                print(f"\n=== Range Fetch Summary ===")
                for key, value in summary.items():
                    if key != 'files':
                        print(f"  {key}: {value}")
                if summary.get('files'):
                    print("\n  Files saved:")
                    for f in summary['files']:
                        print(f"    {f}")
            else:
                results = fetcher.fetch_range(
                    start, end, team=args.team, force=args.force,
                    archive_excel=args.archive_excel,
                )
                print(f"\nFetched {len(results)} days:")
                for r in results:
                    status = "OK" if r['success'] else "FAIL"
                    skip = " (skipped)" if r.get('skipped') else ""
                    print(f"  {status} {r['order_date']}: "
                          f"{r.get('message', r.get('error'))}{skip}")

        else:
            parser.print_help()

    finally:
        fetcher.close()


if __name__ == '__main__':
    main()

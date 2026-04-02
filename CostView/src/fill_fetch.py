"""
FillFetch Module - Main Entry Point

Automatically retrieves fill records on a per-day basis according to a defined schema:
1. Fetches fill data via Bloomberg EMSX History API (blpapi, TradingSystem scope)
2. Maintains a SQL table to track fetch history
3. Uses hash values to prevent duplicate local saves

Data fetching logic is based on the EMSX History blpapi pattern from
explore_fill_history.ipynb, with retry, timeout, and session-reuse optimizations.
"""

import os
import sys
import logging
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import blpapi
import pandas as pd
from dotenv import load_dotenv

try:
    from src.database import FillFetchDatabase, compute_data_hash
except ImportError:
    from .database import FillFetchDatabase, compute_data_hash

load_dotenv()

logger = logging.getLogger(__name__)


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

# Fill field → blpapi getter, matching notebook's explicit extraction order
FILL_FIELD_EXTRACTORS: Dict[str, str] = {
    # ── Active fields ─────────────────────────────────────────────────────────
    "OrderId":                   "getValueAsInteger",
    "Account":                   "getValueAsString",
    "SecurityName":              "getValueAsString",
    "Ticker":                    "getValueAsString",
    "Exchange":                  "getValueAsString",
    "Currency":                  "getValueAsString",
    "Side":                      "getValueAsString",
    "Amount":                    "getValueAsFloat",
    "NyOrderCreateAsOfDateTime": "getValueAsString",
    "OrderInstruction":          "getValueAsString",
    "IsLeg":                     "getValueAsBool",
    "Type":                      "getValueAsString",
    "LimitPrice":                "getValueAsFloat",
    "Broker":                    "getValueAsString",
    "StopPrice":                 "getValueAsFloat",
    "StrategyType":              "getValueAsString",
    "TraderName":                "getValueAsString",
    "TraderUuid":                "getValueAsInteger",
    "RouteId":                   "getValueAsInteger",
    "NyTranCreateAsOfDateTime":  "getValueAsString",
    "RouteShares":               "getValueAsFloat",
    "RouteExecutionInstruction": "getValueAsString",
    "RouteHandlingInstruction":  "getValueAsString",
    "RouteNotes":                "getValueAsString",
    "FillId":                    "getValueAsInteger",
    "ExecType":                  "getValueAsString",
    "DateTimeOfFill":            "getValueAsString",
    "FillPrice":                 "getValueAsFloat",
    "FillShares":                "getValueAsFloat",
    "LastCapacity":              "getValueAsString",
    "LastMarket":                "getValueAsString",
    "Liquidity":                 "getValueAsString",
    "LocalExchangeSymbol":       "getValueAsString",

    # ── Commented fields ──────────────────────────────────────────────────────
    # "AssetClass":                "getValueAsString",
    # "BasketId":                  "getValueAsInteger",
    # "BasketName":                "getValueAsString",
    # "BBGID":                     "getValueAsString",
    # "BlockId":                   "getValueAsString",
    # "ClearingAccount":           "getValueAsString",
    # "ClearingFirm":              "getValueAsString",
    # "ContractExpDate":           "getValueAsString",
    # "CorrectedFillId":           "getValueAsInteger",
    # "Cusip":                     "getValueAsString",
    # "ExecPrevSeqNo":             "getValueAsInteger",
    # "ExecutingBroker":           "getValueAsString",
    # "InvestorID":                "getValueAsString",
    # "IsCfd":                     "getValueAsBool",
    # "Isin":                      "getValueAsString",
    # "LocateBroker":              "getValueAsString",
    # "LocateId":                  "getValueAsString",
    # "LocateRequired":            "getValueAsBool",
    # "MultilegId":                "getValueAsString",
    # "OCCSymbol":                 "getValueAsString",
    # "OrderExecutionInstruction": "getValueAsString",
    # "OrderHandlingInstruction":  "getValueAsString",
    # "OrderOrigin":               "getValueAsString",
    # "OrderReferenceId":          "getValueAsString",
    # "OriginatingTraderUuid":     "getValueAsInteger",
    # "ReroutedBroker":            "getValueAsString",
    # "RouteCommissionAmount":     "getValueAsFloat",
    # "RouteCommissionRate":       "getValueAsFloat",
    # "RouteNetMoney":             "getValueAsFloat",
    # "Sedol":                     "getValueAsString",
    # "SettlementDate":            "getValueAsString",
    # "TIF":                       "getValueAsString",
    # "UserCommissionAmount":      "getValueAsFloat",
    # "UserCommissionRate":        "getValueAsFloat",
    # "UserFees":                  "getValueAsFloat",
    # "UserNetMoney":              "getValueAsFloat",
    # "YellowKey":                 "getValueAsString",
}

EXPECTED_FILL_COLUMNS: List[str] = list(FILL_FIELD_EXTRACTORS.keys())


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
    a synchronous wrapper.  Supports session reuse across multiple fetch_fills()
    calls and configurable retry with exponential back-off.
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

        # Date range – matching notebook ISO-8601 format
        from_str = from_date.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')
        to_str = to_date.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')
        request.set("FromDateTime", from_str)
        request.set("ToDateTime", to_str)

        # Scope – TradingSystem default, Team as override (notebook pattern)
        scope = request.getElement("Scope")
        if team:
            scope.setChoice("Team")
            scope.setElement("Team", team)
            logger.info(f"Requesting fills from {from_str} to {to_str} for Team '{team}'")
        else:
            scope.setChoice("TradingSystem")
            scope.setElement("TradingSystem", True)
            logger.info(f"Requesting fills from {from_str} to {to_str} for TradingSystem (login-based)")

        logger.debug(f"Request: {request.toString()}")

        self._session.sendRequest(request)

        # Consume events until RESPONSE (matching notebook processResponseEvent)
        fills: List[Dict[str, Any]] = []
        done = False
        all_parse_errors: List[str] = []
        max_event_iterations = 500  # safety cap to prevent infinite loop
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

        # Log parse error summary once (not per-fill)
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
        """
        Extract fields using the type-specific getters from
        explore_fill_history.ipynb (e.g. getValueAsString, getValueAsFloat).

        Returns:
            Tuple of (record_dict_or_None, list_of_failed_field_names)
        """
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

    Procedure:
        1. Given a date_time and optional Team, fetch fill data (TradingSystem scope by default)
        2. Compute the hash value of the fetched fill data table
        3. Check for an existing entry in the SQL table with same order_date and hash
           - If match found, skip remaining steps
        4. Save the fill data as an Excel file (preserving original EMSX column names)
        5. Update the SQL table with the new fetch record
    """

    def __init__(self, data_dir: Optional[str] = None, db_path: Optional[str] = None):
        """
        Initialize FillFetch.

        Args:
            data_dir: Directory to save Excel files
            db_path: Path to SQLite database
        """
        self.data_dir = Path(data_dir or os.getenv('FILLFETCH_DATA_DIR', './data/fills'))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.db: Optional[FillFetchDatabase] = None
        try:
            self.db = FillFetchDatabase(db_path)
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

        logger.info(f"FillFetch initialized: data_dir={self.data_dir}")

    def _get_date_range(self, target_date: date) -> Tuple[datetime, datetime]:
        """Get start and end datetime for a given date."""
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date, datetime.max.time().replace(microsecond=0))
        return start, end

    def _save_to_excel(self, data: List[Dict[str, Any]], file_path: Path) -> bool:
        """Save fill data to Excel file (preserving original column names).
        
        Ensures all expected columns are present in the output.
        """
        try:
            df = pd.DataFrame(data)
            
            # Ensure all expected columns exist in the DataFrame
            for col in EXPECTED_FILL_COLUMNS:
                if col not in df.columns:
                    df[col] = None
                    logger.debug(f"Added missing expected column: {col}")
            
            # Log column diagnostics
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

    def fetch_day(self, target_date: date, team: Optional[str] = None,
                  skip_duplicates: bool = True, force: bool = False) -> Dict[str, Any]:
        """
        Fetch fills for a specific day.

        Uses TradingSystem scope by default (fills for the logged-in AIM Px#).

        Args:
            target_date: The date to fetch fills for
            team: Team name to scope fills (alternative to TradingSystem scope)
            skip_duplicates: If True, skip if duplicate hash found
            force: If True, delete existing DB records and overwrite Excel

        Returns:
            Result dictionary with status and details
        """
        if force:
            skip_duplicates = False
        order_date = target_date.strftime('%Y-%m-%d')
        scope_desc = f"Team '{team}'" if team else "TradingSystem (login-based)"
        logger.info(f"Fetching fills for {order_date} ({scope_desc})")

        result = {
            'order_date': order_date,
            'team': team,
            'success': False,
            'skipped': False,
            'rows_fetched': 0,
            'hash_value': None,
            'file_path': None,
            'error': None
        }

        try:
            # Step 1: Fetch fill data
            from_dt, to_dt = self._get_date_range(target_date)

            with BloombergFillFetcher() as client:
                fills = client.fetch_fills(from_dt, to_dt, team=team)

            if not fills:
                logger.info(f"No fills found for {order_date}")
                result['success'] = True
                result['message'] = "No fills found"
                return result

            # Step 2: Compute hash value
            # fills is already List[Dict] with original EMSX column names
            hash_value = compute_data_hash(fills)
            result['hash_value'] = hash_value
            result['rows_fetched'] = len(fills)

            logger.info(f"Fetched {len(fills)} fills, hash={hash_value[:16]}...")

            # Step 3: Check for duplicate (force bypasses this)
            if skip_duplicates and self.db.check_duplicate(order_date, hash_value):
                logger.info(f"Duplicate data found for {order_date}, skipping save")
                result['skipped'] = True
                result['success'] = True
                result['message'] = "Duplicate data - skipped"
                return result

            # Step 3b: Force mode – remove old DB records to avoid unique constraint
            if force:
                deleted = self.db.delete_records_for_date(order_date)
                if deleted:
                    logger.info(f"Force mode: cleared {deleted} old record(s) for {order_date}")

            # Step 4: Save to Excel
            file_name = f"fills_{order_date.replace('-', '')}.xlsx"
            file_path = self.data_dir / file_name

            if not self._save_to_excel(fills, file_path):
                result['error'] = "Failed to save Excel file"
                return result

            result['file_path'] = str(file_path)

            # Step 5: Update SQL table
            fetch_time = f"{from_dt.strftime('%H:%M:%S')}-{to_dt.strftime('%H:%M:%S')}"
            self.db.add_fetch_record(
                order_date=order_date,
                fetch_time=fetch_time,
                row_count=len(fills),
                hash_value=hash_value,
                file_path=str(file_path)
            )

            result['success'] = True
            result['message'] = f"Successfully saved {len(fills)} fills"
            logger.info(f"Fetch completed for {order_date}: {len(fills)} rows saved")

        except Exception as e:
            logger.error(f"Error fetching fills for {order_date}: {e}")
            result['error'] = str(e)

        return result

    def fetch_range(self, start_date: date, end_date: date,
                    team: Optional[str] = None,
                    force: bool = False) -> List[Dict[str, Any]]:
        """
        Fetch fills for a date range (inclusive).

        Args:
            start_date: Start date
            end_date: End date
            team: Team name to scope fills (alternative to TradingSystem scope)
            force: If True, delete existing DB records and overwrite Excel

        Returns:
            List of result dictionaries for each day
        """
        results = []
        current = start_date

        while current <= end_date:
            result = self.fetch_day(current, team=team, force=force)
            results.append(result)
            current += timedelta(days=1)

        return results

    def fetch_range_aggregated(self, start_date: date, end_date: date,
                               team: Optional[str] = None,
                               skip_duplicates: bool = True,
                               force: bool = False) -> Dict[str, Any]:
        """
        Fetch fills for a date range and save as daily Excel files.

        Uses a single Bloomberg session across all days for efficiency.
        Output file naming: fills_YYYYMMDD.xlsx

        Args:
            start_date: Start date
            end_date: End date
            team: Team name to scope fills (alternative to TradingSystem scope)
            skip_duplicates: Skip days that already exist in DB
            force: If True, delete existing DB records and overwrite Excel

        Returns:
            Summary dictionary with aggregated results
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

        # Use a single Bloomberg session for all days, but output one Excel per day
        with BloombergFillFetcher() as client:
            current = start_date
            day_idx = 0

            while current <= end_date:
                day_idx += 1
                order_date = current.strftime('%Y-%m-%d')
                date_compact = current.strftime('%Y%m%d')
                logger.info(f"[{day_idx}/{total_days}] Processing {order_date}...")

                try:
                    from_dt, to_dt = self._get_date_range(current)
                    fills = client.fetch_fills(from_dt, to_dt, team=team)

                    if not fills:
                        logger.info(f"  No fills for {order_date}")
                        day_summaries.append({'order_date': order_date, 'rows': 0, 'status': 'empty'})
                        no_fill_days += 1
                        current += timedelta(days=1)
                        continue

                    hash_value = compute_data_hash(fills)

                    if skip_duplicates and self.db.check_duplicate(order_date, hash_value):
                        logger.info(f"  Duplicate found for {order_date}, skipping")
                        day_summaries.append({'order_date': order_date, 'rows': len(fills), 'status': 'skipped'})
                        skipped_days += 1
                        current += timedelta(days=1)
                        continue

                    if force:
                        self.db.delete_records_for_date(order_date)

                    all_records.extend(fills)

                    # Save one Excel per day (via shared method to ensure all columns)
                    day_file_name = f"fills_{date_compact}.xlsx"
                    if team:
                        day_file_name = f"fills_{date_compact}_{team}.xlsx"
                    day_file_path = self.data_dir / day_file_name

                    if not self._save_to_excel(fills, day_file_path):
                        day_summaries.append({'order_date': order_date, 'rows': len(fills), 'status': 'error', 'error': 'Failed to save Excel'})
                        error_days += 1
                        current += timedelta(days=1)
                        continue

                    saved_files.append(str(day_file_path))

                    day_summaries.append({'order_date': order_date, 'rows': len(fills), 'status': 'fetched', 'file': str(day_file_path)})
                    logger.info(f"  Fetched {len(fills)} fills for {order_date} -> {day_file_name}")

                    # Record in DB per day
                    fetch_time = f"{from_dt.strftime('%H:%M:%S')}-{to_dt.strftime('%H:%M:%S')}"
                    self.db.add_fetch_record(
                        order_date=order_date,
                        fetch_time=fetch_time,
                        row_count=len(fills),
                        hash_value=hash_value,
                        file_path=str(day_file_path)
                    )

                except Exception as e:
                    logger.error(f"  Error fetching {order_date}: {e}")
                    day_summaries.append({'order_date': order_date, 'rows': 0, 'status': 'error', 'error': str(e)})
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
            'success': error_days == 0
        }

        logger.info(f"Range fetch complete: {summary['total_rows']} rows across "
                     f"{summary['days_fetched']} files, {skipped_days} skipped, "
                     f"{error_days} errors")

        return summary

    def get_history(self, order_date: Optional[str] = None,
                    limit: int = 100) -> List[Dict[str, Any]]:
        """Get fetch history from database."""
        records = self.db.get_fetch_history(order_date, limit)
        return [{
            'order_date': r.order_date,
            'fetch_time': r.fetch_time,
            'import_timestamp': r.import_timestamp.isoformat(),
            'row_count': r.row_count,
            'hash_value': r.hash_value,
            'file_path': r.file_path
        } for r in records]

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        return self.db.get_stats()

    def close(self):
        """Close database connection."""
        if self.db is not None:
            self.db.close()


def setup_logging(level: str = "INFO"):
    """Configure logging (idempotent – avoids duplicate handlers)."""
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
                        help='Team name to scope fills (alternative to default TradingSystem scope)')
    parser.add_argument('--force', action='store_true',
                        help='Force re-fetch: skip duplicate check, overwrite Excel, replace DB records')
    parser.add_argument('--aggregate', action='store_true',
                        help='Aggregate range fetch (single Bloomberg session, one Excel per day)')
    parser.add_argument('--data-dir', type=str, help='Data directory')
    parser.add_argument('--db-path', type=str, help='Database path')
    parser.add_argument('--history', action='store_true', help='Show fetch history')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    parser.add_argument('--get-teams', action='store_true', help='List available EMSX teams')
    parser.add_argument('--get-trade-desks', action='store_true', help='List available EMSX trade desks')
    parser.add_argument('--log-level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])

    args = parser.parse_args()

    setup_logging(args.log_level)

    # Handle discovery commands (uses EMSXHistoryClient for non-fill APIs)
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
        if args.stats:
            stats = fetcher.get_stats()
            print("\n=== FillFetch Statistics ===")
            for key, value in stats.items():
                print(f"  {key}: {value}")

        elif args.history:
            history = fetcher.get_history()
            print("\n=== Fetch History ===")
            for record in history[:20]:
                print(f"  {record['order_date']}: {record['row_count']} rows "
                      f"({record['import_timestamp']})")

        elif args.date:
            target = datetime.strptime(args.date, '%Y-%m-%d').date()
            result = fetcher.fetch_day(target, team=args.team, force=args.force)
            print(f"\nResult: {result['message']}")
            if result.get('file_path'):
                print(f"File: {result['file_path']}")

        elif args.start_date and args.end_date:
            start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
            end = datetime.strptime(args.end_date, '%Y-%m-%d').date()

            if args.aggregate:
                summary = fetcher.fetch_range_aggregated(
                    start, end, team=args.team, force=args.force)
                print(f"\n=== Range Fetch Summary ===")
                for key, value in summary.items():
                    if key != 'files':
                        print(f"  {key}: {value}")
                if summary['files']:
                    print("\n  Files saved:")
                    for f in summary['files']:
                        print(f"    {f}")
            else:
                results = fetcher.fetch_range(start, end, team=args.team, force=args.force)
                print(f"\nFetched {len(results)} days:")
                for r in results:
                    status = "OK" if r['success'] else "FAIL"
                    skip = " (skipped)" if r.get('skipped') else ""
                    print(f"  {status} {r['order_date']}: {r.get('message', r.get('error'))}{skip}")

        else:
            parser.print_help()

    finally:
        fetcher.close()


if __name__ == '__main__':
    main()

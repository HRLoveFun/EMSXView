"""
Step 2: Import Excel fill data into raw_fills.db with HK-to-NY timezone conversion.

Mapping rules (confirmed by user 2026-04-06):
    [A] Direct copy (12 columns):
        OrderId <- Order Number, Account <- Tran Account,
        SecurityName <- Security Name, Ticker <- Ticker,
        Exchange <- Exchange, Currency <- Currency,
        Side <- Side, Amount <- Amount, Type <- Order Type,
        StrategyType <- Strategy Type, TraderName <- Trader Name,
        Liquidity <- Liquidity, ExecType <- Exec Type

    [B] Dual-column (broker field varies by file):
        Broker <- Broker, LastMarket <- Last Market

    [C] Price/Quantity (3):
        FillPrice <- Exec Last Fill Px, FillShares <- Exec Last Fill,
        RouteShares <- Routed Amount

    [D] Safe date (1, no TZ issue):
        order_as_of_date <- Order As of Date

    [E] HK -> NY conversion (with DST: winter -5, summer -4):
        All Excel times are Hong Kong (UTC+8).
        Must convert to New York time before storing, because:
          - DB stores DateTimeOfFill in NY timezone (Bloomberg API native format)
          - fill_cleaner.py derive_exchange_times() assumes NY input
          - Conversion uses zoneinfo for automatic DST handling

        DateTimeOfFill         <- Exec Date + Exchange Exec Time (combined)
        NyOrderCreateAsOfDT     <- Order As of Date + Order As of Time (combined)
        NyTranCreateAsOfDT      <- Order As of Date + Route As of Time (combined)

    [F] DROPPED columns:
        - Order Entry Time (duplicate of Route As of Time)
        - Exec Time (no clear DB target; Exchange Exec Time covers exec)
        - Average Price, Day Avg Price, Exec Avg Price (aggregated values)
        - Tran Type (alias of Order Type)

    [G] Filled as NULL / synthetic:
        LimitPrice, StopPrice, TraderUuid, LastCapacity, LocalExchangeSymbol -> NULL
        FillId -> "X" + "Exec Seq Number" (synthetic with X-prefix)
        RouteId -> sequential number per OrderId sorted by Route As of Time

Special:
    - fills_20260302_20260306.xlsx: filtered to rows where
      "Order As of Date" in [2026-03-02, 2026-03-03, 2026-03-04]
    - PK: (OrderId, RouteId, FillId) — RouteId is generated per-order sequence

Usage:
    python scripts/import_excel_fills.py --dry-run       # Analysis only
    python scripts/import_excel_fills.py --execute        # Execute import
"""

import os
import sys
import logging
import argparse
from datetime import datetime, date, time as dt_time, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
import sqlite3
from zoneinfo import ZoneInfo

# ── Add CostView to path ───────────────────────────────────────────────
_COSTVIEW_ROOT = Path(__file__).resolve().parent.parent / "CostView"  # scripts/ -> EMSX/CostView/
if str(_COSTVIEW_ROOT) not in sys.path:
    sys.path.insert(0, str(_COSTVIEW_ROOT))

from src.schema import (
    EMSX_FILL_COLUMNS,
    DERIVED_COLUMNS,
    RAW_METADATA_COLUMNS,
    ALL_RAW_COLUMNS,
)
from DataPipeline.config import Config


logger = logging.getLogger(__name__)

# ── Timezone constants ────────────────────────────────────────────────
HK_TZ = ZoneInfo("Asia/Hong_Kong")       # Excel source: UTC+8, no DST
NY_TZ = ZoneInfo("America/New_York")     # DB target: UTC-5 (EST) / UTC-4 (EDT)


# ══════════════════════════════════════════════════════════════════════
# COLUMN MAPPING DEFINITIONS
# ══════════════════════════════════════════════════════════════════════

#: [A] Direct copy: Excel col name -> DB col name
DIRECT_MAP: List[Tuple[str, str]] = [
    ("Order Number",       "OrderId"),
    ("Tran Account",       "Account"),
    ("Security Name",      "SecurityName"),
    ("Ticker",            "Ticker"),
    ("Exchange",          "Exchange"),
    ("Currency",          "Currency"),
    ("Side",              "Side"),
    ("Amount",            "Amount"),
    ("Order Type",         "Type"),
    ("Strategy Type",      "StrategyType"),
    ("Trader Name",        "TraderName"),
    ("Liquidity",         "Liquidity"),
    ("Exec Type",          "ExecType"),
]

#: [B] Independent broker columns (both can coexist, confirmed from sample data)
#:   Some files have only Broker, some have both Broker + Last Market.
#:   Each maps to its own DB column; missing = None.
BROKER_INDEPENDENT_MAP: List[Tuple[str, str]] = [
    ("Broker",      "Broker"),
    ("Last Market", "LastMarket"),
]

#: [C] Price / quantity columns
PRICE_QTY_MAP: List[Tuple[str, str]] = [
    ("Exec Last Fill Px",  "FillPrice"),
    ("Exec Last Fill",    "FillShares"),
    ("Routed Amount",     "RouteShares"),
]

#: [D] Pure date field (safe, no timezone component)
DATE_ONLY_MAP: List[Tuple[str, str]] = [
    ("Order As of Date",  "order_as_of_date"),
]

#: [E] HK->NY timezone conversion
#   Exec Date is a full HK datetime (date+time combined), e.g. "2025-09-15 10:15:25"
#   Convert to NY timestamp for DB storage.
#   Exchange Exec Time = local exchange execution time (store as-is, no TZ conversion).
HK_TO_NY_TIME_MAP: List[Tuple[str, str]] = [
    # (Excel name,              DB column)
    ("Exec Date",              "DateTimeOfFill"),           # HK datetime -> NY ISO string
]

#: [E2] Direct local-time copy (no TZ conversion — already in local exchange time)
LOCAL_TIME_MAP: List[Tuple[str, str]] = [
    ("Exchange Exec Time",    "exchange_exec_time"),       # local exec time, store as-is
]

#: Columns to silently ignore
DROP_COLS: set = {
    "Order Entry Time",      # duplicate of Route As of Time (user confirmed)
    "Exec Time",              # no clear DB equivalent; Exchange Exec Time covers exec
    "Average Price",          # aggregated value, not raw
    "Day Avg Price",          # aggregated value
    "Exec Avg Price",         # aggregated value
    "Exec Prev Seq Number",   # internal sequence
    "Tran Type",              # alias of Order Type
}

DATA_DIR = Config.DATA_DIR / "archive_excel"
DB_PATH = Config.RAW_FILLS_DB

# Target date range for row filtering (inclusive)
TARGET_DATE_START = "2025-09-15"
TARGET_DATE_END   = "2026-03-04"


# ══════════════════════════════════════════════════════════════════════
# TIMEZONE CONVERSION
# ══════════════════════════════════════════════════════════════════════

def _parse_excel_date(date_val: Any) -> Optional[date]:
    """Parse various Excel date formats into a Python date object."""
    if date_val is None or (isinstance(date_val, float) and pd.isna(date_val)):
        return None
    s = str(date_val).strip()
    if not s:
        return None

    # Try common formats
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    # Try pandas
    try:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.notna(dt):
            return dt.date()
    except Exception:
        pass

    logger.warning(f"Cannot parse date: {date_val!r}")
    return None


def _parse_excel_time(time_val: Any) -> Optional[dt_time]:
    """Parse various Excel time formats into a Python time object."""
    if time_val is None or (isinstance(time_val, float) and pd.isna(time_val)):
        return None
    s = str(time_val).strip()
    if not s:
        return None

    for fmt in ("%H:%M:%S", "%H:%M", "%H.%M.%S", "%I:%M:%S %p"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue

    # Try pandas (may return datetime, extract time)
    try:
        t = pd.to_datetime(s, errors="coerce")
        if pd.notna(t):
            return t.time()
    except Exception:
        pass

    logger.warning(f"Cannot parse time: {time_val!r}")
    return None


def hk_to_ny_datetime(
    date_val: Any,
    time_val: Any,
    label: str = "",
) -> Optional[str]:
    """Combine Excel HK date + time into a NY-timestamp ISO string.

    Pipeline:  HK (UTC+8) naive datetime  -->  aware HK  -->  astimezone(NY)  -->  ISO string

    Uses zoneinfo for automatic DST resolution (EDT/EST).

    Args:
        date_val: Raw Excel date value (e.g. "2026-03-02" or "2026-03-02 11:08:46").
        time_val: Raw Excel time value (e.g. "11:08:46" or "10:08:46").
        label: Human-readable label for error messages.

    Returns:
        ISO-format string in America/New_York timezone, e.g.
        "2026-03-01T22:08:17.409-05:00" (EST) or
        "2026-03-09T20:58:20-04:00" (EDT).
        Returns None if either component is missing or unparseable.
    """
    d = _parse_excel_date(date_val)
    t = _parse_excel_time(time_val)

    if d is None:
        if label:
            logger.debug(f"[{label}] Missing date: {date_val!r}")
        return None
    # time is optional for pure-date fields
    if t is None:
        if label:
            logger.debug(f"[{label}] Missing time: {time_val!r}, using 00:00:00")
        t = dt_time(0, 0, 0)

    # Construct naive datetime in HK timezone, then localize and convert
    hk_naive = datetime.combine(d, t)
    hk_aware = hk_naive.replace(tzinfo=HK_TZ)
    ny_aware = hk_aware.astimezone(NY_TZ)

    return ny_aware.isoformat()


def _hk_datetime_to_ny(dt_val: Any, label: str = "") -> Optional[str]:
    """Convert an Excel Exec Date (already a full HK datetime) to NY ISO string.

    Excel Exec Date value examples:
        - pandas Timestamp: Timestamp('2025-09-15 10:15:25')
        - string:           "2026-02-23 11:32:53"

    Both represent Hong Kong local time (UTC+8, no DST).
    Converts to America/New_York with automatic EDT/EST resolution.
    """
    if dt_val is None or (isinstance(dt_val, float) and pd.isna(dt_val)):
        return None

    # Parse via pandas (handles both Timestamp and string)
    try:
        dt = pd.to_datetime(str(dt_val).strip(), errors="coerce")
        if pd.isna(dt):
            return None
        dt = dt.to_pydatetime()
    except Exception as e:
        logger.warning(f"[{label}] Cannot parse Exec Date: {dt_val!r} ({e})")
        return None

    # Localize as HK, convert to NY
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HK_TZ)
    ny_dt = dt.astimezone(NY_TZ)

    return ny_dt.isoformat()


# ══════════════════════════════════════════════════════════════════════
# ROW CONVERSION
# ══════════════════════════════════════════════════════════════════════

def convert_row(
    excel_row: Dict[str, Any],
    excel_cols: List[str],
    source_date: str,
    route_id: Optional[int] = None,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Convert one Excel row to a DB-ready dict per the confirmed mapping rules.

    Args:
        excel_row: Raw dict from pandas DataFrame row.
        excel_cols: List of Excel column names.
        source_date: YYYYMMDD source date string (from row's Order As of Date).
        route_id: If provided, used as synthetic RouteId (sequential per OrderId).

    Returns:
        (db_row_dict_or_None, list_of_warnings).
        Returns (None, warnings) if OrderId is missing.
    """
    warnings: List[str] = []

    # Initialize all DB columns to None
    db_row: Dict[str, Any] = {}
    for c in ALL_RAW_COLUMNS + RAW_METADATA_COLUMNS:
        db_row[c] = None

    def _get(key: str) -> Any:
        """Safely get value from Excel row, returning None for NaN/empty."""
        val = excel_row.get(key)
        if val is None:
            return None
        if isinstance(val, float) and pd.isna(val):
            return None
        s = str(val).strip()
        return s if s else None

    # ── [A] Direct copy ──
    for excel_col, db_col in DIRECT_MAP:
        v = _get(excel_col)
        if v is not None:
            db_row[db_col] = v

    # ── [B] Independent broker columns (both can coexist in same file) ──
    for excel_col, db_col in BROKER_INDEPENDENT_MAP:
        v = _get(excel_col)
        if v is not None:
            db_row[db_col] = v

    # ── [C] Price / Quantity ──
    for excel_col, db_col in PRICE_QTY_MAP:
        v = _get(excel_col)
        if v is not None:
            db_row[db_col] = v

    # ── [D] Safe date ──
    for excel_col, db_col in DATE_ONLY_MAP:
        v = _get(excel_col)
        if v is not None:
            db_row[db_col] = v

    # Validate required field
    order_id = db_row.get("OrderId")
    if not order_id:
        return None, ["Missing OrderId"]

    # ── [G1] Synthetic RouteId ──
    # For each OrderId, assign one RouteId per UNIQUE "Route As of Time" value,
    # sorted chronologically. Rows with the same (OrderId, Route As of Time) share
    # the same RouteId.
    if route_id is not None:
        db_row["RouteId"] = str(route_id)

    # ── [G2] Synthetic FillId (NOT NULL constraint) ──
    # Directly use Excel Exec Seq Number as FillId (no X-prefix).
    seq_num = _get("Exec Seq Number")
    if seq_num is not None:
        db_row["FillId"] = str(seq_num)
    else:
        db_row["FillId"] = "0"  # fallback

    # ── [E] HK->NY conversion ──
    # Exec Date is already a full HK datetime, e.g. "2025-09-15 10:15:25"
    exec_date_raw = _get("Exec Date")
    if exec_date_raw:
        ny_dt = _hk_datetime_to_ny(exec_date_raw,
                                    label=f"OrderId={order_id} DateTimeOfFill")
        if ny_dt:
            db_row["DateTimeOfFill"] = ny_dt
        else:
            warnings.append(
                f"OrderId={order_id}: Exec Date HK->NY failed ({exec_date_raw!r})")

    # NyOrderCreateAsOfDateTime: Order As of Date + Order As of Time
    oad = _get("Order As of Date")
    oat = _get("Order As of Time")
    if oad and oat:
        ny_dt = hk_to_ny_datetime(oad, oat, label=f"OrderId={order_id} NyOrderCreate")
        if ny_dt:
            db_row["NyOrderCreateAsOfDateTime"] = ny_dt

    # NyTranCreateAsOfDateTime: Order As of Date + Route As of Time
    rat = _get("Route As of Time")
    if oad and rat:
        ny_dt = hk_to_ny_datetime(oad, rat, label=f"OrderId={order_id} NyTranCreate")
        if ny_dt:
            db_row["NyTranCreateAsOfDateTime"] = ny_dt

    # ── [E2] Local time direct copy (no TZ conversion) ──
    for excel_col, db_col in LOCAL_TIME_MAP:
        v = _get(excel_col)
        if v is not None:
            db_row[db_col] = v

    # ── Metadata ──
    db_row["source_date"] = source_date
    db_row["fetched_at"] = datetime.now().isoformat()

    return db_row, warnings


# ══════════════════════════════════════════════════════════════════════
# ANALYSIS (DRY RUN)
# ══════════════════════════════════════════════════════════════════════

def analyze_files(data_dir: Path) -> Dict[str, Any]:
    """Dry-run: read all xlsx files and report mapping coverage."""
    results = {
        "files": [],
        "total_rows": 0,
        "warnings": [],
        "sample_rows": {},
    }

    files = sorted(f for f in os.listdir(data_dir) if f.endswith(".xlsx"))

    for fname in files:
        fpath = data_dir / fname
        try:
            df = pd.read_excel(fpath, engine="openpyxl")
            headers = list(df.columns)

            # Classify each Excel header
            mapped_db = set()
            unmapped_excel = []

            for h in headers:
                matched = False
                # Check all mapping categories
                for ec, dc in DIRECT_MAP + PRICE_QTY_MAP + DATE_ONLY_MAP:
                    if h == ec:
                        mapped_db.add(dc)
                        matched = True
                        break
                if not matched:
                    for ec, dc in BROKER_INDEPENDENT_MAP:
                        if h == ec:
                            mapped_db.add(dc)
                            matched = True
                            break
                if not matched:
                    for ec, dc in HK_TO_NY_TIME_MAP + LOCAL_TIME_MAP:
                        if h == ec:
                            mapped_db.add(dc)
                            matched = True
                            break
                if not matched:
                    if h in DROP_COLS:
                        pass  # known dropped
                    else:
                        unmapped_excel.append(h)

            unmapped_db = sorted(c for c in EMSX_FILL_COLUMNS if c not in mapped_db)

            results["files"].append({
                "file": fname,
                "rows": len(df),
                "headers": headers,
                "mapped_db_cols": sorted(mapped_db),
                "unmapped_excel": sorted(unmapped_excel),
                "unmapped_db_cols": unmapped_db,
            })
            results["total_rows"] += len(df)

            # Save first non-empty row as sample
            if len(results["sample_rows"]) < 3 and len(df) > 0:
                sample = df.iloc[0].to_dict()
                results["sample_rows"][fname] = {
                    k: v for k, v in sample.items()
                    if k != "Index" and v is not None
                    and not (isinstance(v, float) and pd.isna(v))
                }

        except Exception as e:
            results["warnings"].append(f"{fname}: {e}")

    return results


def print_analysis(result: Dict[str, Any]) -> None:
    """Pretty-print analysis results."""
    print(f"\n{'='*70}")
    print(f"MAPPING ANALYSIS SUMMARY")
    print(f"{'='*70}")
    print(f"Total files found : {len(result['files'])}")
    print(f"Total rows       : {result['total_rows']:,}")

    print(f"{'-'*70}")
    print(f"MAPPING RULES:")
    print(f"  [A] Direct copy     : {len(DIRECT_MAP)} columns")
    print(f"  [B] Broker+LM indep : {len(BROKER_INDEPENDENT_MAP)} columns")
    print(f"  [C] Price/Qty       : {len(PRICE_QTY_MAP)} columns")
    print(f"  [D] Safe date       : {len(DATE_ONLY_MAP)} columns")
    print(f"  [E] HK->NY convert  : {len(HK_TO_NY_TIME_MAP)} columns")
    print(f"  [E2] Local time     : {len(LOCAL_TIME_MAP)} columns")
    print(f"  [G] Dropped         : {len(DROP_COLS)} columns")

    print(f"{'-'*70}")
    print(f"PER-FILE DETAILS:")
    for fr in result["files"]:
        status = "OK"
        missing_critical = [c for c in ["OrderId"]
                            if c not in fr["mapped_db_cols"]]
        if missing_critical:
            status = "WARN"
        print(f"  [{status}] {fr['file']}")
        print(f"         Rows: {fr['rows']:,}  |  Mapped: {len(fr['mapped_db_cols'])} DB cols  |  "
              f"Unmapped Excel: {len(fr['unmapped_excel'])}  |  Missing DB: {len(fr['unmapped_db_cols'])}")
        if fr["unmapped_excel"]:
            print(f"         Unmapped Excel cols: {fr['unmapped_excel']}")

    if result["sample_rows"]:
        print(f"{'-'*70}")
        print(f"SAMPLE ROWS (first row of each file):")
        for fname, row in result["sample_rows"].items():
            print(f"\n  --- {fname} ---")
            for k, v in row.items():
                print(f"    {k}: {v}")

    if result["warnings"]:
        print(f"\nWarnings ({len(result['warnings'])}):")
        for w in result["warnings"][:10]:
            print(f"  ! {w}")


# ══════════════════════════════════════════════════════════════════════
# EXECUTE IMPORT
# ══════════════════════════════════════════════════════════════════════

def execute_import(
    data_dir: Path,
    db_path: Path,
    dry_run: bool = False,
    fail_fast: bool = False,
    warning_threshold: int = 100,
    single_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute the actual import of all Excel files into raw_fills.db.

    For multi-date Excel files (e.g., fills_20260302_20260306.xlsx), rows are
    filtered to only those where "Order As of Date" is in TARGET_IMPORT_DATES.
    RouteId is generated as a sequential integer per OrderId, ordered by
    "Route As of Time" then "Exec Seq Number".
    """

    # Single-file mode or all files
    if single_file:
        files = [single_file] if any(single_file == f for f in os.listdir(data_dir)) else []
    else:
        files = sorted(f for f in os.listdir(data_dir) if f.endswith(".xlsx"))

    total_imported = 0
    total_warnings = 0
    file_results = []
    errors = []
    stopped_early = False
    stop_reason = ""

    conn = sqlite3.connect(str(db_path))

    try:
        _ensure_schema(conn)

        insert_cols = ALL_RAW_COLUMNS + RAW_METADATA_COLUMNS
        placeholders = ", ".join(["?"] * len(insert_cols))
        col_names = ", ".join(f"[{c}]" for c in insert_cols)
        sql = f"INSERT OR REPLACE INTO raw_fills ({col_names}) VALUES ({placeholders})"

        for fname in files:
            if stopped_early:
                file_results.append({"file": fname, "rows": 0, "status": "skipped",
                                    "reason": stop_reason})
                continue

            fpath = data_dir / fname
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {fname}")

            source_date = _extract_source_date(fname)
            if not source_date:
                msg = f"{fname}: cannot extract source date"
                errors.append(msg)
                logger.error(f"  ERROR: {msg}")
                if fail_fast:
                    stopped_early = True; stop_reason = "fail-fast: no source_date"
                    continue

            try:
                df = pd.read_excel(fpath, engine="openpyxl")

                # ── Date filtering for multi-date Excel files (range: start ~ end inclusive) ──
                if "Order As of Date" in df.columns:
                    total_before = len(df)
                    df = df[
                        (df["Order As of Date"] >= TARGET_DATE_START) &
                        (df["Order As of Date"] <= TARGET_DATE_END)
                    ].copy()
                    filtered_out = total_before - len(df)
                    if filtered_out > 0:
                        logger.info(f"  Filtered to {len(df):,} rows "
                                    f"(excluded {filtered_out:,} rows outside "
                                    f"{TARGET_DATE_START} ~ {TARGET_DATE_END})")
                elif not df.empty:
                    logger.info(f"  No 'Order As of Date' column — using all {len(df):,} rows")

                if df.empty:
                    logger.info(f"  Empty after filtering, skipped")
                    file_results.append({"file": fname, "rows": 0, "status": "empty_filtered"})
                    continue

                # ── Generate RouteId: one ID per unique (OrderId, "Route As of Time") ──
                # For EACH OrderId independently:
                #   1. Get all unique "Route As of Time" values for that OrderId
                #   2. Sort them chronologically
                #   3. Assign RouteId = 1, 2, 3... in sorted order
                # Every OrderId's first route always gets RouteId=1.
                df["_sort_route_time"] = pd.to_datetime(
                    df["Route As of Time"], format="%H:%M:%S", errors="coerce"
                )
                # Unique (OrderId, RouteAsOfTime) groups with their earliest sort time
                route_lookup = (
                    df[["Order Number", "Route As of Time", "_sort_route_time"]]
                    .drop_duplicates(["Order Number", "Route As of Time"])
                    .copy()
                )
                route_lookup = route_lookup.sort_values(
                    ["Order Number", "_sort_route_time"]
                ).reset_index(drop=True)
                # Enumerate per OrderId group: each group starts at 1
                route_lookup["__gen_route_id"] = (
                    route_lookup.groupby("Order Number", sort=False).cumcount() + 1
                )
                # Build lookup: (OrderNumber_str, RAT_str) -> RouteId
                rid_map = dict(zip(
                    route_lookup["Order Number"].astype(str)
                    + "|" + route_lookup["Route As of Time"].astype(str),
                    route_lookup["__gen_route_id"],
                ))
                df["__gen_route_id"] = (
                    df["Order Number"].astype(str)
                    + "|" + df["Route As of Time"].astype(str)
                ).map(rid_map)

                # Clean up temp column
                df = df.drop(columns=["_sort_route_time"])

                max_rid = int(df["__gen_route_id"].max()) if len(df) > 0 else 0
                unique_routes_total = df["__gen_route_id"].nunique()
                unique_orders = df["Order Number"].nunique()
                logger.info(f"  RouteId generated: max={max_rid}, "
                            f"{unique_routes_total:,} unique routes across "
                            f"{unique_orders:,} orders, {len(df):,} rows")

                batch = []
                imported = 0
                file_warnings: List[str] = []
                skipped_no_orderid = 0

                for idx, row in df.iterrows():
                    excel_row = row.to_dict()
                    route_id = int(row["__gen_route_id"])
                    # Extract source_date from row's Order As of Date for accuracy
                    row_source_date = source_date
                    oad_val = excel_row.get("Order As of Date")
                    if oad_val and str(oad_val).strip():
                        try:
                            from datetime import datetime as dt
                            parsed = dt.strptime(str(oad_val).strip(), "%Y-%m-%d")
                            row_source_date = parsed.strftime("%Y%m%d")
                        except Exception:
                            pass

                    db_row, row_w = convert_row(
                        excel_row, list(df.columns), row_source_date,
                        route_id=route_id,
                    )
                    if db_row is None:
                        skipped_no_orderid += 1
                        continue
                    if row_w:
                        file_warnings.extend(row_w)
                        total_warnings += len(row_w)

                        # Fail-fast on warning threshold breach
                        if (fail_fast and len(file_warnings) > warning_threshold):
                            msg = f"{fname}: warning threshold exceeded ({len(file_warnings)} > {warning_threshold})"
                            errors.append(msg)
                            logger.error(f"  FAIL-FAST STOP: {msg}")
                            # Show sample warnings
                            for w in file_warnings[:10]:
                                logger.error(f"    sample: {w}")
                            stopped_early = True
                            stop_reason = f"fail-fast: warnings>{warning_threshold}"
                            break

                    tup = tuple(str(db_row[c]) if db_row.get(c) is not None else None
                               for c in insert_cols)
                    batch.append(tup)
                    imported += 1

                # DB write with isolation check
                if batch and not dry_run and not stopped_early:
                    try:
                        conn.executemany(sql, batch)
                        conn.commit()
                        logger.info(f"  Upserted {imported} rows "
                                    f"(source_date={source_date}, "
                                    f"skipped={skipped_no_orderid} no-OrderId)")
                    except Exception as db_err:
                        msg = f"{fname}: DB write failed - {db_err}"
                        errors.append(msg)
                        logger.error(f"  DB ERROR: {db_err}", exc_info=True)
                        conn.rollback()
                        if fail_fast:
                            stopped_early = True; stop_reason = "fail-fast: DB error"
                            continue
                        imported = 0  # mark as failed

                status = "ok" if not dry_run else "dry_run"
                if stopped_early and stop_reason:
                    status = "stopped"

                file_results.append({
                    "file": fname,
                    "rows": len(df),
                    "imported": imported,
                    "skipped": skipped_no_orderid,
                    "warnings": len(file_warnings),
                    "status": status,
                })
                total_imported += imported

                # Always show warning summary (not just first 5)
                if file_warnings:
                    show_count = min(len(file_warnings), 20)
                    unique_warnings = set(file_warnings)
                    logger.warning(f"  Warnings: {len(file_warnings)} total "
                                   f"({len(unique_warnings)} unique)")
                    for w in list(unique_warnings)[:show_count]:
                        logger.warning(f"    {w} "
                                       f"(x{file_warnings.count(w)})")
                    if len(unique_warnings) > show_count:
                        logger.warning(f"    ... and {len(unique_warnings)-show_count} more unique")

            except Exception as e:
                msg = f"{fname}: {e}"
                errors.append(msg)
                logger.error(f"  ERROR: {e}", exc_info=True)
                file_results.append({
                    "file": fname, "rows": 0, "imported": 0, "status": "error",
                    "error": str(e),
                })
                if fail_fast:
                    stopped_early = True
                    stop_reason = "fail-fast: exception"

        conn.commit()

    finally:
        conn.close()

    return {
        "dry_run": dry_run,
        "total_files": len(files),
        "total_imported": total_imported,
        "total_warnings": total_warnings,
        "file_results": file_results,
        "errors": errors,
        "stopped_early": stopped_early,
        "stop_reason": stop_reason,
    }


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def _extract_source_date(fname: str) -> Optional[str]:
    """Extract YYYYMMDD source date from filename like 'fills_20250915_20250919.xlsx'.

    Takes the last 8-digit group in the filename (end date of range).
    """
    parts = fname.replace(".xlsx", "").split("_")
    for part in reversed(parts):
        if len(part) == 8 and part.isdigit():
            return part
    return None


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure raw_fills table exists with all columns including derived ones."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_fills (
            OrderId                  TEXT NOT NULL,
            Account                  TEXT,
            SecurityName             TEXT,
            Ticker                   TEXT,
            Exchange                 TEXT,
            Currency                 TEXT,
            Side                     TEXT,
            Amount                   TEXT,
            NyOrderCreateAsOfDateTime TEXT,
            Type                     TEXT,
            LimitPrice               TEXT,
            Broker                   TEXT,
            StopPrice                TEXT,
            StrategyType             TEXT,
            TraderName               TEXT,
                    TraderUuid               TEXT,
            RouteId                  TEXT,
            NyTranCreateAsOfDateTime  TEXT,
            RouteShares              TEXT,
            FillId                   TEXT NOT NULL,
            ExecType                 TEXT,
            DateTimeOfFill           TEXT,
            FillPrice                REAL,
            FillShares               REAL,
            LastCapacity             TEXT,
            LastMarket               TEXT,
            Liquidity                TEXT,
            LocalExchangeSymbol      TEXT,
            -- Derived columns (added by cleaner layer)
            order_as_of_date          TEXT DEFAULT '',
            order_as_of_time          TEXT DEFAULT '',
            exchange_exec_time        TEXT DEFAULT '',
            route_as_of_time          TEXT DEFAULT '',
            local_fill_datetime       TEXT DEFAULT '',
            -- Metadata
            source_date              TEXT NOT NULL DEFAULT '',
            fetched_at               TEXT DEFAULT '',
            PRIMARY KEY (OrderId, FillId)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_source_date ON raw_fills (source_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_order_date ON raw_fills (order_as_of_date)")
    conn.commit()


# ══════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Import Excel fills into raw_fills.db with HK->NY timezone conversion.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/import_excel_fills.py --dry-run                          # Analyze mapping
  python scripts/import_excel_fills.py --execute                          # Run import (all files)
  python scripts/import_excel_fills.py --execute --file fills_20260302_20260306.xlsx
        """,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze files and show mapping plan without importing.")
    parser.add_argument("--execute", action="store_true",
                        help="Execute the actual import into database.")
    parser.add_argument("--data-dir", type=str,
                        default=str(DATA_DIR),
                        help="Directory containing Excel files.")
    parser.add_argument("--db-path", type=str,
                        default=str(DB_PATH),
                        help="Path to raw_fills.db.")
    parser.add_argument("--fail-fast", action="store_true",
                        help="Stop immediately on first file error or warning threshold breach.")
    parser.add_argument("--warning-threshold", type=int, default=100,
                        help="Max warnings per file before stopping (default: 100).")
    parser.add_argument("--file", type=str, default=None,
                        help="Import only this specific filename (e.g. fills_20250915_20250919.xlsx).")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    data_dir = Path(args.data_dir)
    db_path = Path(args.db_path)

    print("=" * 70)
    print("EXCEL FILLS IMPORTER (HK->NY timezone conversion, RouteId generated)")
    print("=" * 70)
    print(f"Data directory : {data_dir}")
    print(f"Database      : {db_path}")
    if TARGET_DATE_START and TARGET_DATE_END:
        print(f"Target range  : {TARGET_DATE_START} ~ {TARGET_DATE_END}")
    if getattr(args, 'file', None):
        print(f"Single file    : {args.file}")

    if not data_dir.exists():
        print(f"\nERROR: Data directory does not exist: {data_dir}")
        sys.exit(1)

    if args.dry_run:
        print("\n--- DRY RUN MODE ---\n")
        result = analyze_files(data_dir)
        print_analysis(result)

    elif args.execute:
        print("\n--- EXECUTE MODE ---\n")
        result = execute_import(
            data_dir=data_dir,
            db_path=db_path,
            dry_run=False,
            fail_fast=getattr(args, 'fail_fast', False),
            warning_threshold=getattr(args, 'warning_threshold', 100),
            single_file=getattr(args, 'file', None),
        )

        print(f"\n{'='*70}")
        print(f"IMPORT SUMMARY")
        print(f"{'='*70}")
        print(f"Mode          : LIVE (INSERT OR REPLACE)")
        print(f"Total files   : {result['total_files']}")
        print(f"Rows imported : {result['total_imported']:,}")
        print(f"Warnings     : {result['total_warnings']}")
        print(f"Errors        : {len(result['errors'])}")

        print(f"\nPer-file details:")
        for fr in result["file_results"]:
            extra = f", warnings={fr.get('warnings',0)}, skipped={fr.get('skipped',0)}"
            print(f"  [{fr['status'].upper():6s}] {fr['file']:40s} "
                  f"{fr['rows']:>6d} rows -> {fr.get('imported',0):>6d} imported{extra}")

        if result["errors"]:
            print(f"\nErrors ({len(result['errors'])}):")
            for e in result["errors"]:
                print(f"  X {e}")

    else:
        print("\nNo action specified. Use --dry-run or --execute.")
        parser.print_help()


if __name__ == "__main__":
    main()

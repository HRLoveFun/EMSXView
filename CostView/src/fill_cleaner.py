"""
Fill Cleaner — clean and enrich raw EMSX fill data.

Provides three independent operations:
    1. filter_out_dfd()       — remove ExecType=='DFD' (Done For Day) records
    2. derive_exchange_times() — parse EMSX datetimes → local exchange time columns
    3. normalize_fill_columns() — standardize strings, numerics, NaN handling

The combined pipeline clean_emsx_fills() runs all three in sequence.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from .exchange_tz import (
    NY_TZ,
    convert_ny_to_local,
)
from .processing_config import ProcessingConfig as Config
from .schema import EMSX_FILL_COLUMNS

logger = logging.getLogger(__name__)


# ── Step 1: Filter ─────────────────────────────────────────────────────────

def filter_out_dfd(df: pd.DataFrame) -> pd.DataFrame:
    """Filter out ExecType == 'DFD' (Done For Day) records.

    DFD is a terminal order status, not an actual fill. All other ExecType
    values (FILL, PARTIAL_FILL, CANCEL, etc.) are preserved.

    Args:
        df: DataFrame with an 'ExecType' column.

    Returns:
        Filtered DataFrame (copy, never modifies input in-place).
    """
    before = len(df)

    if before == 0 or "ExecType" not in df.columns:
        return df.copy() if before == 0 else df

    mask = (
        df["ExecType"]
        .astype(str)
        .str.strip()
        .str.upper()
        != "DFD"
    )
    result = df[mask].copy()

    filtered = before - len(result)
    if filtered > 0:
        logger.info(f"Filtered {filtered} DFD records ({before} → {len(result)})")

    return result


# ── Step 2: Derive exchange times ──────────────────────────────────────────

def _parse_emsx_datetime(value: Any) -> Optional[datetime]:
    """Parse an EMSX datetime string into a timezone-aware datetime (NY).

    Tries multiple formats to handle variations in Bloomberg output.
    If the parsed datetime is naive, it is assumed to be NY time.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None

    s = str(value).strip()

    # Try pandas parser first (handles most ISO-8601 variants)
    try:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.isna(dt):
            return None
        dt = dt.to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=NY_TZ)
        return dt
    except Exception:
        pass

    # Fallback: explicit format attempts
    for fmt in Config.EMSX_DATETIME_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=NY_TZ)
            return dt
        except ValueError:
            continue

    logger.debug(f"Could not parse EMSX datetime: {value!r}")
    return None


def derive_exchange_times(df: pd.DataFrame) -> pd.DataFrame:
    """Derive local exchange time columns from NY-timezone EMSX datetime fields.

    Input columns required:
        - DateTimeOfFill, Exchange
        - NyOrderCreateAsOfDateTime, NyTranCreateAsOfDateTime (optional)

    Output columns added:
        - local_fill_datetime : full local timestamp (YYYY-MM-DD HH:MM:SS)
        - order_as_of_date    : local trading date (YYYYMMDD) — pipeline partition key
        - exchange_exec_time  : local execution time (HH:MM:SS) — source of mkt_timestamp
        - order_as_of_time    : local order creation time (HH:MM:SS)
        - route_as_of_time    : local route creation time (HH:MM:SS)
    """
    # ── 1. Parse DateTimeOfFill → local_fill_datetime, order_as_of_date, exchange_exec_time ──
    df["_fill_dt"] = df["DateTimeOfFill"].apply(_parse_emsx_datetime)

    local_fill_datetimes = []
    order_as_of_dates = []
    exchange_exec_times = []

    for _, row in df.iterrows():
        dt_ny = row["_fill_dt"]
        exch = row.get("Exchange", "")

        if dt_ny is None:
            local_fill_datetimes.append("")
            order_as_of_dates.append("")
            exchange_exec_times.append("")
            continue

        # Convert to local exchange time
        local_dt = None
        if exch and isinstance(exch, str) and exch.strip():
            local_dt = convert_ny_to_local(dt_ny, exch.strip())

        if local_dt is not None:
            local_fill_datetimes.append(local_dt.strftime(Config.DATETIME_FORMAT))
            order_as_of_dates.append(local_dt.strftime(Config.DATE_FORMAT))
            exchange_exec_times.append(local_dt.strftime(Config.TIME_FORMAT))
        else:
            # Fallback: use NY time if exchange TZ unknown
            local_fill_datetimes.append(dt_ny.strftime(Config.DATETIME_FORMAT))
            order_as_of_dates.append(dt_ny.strftime(Config.DATE_FORMAT))
            exchange_exec_times.append(dt_ny.strftime(Config.TIME_FORMAT))

    df["local_fill_datetime"] = local_fill_datetimes
    df["order_as_of_date"] = order_as_of_dates
    df["exchange_exec_time"] = exchange_exec_times

    # ── 2. Parse NyOrderCreateAsOfDateTime → order_as_of_time (local) ──
    if "NyOrderCreateAsOfDateTime" in df.columns:
        df["_order_dt"] = df["NyOrderCreateAsOfDateTime"].apply(_parse_emsx_datetime)

        def _to_local_time(row: pd.Series) -> str:
            dt_ny = row["_order_dt"]
            if dt_ny is None:
                return ""
            exch = row.get("Exchange", "")
            local_dt = None
            if exch and isinstance(exch, str) and exch.strip():
                local_dt = convert_ny_to_local(dt_ny, exch.strip())
            if local_dt is not None:
                return local_dt.strftime(Config.TIME_FORMAT)
            return dt_ny.strftime(Config.TIME_FORMAT)

        df["order_as_of_time"] = df.apply(_to_local_time, axis=1)
    else:
        df["order_as_of_time"] = ""

    # ── 3. Parse NyTranCreateAsOfDateTime → route_as_of_time (local) ──
    if "NyTranCreateAsOfDateTime" in df.columns:
        df["_route_dt"] = df["NyTranCreateAsOfDateTime"].apply(_parse_emsx_datetime)

        def _to_local_route_time(row: pd.Series) -> str:
            dt_ny = row["_route_dt"]
            if dt_ny is None:
                return ""
            exch = row.get("Exchange", "")
            local_dt = None
            if exch and isinstance(exch, str) and exch.strip():
                local_dt = convert_ny_to_local(dt_ny, exch.strip())
            if local_dt is not None:
                return local_dt.strftime(Config.TIME_FORMAT)
            return dt_ny.strftime(Config.TIME_FORMAT)

        df["route_as_of_time"] = df.apply(_to_local_route_time, axis=1)
    else:
        df["route_as_of_time"] = ""

    # Drop internal temporary columns
    df = df.drop(columns=["_fill_dt", "_order_dt", "_route_dt"], errors="ignore")

    return df


# ── Step 3: Normalize columns ─────────────────────────────────────────────

def normalize_fill_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize string and numeric columns.

    - String columns: strip whitespace, replace NaN/None with ""
    - Numeric columns: coerce to numeric
    - OrderId: convert to string for consistent key handling
    """
    # String columns: strip whitespace, replace NaN with ""
    string_cols = [
        "Ticker", "Exchange", "Currency", "Side", "Broker", "StrategyType",
        "TraderName", "SecurityName", "ExecType", "LastMarket", "Liquidity",
        "Account", "Type", "LocalExchangeSymbol", "LastCapacity",
    ]
    for col in string_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().replace("nan", "").replace("None", "")

    # Numeric columns: coerce to numeric
    numeric_cols = [
        "OrderId", "Amount", "LimitPrice", "StopPrice", "TraderUuid",
        "RouteId", "RouteShares", "FillId", "FillPrice", "FillShares",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # OrderId as string (for consistent key handling)
    if "OrderId" in df.columns:
        df["OrderId"] = df["OrderId"].apply(
            lambda x: str(int(x)) if pd.notna(x) else ""
        )

    return df


# ── Combined pipeline ─────────────────────────────────────────────────────

def clean_emsx_fills(
    fills_or_df: Union[List[Dict[str, Any]], pd.DataFrame],
) -> pd.DataFrame:
    """Clean EMSX fill data: filter + derive exchange times + normalize.

    Pipeline steps (order matters):
        1. filter_out_dfd()       — remove ExecType=='DFD' records
        2. derive_exchange_times() — NY → local timezone conversion
        3. normalize_fill_columns() — standardize data types

    Args:
        fills_or_df: List[Dict] (from API/Excel) or pd.DataFrame.

    Returns:
        Cleaned DataFrame (28 EMSX cols + 5 derived cols = 33 cols).
    """
    # ① List[Dict] → DataFrame
    if isinstance(fills_or_df, list):
        if not fills_or_df:
            return pd.DataFrame(columns=EMSX_FILL_COLUMNS)
        df = pd.DataFrame(fills_or_df)
    else:
        df = fills_or_df.copy()

    if df.empty:
        return df

    n_rows = len(df)

    # Ensure expected columns exist
    for col in EMSX_FILL_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # ② Filter DFD
    df = filter_out_dfd(df)

    if df.empty:
        logger.warning("All records filtered out (ExecType == 'DFD')")
        return df

    # ③ Derive exchange times
    df = derive_exchange_times(df)

    # ④ Normalize columns
    df = normalize_fill_columns(df)

    logger.info(f"Cleaned {n_rows} EMSX fills → {len(df)} rows")
    return df


def clean_emsx_fills_from_excel(file_path: str) -> pd.DataFrame:
    """Read an EMSX fills Excel file and clean it.

    Convenience wrapper for processing existing FillFetch Excel output.
    """
    try:
        df = pd.read_excel(file_path, engine="openpyxl")
        records = df.to_dict("records")
        return clean_emsx_fills(records)
    except Exception as e:
        logger.error(f"Failed to read/clean Excel file {file_path}: {e}")
        return pd.DataFrame()

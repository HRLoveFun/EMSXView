"""
Fill Cleaner — clean and enrich raw EMSX fill data.

Parses EMSX datetime fields, derives local execution times using
exchange timezone mapping, normalizes data types, and prepares fills
for storage in the raw fills database.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from .exchange_tz import (
    NY_TZ,
    convert_ny_to_local,
    get_exchange_timezone,
    get_local_date_str,
    get_local_time_str,
)
from .processing_config import ProcessingConfig as Config
from .schema import EMSX_FILL_COLUMNS

logger = logging.getLogger(__name__)


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


def clean_emsx_fills(fills: List[Dict[str, Any]]) -> pd.DataFrame:
    """Clean raw EMSX fill records and derive additional columns.

    Steps:
        1. Build DataFrame from fill dicts
        2. Parse DateTimeOfFill → exec_date, exec_time, exchange_exec_time, local_fill_datetime
        3. Parse NyOrderCreateAsOfDateTime → order_as_of_date, order_as_of_time
        4. Parse NyTranCreateAsOfDateTime → route_as_of_time
        5. Normalize string/numeric columns

    Args:
        fills: List of dicts from FillFetch / Excel read, with EMSX column names.

    Returns:
        Cleaned DataFrame with original + derived columns.
    """
    if not fills:
        return pd.DataFrame(columns=EMSX_FILL_COLUMNS)

    df = pd.DataFrame(fills)
    n_rows = len(df)

    # Ensure expected columns exist
    for col in EMSX_FILL_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # ── 1. Parse DateTimeOfFill → exec_date, exec_time, exchange_exec_time ──
    df["_fill_dt"] = df["DateTimeOfFill"].apply(_parse_emsx_datetime)

    # exec_time (NY time, HH:MM:SS)
    df["exec_time"] = df["_fill_dt"].apply(
        lambda dt: dt.strftime(Config.TIME_FORMAT) if dt else ""
    )

    # exec_date and exchange_exec_time (local exchange time)
    exec_dates = []
    exchange_exec_times = []
    local_fill_datetimes = []

    for _, row in df.iterrows():
        dt_ny = row["_fill_dt"]
        exch = row.get("Exchange", "")

        if dt_ny is None:
            exec_dates.append("")
            exchange_exec_times.append("")
            local_fill_datetimes.append("")
            continue

        # Try converting to local exchange time
        local_dt = None
        if exch and isinstance(exch, str) and exch.strip():
            local_dt = convert_ny_to_local(dt_ny, exch.strip())

        if local_dt is not None:
            exec_dates.append(local_dt.strftime(Config.DATE_FORMAT))
            exchange_exec_times.append(local_dt.strftime(Config.TIME_FORMAT))
            local_fill_datetimes.append(local_dt.strftime(Config.DATETIME_FORMAT))
        else:
            # Fallback: use NY time if exchange TZ unknown
            exec_dates.append(dt_ny.strftime(Config.DATE_FORMAT))
            exchange_exec_times.append(dt_ny.strftime(Config.TIME_FORMAT))
            local_fill_datetimes.append(dt_ny.strftime(Config.DATETIME_FORMAT))

    df["exec_date"] = exec_dates
    df["exchange_exec_time"] = exchange_exec_times
    df["local_fill_datetime"] = local_fill_datetimes

    # ── 2. Parse NyOrderCreateAsOfDateTime → order_as_of_date, order_as_of_time ──
    df["_order_dt"] = df["NyOrderCreateAsOfDateTime"].apply(_parse_emsx_datetime)

    df["order_as_of_date"] = df.apply(
        _derive_order_as_of_date, axis=1
    )
    df["order_as_of_time"] = df["_order_dt"].apply(
        lambda dt: dt.strftime(Config.TIME_FORMAT) if dt else ""
    )

    # ── 3. Parse NyTranCreateAsOfDateTime → route_as_of_time ──
    df["_route_dt"] = df["NyTranCreateAsOfDateTime"].apply(_parse_emsx_datetime)
    df["route_as_of_time"] = df["_route_dt"].apply(
        lambda dt: dt.strftime(Config.TIME_FORMAT) if dt else ""
    )

    # ── 4. Normalize data types ──
    # String columns: strip whitespace, replace NaN with ""
    string_cols = [
        "Ticker", "Exchange", "Currency", "Side", "Broker", "StrategyType",
        "TraderName", "SecurityName", "ExecType", "LastMarket", "Liquidity",
        "Account", "OrderInstruction", "Type", "LocalExchangeSymbol",
        "RouteExecutionInstruction", "RouteHandlingInstruction", "RouteNotes",
        "LastCapacity",
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

    # Drop internal temporary columns
    df = df.drop(columns=["_fill_dt", "_order_dt", "_route_dt"], errors="ignore")

    logger.info(f"Cleaned {n_rows} EMSX fills → {len(df)} rows, {len(df.columns)} columns")
    return df


def _derive_order_as_of_date(row: pd.Series) -> str:
    """Derive order_as_of_date from NyOrderCreateAsOfDateTime.

    Uses the local exchange date of the order creation time, falling back
    to the NY date if the exchange timezone is unknown.
    """
    dt_ny = row.get("_order_dt")
    if dt_ny is None:
        return ""

    exch = row.get("Exchange", "")
    if exch and isinstance(exch, str) and exch.strip():
        local_date = get_local_date_str(dt_ny, exch.strip(), Config.DATE_FORMAT)
        if local_date:
            return local_date

    # Fallback: NY date
    return dt_ny.strftime(Config.DATE_FORMAT)


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

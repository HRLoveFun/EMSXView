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

import numpy as np
import pandas as pd

from DataPipeline.common.exchange_tz import (
    NY_TZ,
    batch_convert_ny_to_local,
    convert_ny_to_local,
)
from DataPipeline.config import Config
from DataPipeline.storage.schema.columns import EMSX_FILL_COLUMNS

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

    Uses vectorized batch_convert_ny_to_local() grouped by exchange code for
    performance (~10-50x faster than per-row conversion).
    """
    exchange_col = df.get("Exchange", pd.Series("", index=df.index))

    # 硬校验：所有需要时区转换的行必须有非空、已知的 Exchange code
    empty_or_unknown = exchange_col.isna() | (exchange_col.astype(str).str.strip() == "")
    if empty_or_unknown.any():
        raise ValueError(
            f"derive_exchange_times: {int(empty_or_unknown.sum())} 行 Exchange 为空/缺失，"
            "无法进行时区转换。请检查上游 raw_fills 数据。"
        )

    # ── Helper: parse datetime column and vectorize tz conversion + formatting ──
    def _vectorized_convert(col_name, datetime_fmt, date_fmt=None, time_fmt=None):
        """Parse a datetime column, batch-convert to local tz, return formatted Series."""
        # Step 1: Parse to datetime — pandas vectorized parser handles most variants
        raw = df[col_name]
        parsed = pd.to_datetime(raw, errors="coerce")

        # Step 2: For rows that failed pandas parser, try format fallbacks
        nat_mask = parsed.isna() & raw.notna() & (raw.astype(str).str.strip() != "")
        if nat_mask.any():
            for fmt in Config.EMSX_DATETIME_FORMATS:
                still_nat = parsed.isna() & nat_mask
                if not still_nat.any():
                    break
                try:
                    # 使用 where 避免 object dtype 数组的 fillna 降级警告
                    parsed = parsed.where(~parsed.isna(), pd.to_datetime(raw, format=fmt, errors="coerce"))
                except Exception:
                    continue

        # Step 3: Batch convert NY → local exchange tz
        valid_mask = parsed.notna()
        results = {}
        if valid_mask.any():
            local_dt = batch_convert_ny_to_local(parsed[valid_mask], exchange_col[valid_mask])

            if datetime_fmt:
                fmt_series = local_dt.dt.strftime(datetime_fmt)
                results["datetime"] = pd.Series("", index=df.index)
                results["datetime"].loc[valid_mask] = fmt_series
            if date_fmt:
                fmt_series = local_dt.dt.strftime(date_fmt)
                results["date"] = pd.Series("", index=df.index)
                results["date"].loc[valid_mask] = fmt_series
            if time_fmt:
                fmt_series = local_dt.dt.strftime(time_fmt)
                results["time"] = pd.Series("", index=df.index)
                results["time"].loc[valid_mask] = fmt_series

        # Fill missing keys with empty strings
        for key in ("datetime", "date", "time"):
            if key not in results:
                results[key] = pd.Series("", index=df.index)

        return results

    # ── 1. DateTimeOfFill → local_fill_datetime, order_as_of_date, exchange_exec_time ──
    fill_results = _vectorized_convert(
        "DateTimeOfFill",
        datetime_fmt=Config.DATETIME_FORMAT,
        date_fmt=Config.DATE_FORMAT,
        time_fmt=Config.TIME_FORMAT,
    )
    df["local_fill_datetime"] = fill_results["datetime"]
    df["order_as_of_date"] = fill_results["date"]
    df["exchange_exec_time"] = fill_results["time"]

    # ── 2. NyOrderCreateAsOfDateTime → order_as_of_time (local) ──
    if "NyOrderCreateAsOfDateTime" in df.columns:
        order_results = _vectorized_convert(
            "NyOrderCreateAsOfDateTime",
            datetime_fmt=None,
            time_fmt=Config.TIME_FORMAT,
        )
        df["order_as_of_time"] = order_results["time"]
    else:
        df["order_as_of_time"] = ""

    # ── 3. NyTranCreateAsOfDateTime → route_as_of_time (local) ──
    if "NyTranCreateAsOfDateTime" in df.columns:
        route_results = _vectorized_convert(
            "NyTranCreateAsOfDateTime",
            datetime_fmt=None,
            time_fmt=Config.TIME_FORMAT,
        )
        df["route_as_of_time"] = route_results["time"]
    else:
        df["route_as_of_time"] = ""

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
            if col == "Exchange":
                # Exchange 列特殊处理:
                # 1) 字符串 "nan" → "NA" (荷兰交易所代码被 pandas 误转)
                # 2) 真正的 NaN/None 保持 NaN，不能降级为 "NA" 或空字符串，
                #    否则会导致时区转换回退到 NY 时间并产生错误日期。
                is_na = df[col].isna()
                exchange_str = df[col].astype(str).str.strip().replace("nan", "NA")
                empty_mask = exchange_str.isin(["", "None", "NONE", "nan"])
                df[col] = np.where(is_na | empty_mask, np.nan, exchange_str)
            else:
                df[col] = df[col].astype(str).str.strip().replace("nan", "").replace("None", "")

    # Numeric columns: coerce to numeric
    numeric_cols = [
        "OrderId", "Amount", "LimitPrice", "StopPrice", "TraderUuid",
        "RouteShares", "FillPrice", "FillShares",
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

        # ══ 修复: 恢复荷兰交易所代码 "NA" (pandas 默认将字符串 "NA" 解析为 NaN)
        if "Exchange" in df.columns:
            exchange_na_mask = df["Exchange"].isna()
            if exchange_na_mask.any():
                for i in exchange_na_mask[exchange_na_mask].index:
                    original = fills_or_df[i].get("Exchange")
                    if original == "NA":
                        df.at[i, "Exchange"] = "NA"
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
        df_excel = pd.read_excel(file_path)
    except Exception as e:
        logger.error(f"Failed to read Excel file {file_path}: {e}")
        return pd.DataFrame()

    # Map Excel column names to EMSX column names
    col_map = {
        "Route Id": "RouteId",
        "Order Id": "OrderId",
        "Fill Id": "FillId",
        "Fill Price": "FillPrice",
        "Fill Shares": "FillShares",
        "Route Shares": "RouteShares",
        "Trader UUID": "TraderUuid",
        "Local Exchange Symbol": "LocalExchangeSymbol",
        "Security Name": "SecurityName",
        "Stop Price": "StopPrice",
        "Limit Price": "LimitPrice",
        "Last Capacity": "LastCapacity",
        "Strategy Type": "StrategyType",
        "Trader Name": "TraderName",
        "Last Market": "LastMarket",
        "Date Time Of Fill": "DateTimeOfFill",
        "Ny Order Create As Of Date Time": "NyOrderCreateAsOfDateTime",
        "Ny Tran Create As Of Date Time": "NyTranCreateAsOfDateTime",
    }
    df_excel.rename(columns=col_map, inplace=True)

    return clean_emsx_fills(df_excel)

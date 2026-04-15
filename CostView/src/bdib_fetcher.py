"""
BDIB Fetcher — fetch intraday bar data for tickers from processed fills.

Adapted from D:\\Evaluation\\src\\trading_data_processing\\fill_bdib_integrated.py.
Uses xbbg blp.bdib() to fetch 10-second intraday bars and stores results
in processed_fills.db.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from .processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)
# Keep consistent with D:\Evaluation/src/trading_data_processing/bdib.py
# where ref only uses selected exchange codes.
LIST_EXHC_TZ: Set[str] = {"ID", "FH", "GA", "PL"}

# Bloomberg market holiday calendar (major exchanges) — partial list.
# Extend as needed for specific exchange coverage requirements.
# Format: set of "YYYY-MM-DD" strings for non-trading days (excludes weekends).
_BLOOMBERG_KNOWN_HOLIDAYS: Set[str] = set()


def _is_trading_day(dt: date) -> bool:
    """Check if a given date is likely a valid trading day.

    Rules:
        1. Cannot be a future date (after today).
        2. Cannot be Saturday (weekday=5) or Sunday (weekday=6).
        3. Not in known holiday set (extendable).
    """
    today = datetime.now().date()
    if dt > today:
        return False
    if dt.weekday() >= 5:
        return False
    iso = dt.isoformat()
    if iso in _BLOOMBERG_KNOWN_HOLIDAYS:
        return False
    return True


def _flatten_bdib_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten xbbg MultiIndex columns to simple field names.

    xbbg blp.bdib() returns MultiIndex columns like ('AAPL US Equity', 'open').
    This function flattens them to ['open', 'high', 'low', ...].
    """
    if isinstance(df.columns, pd.MultiIndex):
        # Drop ticker level, keep only field name level
        df.columns = [col[1] if len(col) > 1 else col[0] for col in df.columns.values]
    return df


def _validate_bdib_response(
    df: pd.DataFrame,
    ticker: str,
    date_str: str,
) -> Optional[pd.DataFrame]:
    """Validate and clean BDIB response data.

    Checks:
        1. DataFrame is not empty.
        2. Contains at least some rows with actual OHLC/volume data.
        3. Filters out completely empty bars (all OHLC None + volume == 0).

    Returns:
        Cleaned DataFrame, or None if data is entirely invalid.
    """
    if df is None or df.empty:
        logger.debug(f"No BDIB data returned for {ticker} on {date_str}")
        return None

    original_len = len(df)

    # Identify columns that carry price/volume information
    price_cols = ["open", "high", "low", "close"]
    vol_col = "volume"

    available_price_cols = [c for c in price_cols if c in df.columns]

    # Filter out rows where ALL price fields are NaN/None AND volume is 0 or NaN
    if available_price_cols and vol_col in df.columns:
        has_price_data = df[available_price_cols].notna().any(axis=1)
        has_vol_data = df[vol_col].fillna(0) > 0
        valid_mask = has_price_data | has_vol_data
        empty_count = (~valid_mask).sum()

        if empty_count > 0:
            logger.info(
                f"BDIB {ticker} {date_str}: filtering {empty_count}/{original_len} "
                f"empty bars (no OHLC, volume=0)"
            )
            df = df[valid_mask].copy()

    if df.empty:
        logger.warning(
            f"BDIB {ticker} on {date_str}: all {original_len} bars are empty "
            f"(OHLC=None, volume=0). Possible non-trading day or API limitation."
        )
        return None

    remaining = len(df)
    if remaining < original_len:
        logger.info(f"BDIB {ticker} {date_str}: {remaining} valid bars after cleaning")

    return df



def _extract_exchange_from_ticker(ticker: str) -> Optional[str]:
    parts = str(ticker).split()
    if len(parts) >= 2:
        return parts[1].strip().upper()
    return None



def fetch_bdib_for_ticker_date(
    ticker: str,
    date_str: str,
    interval: int = 10,
    exchange: Optional[str] = None,
    max_retries: int = 3,
) -> Optional[pd.DataFrame]:
    """Fetch intraday bar data (BDIB) for a single ticker and date.

    Args:
        ticker: Bloomberg equity ticker (e.g. "7203 JP Equity")
        date_str: Date in YYYYMMDD format
        interval: Bar interval in seconds (default 10)
        exchange: Bloomberg exchange code from ticker_repository (e.g. "JP")
        max_retries: Number of retry attempts

    Returns:
        DataFrame with columns: [mkt_timestamp, open, high, low, close, volume,
        num_trds, value] or None on failure / empty data.
    """
    try:
        from xbbg import blp
    except ImportError:
        logger.error("xbbg not available; cannot fetch BDIB data")
        return None

    # Convert YYYYMMDD to datetime for xbbg
    try:
        dt = datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        logger.error(f"Invalid date format: {date_str}")
        return None

    # ── Date validation: reject future dates and weekends early ──
    if not _is_trading_day(dt):
        logger.info(
            f"Skipping BDIB fetch for {ticker} on {date_str}: "
            f"not a valid trading day (future/weekend/holiday)"
        )
        return None

    normalized_exchange = str(exchange).strip().upper() if exchange is not None else None
    if not normalized_exchange:
        normalized_exchange = _extract_exchange_from_ticker(ticker)
    ref_exchange = normalized_exchange if normalized_exchange in LIST_EXHC_TZ else None

    last_exception: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            df = blp.bdib(
                ticker,
                dt=dt.strftime("%Y-%m-%d"),
                session="day",
                typ="TRADE",
                interval=interval,
                intervalHasSeconds=True,
                ref=ref_exchange,
                batch=True,
            )

            # Flatten xbbg MultiIndex columns FIRST (before any column-level logic)
            # xbbg returns ('AAPL US Equity', 'open') style tuples
            df = _flatten_bdib_columns(df)

            # Validate response quality — filter out empty bars
            df = _validate_bdib_response(df, ticker, date_str)
            if df is None:
                return None

            # Standardize the output
            if isinstance(df.index, pd.DatetimeIndex):
                # xbbg returns DatetimeIndex with timezone info (e.g. -04:00)
                ts = df.index
                if ts.tz is not None:
                    ts = ts.tz_localize(None)
                mkt_ts = ts.floor(f"{interval}s").strftime("%H:%M:%S")
                df = df.reset_index()
                df["mkt_timestamp"] = mkt_ts
                if "index" in df.columns:
                    df.drop(columns=["index"], inplace=True)
            else:
                df = df.reset_index()
                if "index" in df.columns:
                    df.rename(columns={"index": "timestamp"}, inplace=True)
                if "timestamp" in df.columns:
                    df["mkt_timestamp"] = (
                        pd.to_datetime(df["timestamp"])
                        .dt.floor(f"{interval}s")
                        .dt.strftime("%H:%M:%S")
                        )
                elif df.index.name and "time" in df.index.name.lower():
                    df["mkt_timestamp"] = (
                        pd.to_datetime(df.index)
                        .floor(f"{interval}s")
                        .strftime("%H:%M:%S")
                    )

            df["equ_ticker"] = ticker
            df["Order As of Date"] = date_str

            # Standardize column names
            col_map = {
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
                "num_trds": "num_trds",
                "value": "value",
            }
            for old_name, new_name in col_map.items():
                if old_name not in df.columns:
                    for c in df.columns:
                        if c.lower() == old_name:
                            df.rename(columns={c: new_name}, inplace=True)
                            break

            # NOTE: Derived fields (vwap, fluctuation, log_chg_pct_10s) are NOT
            # computed here. They belong to the processed_raw_bdib layer per
            # D:\Evaluation convention: raw_bdib → processed_bdib → fill_bdib.
            # Use ProcessedRawBDIBDB.compute_derived_fields(df) when needed.

            logger.debug(f"Fetched {len(df)} raw BDIB bars for {ticker} on {date_str}")
            return df

        except Exception as e:
            last_exception = e
            if attempt == max_retries - 1:
                logger.warning(f"BDIB fetch failed for {ticker} on {date_str}: {e}")
            continue

    # All retries exhausted
    if last_exception is not None:
        logger.error(
            f"All {max_retries} retries exhausted for {ticker} on {date_str}: "
            f"{last_exception}"
        )
    return None


def fetch_bdib_for_fills(
    ticker_dates: Dict[str, List[str]],
    interval: int = 10,
    ticker_exchange_map: Optional[Dict[str, str]] = None,
) -> Dict[str, pd.DataFrame]:
    """Fetch BDIB data for all (ticker, date) pairs.

    Args:
        ticker_dates: Dict mapping equ_ticker → list of YYYYMMDD dates
        interval: Bar interval in seconds
        ticker_exchange_map: equ_ticker -> Exchange mapping from ticker_repository

    Returns:
        Dict mapping "ticker|date" → BDIB DataFrame
    """
    results: Dict[str, pd.DataFrame] = {}
    total_pairs = sum(len(dates) for dates in ticker_dates.values())

    # Pre-filter invalid (future/weekend) dates with a warning
    valid_pairs: List[Tuple[str, str]] = []
    skipped_non_trading = 0
    for ticker, dates in ticker_dates.items():
        for date_str in dates:
            try:
                dt = datetime.strptime(date_str, "%Y%m%d").date()
                if _is_trading_day(dt):
                    valid_pairs.append((ticker, date_str))
                else:
                    skipped_non_trading += 1
            except ValueError:
                logger.warning(f"Skipping invalid date format: {date_str}")
                skipped_non_trading += 1

    if skipped_non_trading > 0:
        logger.info(
            f"BDIB pre-filter: skipped {skipped_non_trading}/{total_pairs} "
            f"non-trading dates (future/weekend/holiday)"
        )

    logger.info(f"Fetching BDIB data for {len(ticker_dates)} tickers, {len(valid_pairs)} valid pairs")

    fetched = 0
    empty_data = 0
    exchange_map = ticker_exchange_map or {}
    for ticker, date_str in valid_pairs:
        exchange = exchange_map.get(ticker)
        df = fetch_bdib_for_ticker_date(
            ticker,
            date_str,
            interval=interval,
            exchange=exchange,
        )
        if df is not None and not df.empty:
            key = f"{ticker}|{date_str}"
            results[key] = df
            fetched += 1
        else:
            empty_data += 1

    logger.info(
        f"BDIB fetch complete: {fetched} valid, {empty_data} empty, "
        f"{skipped_non_trading} skipped (non-trading day)"
    )
    return results


def get_bdib_for_date(
    bdib_data: Dict[str, pd.DataFrame],
    date_str: str,
) -> pd.DataFrame:
    """Combine all BDIB data for a single date."""
    dfs = []
    for key, df in bdib_data.items():
        if key.endswith(f"|{date_str}"):
            dfs.append(df)
    if dfs:
        return pd.concat(dfs, ignore_index=True)
    return pd.DataFrame()

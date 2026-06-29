"""
BDIB Fetcher — fetch intraday bar data for tickers from processed fills.

Adapted from D:\\Evaluation\\src\\trading_data_processing\\fill_bdib_integrated.py.
Uses xbbg blp.bdib() to fetch 10-second intraday bars and stores results
in processed_fills.db.

"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from DataPipeline.common.outdated_tickers import load_outdated_ticker_set, record_outdated_ticker
from DataPipeline.config import Config

logger = logging.getLogger(__name__)
# Keep consistent with D:\Evaluation/src/trading_data_processing/bdib.py
# where ref only uses selected exchange codes.
LIST_EXHC_TZ: Set[str] = {"ID", "FH", "GA", "PL"}

# Bloomberg market holiday calendar (major exchanges) — partial list.
# Extend as needed for specific exchange coverage requirements.
# Format: set of "YYYY-MM-DD" strings for non-trading days (excludes weekends).
_BLOOMBERG_KNOWN_HOLIDAYS: Set[str] = set()
_OUTDATED_TICKER_REASON = "cannot_find_exchange_info"

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

def _get_previous_weekday(today: date) -> date:
    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate

def _latest_safe_bdib_date(now: Optional[datetime] = None) -> date:
    ref_dt = now or datetime.now()
    safe_date = _get_previous_weekday(ref_dt.date())

    if safe_date == ref_dt.date() - timedelta(days=1) and ref_dt.hour < Config.BDIB_LATEST_READY_HOUR_LOCAL:
        safe_date = _get_previous_weekday(safe_date)

    return safe_date

def _is_safe_bdib_query_date(dt: date, now: Optional[datetime] = None) -> bool:
    return dt <= _latest_safe_bdib_date(now)

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

def _is_outdated_ticker_error(exc: Exception) -> bool:
    return "Cannot find exchange info" in str(exc)

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
        max_retries: Number of retry attempts（已由 RetryPolicy 管理，保留参数兼容）

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

    if not _is_safe_bdib_query_date(dt):
        logger.info(
            f"Skipping BDIB fetch for {ticker} on {date_str}: "
            f"date is too close to current time and not yet in the safe BDIB window"
        )
        return None

    normalized_exchange = str(exchange).strip().upper() if exchange is not None else None
    if not normalized_exchange:
        normalized_exchange = _extract_exchange_from_ticker(ticker)
    ref_exchange = normalized_exchange if normalized_exchange in LIST_EXHC_TZ else None

    # ── 使用 RetryPolicy 包装 Bloomberg API 调用 ──
    from DataPipeline.circuit_breaker.retry_policy import RetryConfig, RetryPolicy, RetryResult

    retry_config = RetryConfig(
        max_retries=max_retries,
        base_delay_seconds=1.0,
        backoff_factor=2.0,
    )
    policy = RetryPolicy(retry_config)

    def _fetch_bdib_once() -> pd.DataFrame:
        """单次 BDIB 抓取（供 RetryPolicy 重试调用）"""
        try:
            df = blp.bdib(
                ticker,
                dt=dt.strftime("%Y-%m-%d"),
                session="day",
                typ="TRADE",
                interval=interval,
                intervalHasSeconds=True,
                ref=ref_exchange,
                batch=False,
            )
        except Exception as e:
            # 过期 ticker 立即标记，不重试
            if _is_outdated_ticker_error(e):
                entry = record_outdated_ticker(
                    ticker,
                    _OUTDATED_TICKER_REASON,
                    detail=str(e),
                )
                logger.warning(
                    f"Marked outdated ticker {ticker} after exchange-info failure; "
                    f"hit_count={entry['hit_count']}"
                )
            raise  # 重新抛出，让 RetryPolicy 处理重试

        return df

    fetch_result: RetryResult = policy.execute_with_retry_sync(
        _fetch_bdib_once,
        context={"ticker": ticker, "date": date_str},
    )

    # 处理重试耗尽情况
    if not fetch_result.success:
        # 检查是否是过期 ticker（已在 _fetch_bdib_once 中标记，直接跳过）
        if fetch_result.last_error and "Cannot find exchange info" in fetch_result.last_error:
            return None
        logger.warning(
            f"BDIB fetch failed after {fetch_result.attempts} attempts "
            f"for {ticker} on {date_str}: {fetch_result.last_error}"
        )
        return None

    # ── 处理成功的响应 ──
    df = fetch_result.result

    # Flatten xbbg MultiIndex columns FIRST (before any column-level logic)
    df = _flatten_bdib_columns(df)

    # Validate response quality — filter out empty bars
    df = _validate_bdib_response(df, ticker, date_str)
    if df is None:
        return None

    # Standardize the output
    if isinstance(df.index, pd.DatetimeIndex):
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
    df["order_as_of_date"] = date_str

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

    logger.debug(f"Fetched {len(df)} raw BDIB bars for {ticker} on {date_str}")
    return df

def fetch_bdib_batch(
    ticker_date_pairs: List[Tuple[str, str]],
    max_workers: int = 4,
    interval: int = 10,
    exchange_map: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """Fetch BDIB data for multiple (ticker, date) pairs in parallel.

    Args:
        ticker_date_pairs: List of (ticker, date_str) tuples
        max_workers: Max parallel workers (Bloomberg API connections)
        interval: Bar interval in seconds
        exchange_map: Optional ticker -> exchange code mapping

    Returns:
        Combined DataFrame with all fetched BDIB data
    """
    results: List[pd.DataFrame] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}
        for ticker, date_str in ticker_date_pairs:
            exchange = exchange_map.get(ticker) if exchange_map else None
            future = executor.submit(
                fetch_bdib_for_ticker_date, ticker, date_str, interval, exchange
            )
            future_map[future] = (ticker, date_str)

        for future in as_completed(future_map):
            ticker, date_str = future_map[future]
            try:
                df = future.result()
                if df is not None and not df.empty:
                    results.append(df)
            except Exception as e:
                logger.error(f"BDIB batch fetch failed for {ticker} on {date_str}: {e}")

    if results:
        combined = pd.concat(results, ignore_index=True)
        logger.info(f"BDIB batch fetch completed: {len(combined)} bars from {len(results)} ticker-dates")
        return combined

    return pd.DataFrame()

def fetch_bdib_for_fills(
    ticker_dates: dict[str, list[str]],
    ticker_exchange_map: Optional[dict[str, str]] = None,
    interval: int = 10,
    max_workers: int = 4,
) -> dict[str, pd.DataFrame]:
    """Fetch BDIB data for fill processing, skipping outdated tickers.

    Orchestrates parallel BDIB fetches for the given ticker-date pairs,
    filters out tickers known to be outdated, and returns results keyed
    by ``"TICKER|DATE"`` so that callers can determine per-pair success.

    Args:
        ticker_dates: Mapping of ticker -> list of YYYYMMDD date strings.
        ticker_exchange_map: Optional mapping of ticker -> Bloomberg exchange code.
        interval: Bar interval in seconds (default 10).
        max_workers: Max parallel workers (default 4).

    Returns:
        Dict mapping ``"{ticker}|{date_str}"`` -> BDIB DataFrame, containing
        only pairs that were actually fetched (i.e. non-outdated, non-empty).
    """
    outdated = load_outdated_ticker_set()

    # Build the list of (ticker, date) pairs, skipping outdated tickers entirely
    pairs: list[tuple[str, str]] = []
    for ticker, dates in ticker_dates.items():
        if ticker in outdated:
            logger.info(f"fetch_bdib_for_fills: skipping outdated ticker {ticker}")
            continue
        for date_str in dates:
            pairs.append((ticker, date_str))

    if not pairs:
        logger.info("fetch_bdib_for_fills: no non-outdated pairs to fetch")
        return {}

    combined = fetch_bdib_batch(
        pairs,
        max_workers=max_workers,
        interval=interval,
        exchange_map=ticker_exchange_map,
    )

    result: dict[str, pd.DataFrame] = {}
    if not combined.empty and "equ_ticker" in combined.columns and "order_as_of_date" in combined.columns:
        for (ticker, date_str), group in combined.groupby(
            ["equ_ticker", "order_as_of_date"], sort=False
        ):
            key = f"{ticker}|{date_str}"
            result[key] = group.reset_index(drop=True)

    logger.info(
        f"fetch_bdib_for_fills: {len(result)} ticker-dates fetched "
        f"({len(pairs) - len(result)} empty/failed)"
    )
    return result

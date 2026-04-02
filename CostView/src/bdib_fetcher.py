"""
BDIB Fetcher — fetch intraday bar data for tickers from processed fills.

Adapted from D:\\Evaluation\\src\\trading_data_processing\\fill_bdib_integrated.py.
Uses xbbg blp.bdib() to fetch 10-second intraday bars and stores results
in processed_fills.db.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from .processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)


def fetch_bdib_for_ticker_date(
    ticker: str,
    date_str: str,
    interval: int = 10,
    max_retries: int = 3,
) -> Optional[pd.DataFrame]:
    """Fetch intraday bar data (BDIB) for a single ticker and date.

    Args:
        ticker: Bloomberg equity ticker (e.g. "7203 JP Equity")
        date_str: Date in YYYYMMDD format
        interval: Bar interval in seconds (default 10)
        max_retries: Number of retry attempts

    Returns:
        DataFrame with columns: [mkt_timestamp, open, high, low, close, volume,
        num_trds, value] or None on failure.
    """
    try:
        from xbbg import blp
    except ImportError:
        logger.error("xbbg not available; cannot fetch BDIB data")
        return None

    # Convert YYYYMMDD to datetime for xbbg
    try:
        dt = datetime.strptime(date_str, "%Y%m%d")
    except ValueError:
        logger.error(f"Invalid date format: {date_str}")
        return None

    for attempt in range(max_retries):
        try:
            df = blp.bdib(
                ticker,
                dt=dt.strftime("%Y-%m-%d"),
                session="day",
                typ="TRADE",
            )

            if df is None or df.empty:
                logger.debug(f"No BDIB data for {ticker} on {date_str}")
                return None

            # Standardize the output
            df = df.reset_index()

            # Ensure mkt_timestamp column exists
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
                    # Try case-insensitive match
                    for c in df.columns:
                        if c.lower() == old_name:
                            df.rename(columns={c: new_name}, inplace=True)
                            break

            # Compute derived fields
            if "close" in df.columns:
                df["vwap"] = np.where(
                    df.get("volume", pd.Series(0)) > 0,
                    df.get("value", df["close"] * df.get("volume", 1)) / df.get("volume", 1),
                    df["close"],
                )
                # Log change pct (10s interval)
                df["log_chg_pct_10s"] = np.log(
                    df["close"] / df["close"].shift(1)
                ).fillna(0)
                df["fluctuation"] = (df["high"] - df["low"]) / df["close"]

            logger.debug(f"Fetched {len(df)} BDIB bars for {ticker} on {date_str}")
            return df

        except Exception as e:
            if attempt == max_retries - 1:
                logger.warning(f"BDIB fetch failed for {ticker} on {date_str}: {e}")
            continue

    return None


def fetch_bdib_for_fills(
    ticker_dates: Dict[str, List[str]],
    interval: int = 10,
) -> Dict[str, pd.DataFrame]:
    """Fetch BDIB data for all (ticker, date) pairs.

    Args:
        ticker_dates: Dict mapping equ_ticker → list of YYYYMMDD dates
        interval: Bar interval in seconds

    Returns:
        Dict mapping "ticker|date" → BDIB DataFrame
    """
    results: Dict[str, pd.DataFrame] = {}
    total_pairs = sum(len(dates) for dates in ticker_dates.values())

    logger.info(f"Fetching BDIB data for {len(ticker_dates)} tickers, {total_pairs} ticker-date pairs")

    fetched = 0
    for ticker, dates in ticker_dates.items():
        for date_str in dates:
            df = fetch_bdib_for_ticker_date(ticker, date_str, interval=interval)
            if df is not None and not df.empty:
                key = f"{ticker}|{date_str}"
                results[key] = df
                fetched += 1

    logger.info(f"Fetched BDIB data for {fetched}/{total_pairs} ticker-date pairs")
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

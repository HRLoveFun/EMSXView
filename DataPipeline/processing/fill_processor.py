"""
Fill Processor — transform cleaned EMSX fills into processed fills.

Adapted from D:\\Evaluation\\src\\trading_data_processing\\fill.py.
All functions use EMSX column names (e.g. StrategyType not "Strategy Type",
FillPrice not "Exec Last Fill Px", exchange_exec_time not "Exchange Exec Time").

"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from DataPipeline.common.mapping import (
    EXCHANGE_AUCTION_TIME_ADJUST,
    close,
    closing_auction_times,
    currency_region,
    pov,
    twap,
    vwap,
)
from DataPipeline.config import Config

logger = logging.getLogger(__name__)

# ── Algo Classification ─────────────────────────────────────────────────────

def add_algo_column(df: pd.DataFrame) -> pd.DataFrame:
    """Classify fills into algo categories based on Broker + StrategyType.

    EMSX uses 'StrategyType' (not 'Strategy Type' as in Evaluation).
    """
    df = df.copy()
    df["algo"] = "other"

    def _apply_mapping(algo_name: str, mapping_dict: Dict[str, List[str]]):
        for broker, strategies in mapping_dict.items():
            if not strategies:
                continue
            mask = (df["Broker"] == broker) & (df["StrategyType"].isin(strategies))
            if mask.any():
                df.loc[mask, "algo"] = algo_name

    _apply_mapping("vwap", vwap)
    _apply_mapping("twap", twap)
    _apply_mapping("pov", pov)
    _apply_mapping("close", close)

    return df

# ── Currency Columns ─────────────────────────────────────────────────────────

def add_currency_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add ccy_ticker and region columns from Currency."""
    df = df.copy()
    currency_upper = df["Currency"].astype(str).str.upper()
    df["ccy_ticker"] = np.where(
        currency_upper != "USD",
        "USD" + currency_upper + " Curncy",
        "USD Curncy",
    )
    df["region"] = df["Currency"].map(currency_region)
    return df

# ── Equity Ticker ────────────────────────────────────────────────────────────

def add_equity_ticker(df: pd.DataFrame) -> pd.DataFrame:
    """Add equ_ticker column with Bloomberg equity ticker.

    EMSX uses Ticker, Exchange, Currency (same names as Evaluation).
    For EUR stocks, attempts to resolve EU composite tickers via blp.bdp.
    """
    required = ["Ticker", "Exchange", "Currency"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.copy()

    # KRW tickers need zero-padding
    df["_processed_ticker"] = np.where(
        df["Currency"] == "KRW",
        df["Ticker"].astype(str).str.zfill(6),
        df["Ticker"].astype(str),
    )

    df["equ_ticker"] = (
        df["_processed_ticker"] + " " + df["Exchange"] + " Equity"
    ).str.strip()

    # EUR composite ticker resolution
    eur_mask = df["Currency"] == "EUR"
    if eur_mask.any():
        unique_eur_tickers = df.loc[eur_mask, "equ_ticker"].dropna().unique().tolist()
        composite_map = _fetch_composite_tickers(unique_eur_tickers)
        if composite_map:
            df.loc[eur_mask, "equ_ticker"] = df.loc[eur_mask, "equ_ticker"].map(
                lambda x: composite_map.get(x, x).strip() if pd.notna(x) else x
            )

    return df.drop(columns=["_processed_ticker"])

def _fetch_composite_tickers(
    tickers: List[str], chunk_size: int = 100, max_retries: int = 3
) -> Dict[str, str]:
    """Fetch EU_COMPOSITE_TICKER via xbbg blp.bdp with retry."""
    results: Dict[str, str] = {}
    try:
        from xbbg import blp
    except ImportError:
        logger.warning("xbbg not available; skipping EUR composite ticker resolution")
        return results

    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        for attempt in range(max_retries):
            try:
                response = blp.bdp(chunk, "EU_COMPOSITE_TICKER")
                if "eu_composite_ticker" in response.columns:
                    results.update(response["eu_composite_ticker"].astype(str).to_dict())
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.warning(
                        f"EUR composite fetch failed for chunk {i // chunk_size}: {e}"
                    )
    return results

# ── Market Timestamp (10-second floor) ───────────────────────────────────────

def add_mkt_timestamp_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add mkt_timestamp (10s floor) and is_closing_auction from exchange_exec_time.

    EMSX uses 'exchange_exec_time' (derived column) instead of Evaluation's
    'Exchange Exec Time'.
    """
    df = df.copy()

    # Parse exchange_exec_time to datetime for arithmetic
    exec_time_dt = pd.to_datetime(
        df["exchange_exec_time"].astype(str), format="%H:%M:%S.%f", errors="coerce"
    )
    mask_na = exec_time_dt.isna()
    if mask_na.any():
        exec_time_dt.loc[mask_na] = pd.to_datetime(
            df.loc[mask_na, "exchange_exec_time"].astype(str),
            format=Config.TIME_FORMAT,
            errors="coerce",
        )

    # Floor to 10-second intervals
    df["mkt_timestamp"] = exec_time_dt.dt.floor("10s").dt.strftime("%H:%M:%S")

    # Closing auction detection
    df["is_closing_auction"] = False

    for exchange, close_time_str in closing_auction_times.items():
        close_time = pd.to_datetime(close_time_str, format=Config.TIME_FORMAT).time()
        exch_mask = df["Exchange"] == exchange

        if not exch_mask.any():
            continue

        if exchange in EXCHANGE_AUCTION_TIME_ADJUST:
            adj_time = (exec_time_dt[exch_mask] + pd.Timedelta(minutes=1)).dt.time
            auction_mask = adj_time >= close_time
        else:
            mkt_time = pd.to_datetime(
                df.loc[exch_mask, "mkt_timestamp"], format="%H:%M:%S"
            ).dt.time
            auction_mask = mkt_time >= close_time

        df.loc[
            exch_mask & auction_mask.reindex(df.index, fill_value=False),
            "is_closing_auction",
        ] = True

    return df

# ── Route Market Timestamp ───────────────────────────────────────────────────

def add_route_mkt_timestamp_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add route_mkt_timestamp by applying 10-second floor to route_as_of_time.

    EMSX derived columns:
      - exchange_exec_time (local exchange time)
      - route_as_of_time (local exchange time)
    """
    df = df.copy()

    def _to_seconds(series: pd.Series) -> pd.Series:
        dt_series = pd.to_datetime(
            series.astype(str), format="%H:%M:%S.%f", errors="coerce"
        )
        mask = dt_series.isna()
        if mask.any():
            dt_series.loc[mask] = pd.to_datetime(
                series.loc[mask].astype(str), format=Config.TIME_FORMAT, errors="coerce"
            )
        return dt_series.dt.hour * 3600 + dt_series.dt.minute * 60 + dt_series.dt.second

    rt_sec = _to_seconds(df["route_as_of_time"])

    # Round to 10-second intervals
    new_rt_total = (rt_sec // 10) * 10

    hours = (new_rt_total // 3600).fillna(0).astype(int)
    minutes = ((new_rt_total % 3600) // 60).fillna(0).astype(int)
    seconds = (new_rt_total % 60).fillna(0).astype(int)

    time_strs = (
        hours.astype(str).str.zfill(2)
        + ":"
        + minutes.astype(str).str.zfill(2)
        + ":"
        + seconds.astype(str).str.zfill(2)
    )
    df["route_mkt_timestamp"] = pd.to_datetime(
        time_strs, format="%H:%M:%S", errors="coerce"
    ).dt.time

    mask_nan = rt_sec.isna()
    df.loc[mask_nan, "route_mkt_timestamp"] = None

    return df

# ── Pipeline: Process a DataFrame ───────────────────────────────────────────

def process_fills(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all transformation steps to a cleaned EMSX fills DataFrame.

    Expects input that has already been through clean_emsx_fills()
    (i.e. DFD filtered, exchange times derived, columns normalized).

    Pipeline:
        1. add_algo_column
        2. add_currency_columns
        3. add_equity_ticker
        4. add_mkt_timestamp_columns
        5. add_route_mkt_timestamp_columns
    """
    if df.empty:
        return df

    # Ensure string columns are clean strings (not 'nan')
    for col in ["Broker", "StrategyType", "Exchange", "Ticker", "Currency", "Side"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().replace("nan", "").replace("None", "")

    processed = (
        df.pipe(add_algo_column)
        .pipe(add_currency_columns)
        .pipe(add_equity_ticker)
        .pipe(add_mkt_timestamp_columns)
        .pipe(add_route_mkt_timestamp_columns)
    )

    logger.info(f"Processed {len(processed)} fills -> added algo/ccy/ticker/timestamp columns")
    return processed

def process_raw_fills(df: pd.DataFrame) -> pd.DataFrame:
    """Full pipeline: clean then process.

    Convenience function that runs clean_emsx_fills() + process_fills()
    in sequence. Use when the input has NOT been pre-cleaned.

    Args:
        df: Raw EMSX DataFrame or List[Dict].
    """
    from .fill_cleaner import clean_emsx_fills

    cleaned = clean_emsx_fills(df)
    return process_fills(cleaned)

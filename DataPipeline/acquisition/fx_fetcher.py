"""
FX Rate Fetcher — fetch daily PX_LAST from Bloomberg for ccy_tickers.

Usage:
    fx_rates = fetch_fx_rates_for_date(["USDJPY Curncy", "USDGBP Curncy"], "20260408")
    # -> {"USDJPY Curncy": 0.00697, "USDGBP Curncy": 1.2658}
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

_BLOOMBERG_FIELD = "PX_LAST"


def fetch_fx_rate_for_ccy(ccy_ticker: str, date_str: str) -> float:
    """Fetch daily PX_LAST for a single ccy_ticker on a given date.

    Bloomberg returns inverse quotes for USD{ccy} Curncy, e.g.
    PX_LAST of "USDJPY Curncy" = 143.50 -> fx_rate = 1/143.50 = 0.00697.

    Returns fx_rate as USD per 1 unit of currency.
    Defaults to 1.0 on any failure (no FX impact on TCA).
    """
    from xbbg import blp

    ccy_upper = ccy_ticker.upper().strip()
    if not ccy_upper or ccy_upper in ("USD Curncy", "USD", ""):
        return 1.0

    try:
        dt = datetime.strptime(date_str, "%Y%m%d")
        df = blp.bdh(ccy_ticker, _BLOOMBERG_FIELD, dt, dt)
        if df is not None and not df.empty:
            raw_px = float(df.iloc[0, 0])
            if raw_px > 0:
                return 1.0 / raw_px
        logger.info("No PX_LAST data for %s on %s, defaulting to 1.0", ccy_ticker, date_str)
    except Exception as e:
        logger.warning("Failed to fetch FX rate for %s on %s: %s", ccy_ticker, date_str, e)

    return 1.0


def fetch_fx_rates_for_date(
    ccy_tickers: list[str],
    date_str: str,
) -> dict[str, float]:
    """Fetch daily PX_LAST for a list of ccy_tickers on a given date.

    Returns {ccy_ticker: fx_rate}. USD Curncy and unknown tickers
    default to 1.0 (= no FX impact on TCA).
    """
    results: dict[str, float] = {}
    for ccy in ccy_tickers:
        results[ccy] = fetch_fx_rate_for_ccy(ccy, date_str)
    return results


def fx_rates_to_dataframe(
    results: dict[str, float],
    date_str: str,
) -> pd.DataFrame:
    """Convert {ccy_ticker: fx_rate} dict to DataFrame with date column."""
    return pd.DataFrame([
        {"ccy_ticker": k, "fx_rate": v, "order_as_of_date": date_str}
        for k, v in results.items()
    ])

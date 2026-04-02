"""
Fill-BDIB Integration — merge processed fills with intraday bar data.

Adapted from D:\\Evaluation\\src\\trading_data_processing\\fill_bdib_integrated.py.
Merges 10-second aggregated fills with BDIB market data, adds FX rates and
daily equity metrics, and computes TCA-related derived metrics.

All functions use EMSX column names (OrderId, FillShares, FillPrice, etc.).
"""

from __future__ import annotations

import gc
import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .bdib_fetcher import fetch_bdib_for_ticker_date
from .processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)


def integrate_fills_bdib_for_date(
    agg_fills_df: pd.DataFrame,
    date_str: str,
    bdib_data: Optional[pd.DataFrame] = None,
    fx_rates: Optional[pd.DataFrame] = None,
    daily_equity_data: Optional[Dict[str, pd.DataFrame]] = None,
) -> pd.DataFrame:
    """Integrate aggregated fills with BDIB market data for a single date.

    Steps:
        A. Merge fills with BDIB on (equ_ticker, order_as_of_date, mkt_timestamp)
        B. Add FX rates
        C. Add daily equity metrics (chg_pct_1d, bid_ask_spread_%)
        D. Rename columns for TCA output
        E. Compute derived metrics (fill_value, cum_*, slippage, etc.)

    Args:
        agg_fills_df: 10-second aggregated fills for this date
        date_str: YYYYMMDD date string
        bdib_data: Pre-fetched BDIB data (or None to fetch on demand)
        fx_rates: FX rates DataFrame (long format: ccy_ticker, Order As of Date, fx_rate)
        daily_equity_data: Dict with keys 'chg_pct_1d', 'bid_ask_spread' → DataFrames

    Returns:
        Integrated DataFrame with all TCA metrics
    """
    if agg_fills_df.empty:
        return pd.DataFrame()

    df_fills = agg_fills_df.copy()

    # Ensure date column consistency
    if "order_as_of_date" in df_fills.columns:
        df_fills["order_as_of_date"] = df_fills["order_as_of_date"].astype(str)
    else:
        df_fills["order_as_of_date"] = date_str

    # ── A. Fetch and merge BDIB data ──────────────────────────────────────

    if bdib_data is None:
        # Fetch on demand for all tickers in this date's fills
        tickers = df_fills["equ_ticker"].dropna().unique().tolist() if "equ_ticker" in df_fills.columns else []
        bdib_list = []
        for ticker in tickers:
            df_bdib = fetch_bdib_for_ticker_date(ticker, date_str)
            if df_bdib is not None and not df_bdib.empty:
                bdib_list.append(df_bdib)
        bdib_data = pd.concat(bdib_list, ignore_index=True) if bdib_list else pd.DataFrame()

    if not bdib_data.empty:
        # Determine merge keys
        merge_keys = ["equ_ticker", "mkt_timestamp"]
        if "order_as_of_date" in bdib_data.columns:
            merge_keys.append("order_as_of_date")
            bdib_data["order_as_of_date"] = bdib_data["order_as_of_date"].astype(str)

        valid_keys = [k for k in merge_keys if k in df_fills.columns and k in bdib_data.columns]

        if valid_keys:
            for k in valid_keys:
                df_fills[k] = df_fills[k].astype(str)
                bdib_data[k] = bdib_data[k].astype(str)

            df_merged = pd.merge(
                df_fills, bdib_data, on=valid_keys, how="left", suffixes=("", "_bdib")
            )
        else:
            df_merged = df_fills
    else:
        df_merged = df_fills
        # Add empty BDIB columns
        for col in ["open", "high", "low", "close", "volume", "num_trds", "value", "vwap", "fluctuation", "log_chg_pct_10s"]:
            df_merged[col] = np.nan

    # ── B. Add FX rates ───────────────────────────────────────────────────

    if fx_rates is not None and not fx_rates.empty:
        fx_for_date = fx_rates[fx_rates["order_as_of_date"] == date_str].copy()
        if not fx_for_date.empty and "ccy_ticker" in df_merged.columns:
            df_merged = pd.merge(
                df_merged,
                fx_for_date[["order_as_of_date", "ccy_ticker", "fx_rate"]],
                on=["order_as_of_date", "ccy_ticker"],
                how="left",
            )
        else:
            df_merged["fx_rate"] = np.nan
    else:
        df_merged["fx_rate"] = np.nan

    # USD/USD → fx_rate = 1.0
    if "ccy_ticker" in df_merged.columns:
        usd_mask = df_merged["ccy_ticker"].astype(str).str.contains("USD", na=False)
        df_merged.loc[usd_mask & df_merged["fx_rate"].isna(), "fx_rate"] = 1.0

    # ── C. Add daily equity metrics ───────────────────────────────────────

    if daily_equity_data:
        for field_name, field_df in daily_equity_data.items():
            if field_df is None or field_df.empty:
                df_merged[field_name] = np.nan
                continue

            field_df = field_df.copy()
            if "order_as_of_date" in field_df.columns:
                field_df["order_as_of_date"] = field_df["order_as_of_date"].astype(str)
                daily_for_date = field_df[field_df["order_as_of_date"] == date_str]

                if not daily_for_date.empty and "equ_ticker" in df_merged.columns:
                    # If wide format, melt to long
                    if "equ_ticker" not in daily_for_date.columns:
                        equity_cols = [c for c in daily_for_date.columns if c != "order_as_of_date"]
                        daily_for_date = daily_for_date.melt(
                            id_vars=["order_as_of_date"],
                            value_vars=equity_cols,
                            var_name="equ_ticker",
                            value_name=field_name,
                        )

                    df_merged = pd.merge(
                        df_merged,
                        daily_for_date[["order_as_of_date", "equ_ticker", field_name]],
                        on=["order_as_of_date", "equ_ticker"],
                        how="left",
                    )
                else:
                    df_merged[field_name] = np.nan
            else:
                df_merged[field_name] = np.nan
    else:
        df_merged["chg_pct_1d"] = np.nan
        df_merged["bid_ask_spread_%"] = np.nan

    # ── D. Rename columns for TCA output ──────────────────────────────────

    rename_map = {
        "FillShares": "fill_volume",
        "FillPrice": "fill_px",
    }
    existing_renames = {k: v for k, v in rename_map.items() if k in df_merged.columns}
    df_merged.rename(columns=existing_renames, inplace=True)

    # ── E. Compute derived metrics ────────────────────────────────────────

    _compute_derived_metrics(df_merged)

    # Filter out rows with zero fill volume
    if "fill_volume" in df_merged.columns:
        df_merged["fill_volume"] = pd.to_numeric(df_merged["fill_volume"], errors="coerce")
        df_merged = df_merged[df_merged["fill_volume"] > 0].copy()

    logger.info(f"Integrated fills+BDIB for {date_str}: {len(df_merged)} rows")
    return df_merged


def _compute_derived_metrics(df: pd.DataFrame) -> None:
    """Compute TCA derived metrics in place, grouped by OrderId."""
    # fill_value
    if "fill_volume" in df.columns and "fill_px" in df.columns:
        df["fill_volume"] = pd.to_numeric(df["fill_volume"], errors="coerce")
        df["fill_px"] = pd.to_numeric(df["fill_px"], errors="coerce")
        df["fill_value"] = df["fill_volume"] * df["fill_px"]
    else:
        df["fill_value"] = np.nan

    # side_sign
    if "Side" in df.columns:
        side_upper = df["Side"].astype(str).str.upper()
        conditions = [side_upper == "S", side_upper == "B"]
        choices = [1, -1]
        df["side_sign"] = np.select(conditions, choices, default=0)
    else:
        df["side_sign"] = 0

    # Sort for cumulative calculations
    sort_cols = []
    if "OrderId" in df.columns:
        sort_cols.append("OrderId")
    if "mkt_timestamp" in df.columns:
        sort_cols.append("mkt_timestamp")

    if not sort_cols:
        return

    df.sort_values(by=sort_cols, inplace=True)

    if "OrderId" not in df.columns:
        return

    g = df.groupby("OrderId")

    # Cumulative fill value
    if "fill_value" in df.columns:
        df["cum_fill_value"] = g["fill_value"].cumsum()

    # Cumulative fill volume
    if "fill_volume" in df.columns:
        df["cum_fill_volume"] = g["fill_volume"].cumsum()

    # Cumulative market volume
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        df["cum_volume"] = g["volume"].cumsum()
    else:
        df["cum_volume"] = 0

    # Cumulative market value
    if "value" in df.columns:
        df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0)
        df["cum_value"] = g["value"].cumsum()
    else:
        df["cum_value"] = 0

    # Market VWAP
    df["cum_vwap"] = np.where(
        df["cum_volume"] > 0,
        df["cum_value"] / df["cum_volume"],
        np.nan,
    )

    # Cumulative fill VWAP
    if "cum_fill_value" in df.columns and "cum_fill_volume" in df.columns:
        df["cum_fill_vwap"] = np.where(
            df["cum_fill_volume"] > 0,
            df["cum_fill_value"] / df["cum_fill_volume"],
            np.nan,
        )

    # Slippage metrics
    if all(c in df.columns for c in ["side_sign", "cum_fill_vwap", "cum_vwap"]):
        df["cum_slippage_bps"] = np.where(
            df["cum_vwap"].notna() & (df["cum_vwap"] != 0),
            df["side_sign"] * (df["cum_fill_vwap"] / df["cum_vwap"] - 1) * 10000,
            np.nan,
        )
        df["cum_tracking_error"] = g["cum_slippage_bps"].transform(
            lambda x: x.expanding().std()
        )
        df["cum_info_ratio"] = df["cum_slippage_bps"] / df["cum_tracking_error"]

    if all(c in df.columns for c in ["side_sign", "cum_fill_vwap", "cum_vwap", "cum_fill_volume"]):
        df["cum_slippage_value"] = np.where(
            df["cum_vwap"].notna(),
            df["side_sign"] * (df["cum_fill_vwap"] - df["cum_vwap"]) * df["cum_fill_volume"],
            np.nan,
        )

    if all(c in df.columns for c in ["cum_slippage_value", "fx_rate"]):
        df["cum_slippage_usd"] = np.where(
            df["fx_rate"].notna() & (df["fx_rate"] != 0),
            df["cum_slippage_value"] / df["fx_rate"],
            np.nan,
        )

    if all(c in df.columns for c in ["cum_fill_volume", "cum_volume"]):
        df["cum_volume_pct"] = np.where(
            df["cum_volume"] > 0,
            df["cum_fill_volume"] / df["cum_volume"] * 100,
            np.nan,
        )

    # Interval price change metrics
    if "log_chg_pct_10s" in df.columns:
        df["log_chg_pct_10s"] = pd.to_numeric(df["log_chg_pct_10s"], errors="coerce").fillna(0)
        df["cum_interval_chg_pct"] = g["log_chg_pct_10s"].transform("cumsum")
        df["standard_cum_interval_chg_pct"] = (
            g["log_chg_pct_10s"].transform("cumsum")
            / (g["log_chg_pct_10s"].transform("cumcount") + 1)
        )
        df["cum_interval_volatility"] = g["log_chg_pct_10s"].transform(
            lambda x: (x**2).cumsum()
        )
        df["standard_cum_interval_volatility"] = (
            g["log_chg_pct_10s"].transform(lambda x: (x**2).cumsum())
            / (g["log_chg_pct_10s"].transform("cumcount") + 1)
        )

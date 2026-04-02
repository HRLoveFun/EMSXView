"""
Fill Aggregator — 10-second and 1-minute aggregation of processed EMSX fills.

Adapted from D:\\Evaluation\\src\\trading_data_processing\\fill.py:
  - _generate_agg_processed_fills()  → generate_agg_fills_10s()
  - 1-minute version                 → generate_agg_fills_1min()

All functions use EMSX column names:
  - OrderId (not "Order Number")
  - FillShares (not "Exec Last Fill")
  - FillPrice (not "Exec Last Fill Px")
  - StrategyType (not "Strategy Type")
  - route_as_of_time (lowercase derived column)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)


def _unique_or_mult(x: pd.Series):
    """Return unique value or 'Mult' if multiple distinct values."""
    u = x.unique()
    return u[0] if len(u) == 1 else "Mult"


def generate_agg_fills_10s(processed_df: pd.DataFrame) -> pd.DataFrame:
    """Generate 10-second aggregated fills.

    Groups by (OrderId, mkt_timestamp), computes VWAP for FillPrice,
    sums FillShares, applies unique_or_mult for categorical columns,
    and fills missing 10s intervals with 0 fills.
    """
    if processed_df.empty:
        return pd.DataFrame()

    # Aggregation rules for EMSX columns
    agg_rules: Dict[str, any] = {}

    unique_cols = [
        "Ticker", "equ_ticker", "Exchange", "Amount", "Side", "Currency", "region",
        "order_as_of_date", "route_as_of_time",
        "Broker", "StrategyType", "algo", "TraderName",
        "ccy_ticker", "is_closing_auction",
        "RouteShares",
    ]
    for col in unique_cols:
        if col in processed_df.columns:
            agg_rules[col] = _unique_or_mult

    # Sum for fill quantity
    if "FillShares" in processed_df.columns:
        agg_rules["FillShares"] = "sum"

    # Group by OrderId and mkt_timestamp
    res = processed_df.groupby(["OrderId", "mkt_timestamp"]).agg(agg_rules)
    res = res.reset_index()

    # VWAP for FillPrice
    if "FillPrice" in processed_df.columns and "FillShares" in processed_df.columns:
        processed_df = processed_df.copy()
        processed_df["_exec_val"] = processed_df["FillPrice"].astype(float) * processed_df["FillShares"].astype(float)

        g_sum = processed_df.groupby(["OrderId", "mkt_timestamp"])[
            ["_exec_val", "FillShares"]
        ].sum()

        vwap_series = g_sum["_exec_val"] / g_sum["FillShares"].replace(0, np.nan)
        vwap_df = vwap_series.reset_index(name="FillPrice")

        res = pd.merge(res, vwap_df, on=["OrderId", "mkt_timestamp"], how="left")

    # Fill missing 10-second intervals within each order's trading range
    if "OrderId" in res.columns and "mkt_timestamp" in res.columns:
        mkt_ts = pd.to_datetime(
            res["mkt_timestamp"].astype(str), format="%H:%M:%S", errors="coerce"
        )
        if mkt_ts.notna().any():
            res = res.copy()
            res["_mkt_ts"] = mkt_ts

            def _complete_intervals(order_df: pd.DataFrame) -> pd.DataFrame:
                order_df = order_df.sort_values("_mkt_ts")
                valid_ts = order_df["_mkt_ts"].dropna()
                if valid_ts.empty:
                    return order_df.drop(columns=["_mkt_ts"], errors="ignore")

                full_idx = pd.date_range(
                    start=valid_ts.min(), end=valid_ts.max(), freq="10s"
                )
                original_idx = order_df["_mkt_ts"].tolist()
                inserted_mask = ~full_idx.isin(original_idx)

                expanded = order_df.set_index("_mkt_ts").reindex(full_idx)
                expanded.index.name = "_mkt_ts"
                expanded = expanded.reset_index()

                # Forward-fill categorical columns, keep fill columns 0 for inserted rows
                cols_to_ffill = [
                    c for c in expanded.columns
                    if c not in {"FillShares", "FillPrice", "mkt_timestamp"}
                ]
                if cols_to_ffill:
                    expanded[cols_to_ffill] = expanded[cols_to_ffill].ffill().infer_objects(copy=False)

                expanded["mkt_timestamp"] = pd.to_datetime(
                    expanded["_mkt_ts"]
                ).dt.strftime("%H:%M:%S")

                if "FillShares" in expanded.columns:
                    expanded.loc[inserted_mask, "FillShares"] = 0
                if "FillPrice" in expanded.columns:
                    expanded.loc[inserted_mask, "FillPrice"] = 0

                return expanded.drop(columns=["_mkt_ts"], errors="ignore")

            res = (
                res.groupby("OrderId", group_keys=False)[res.columns]
                .apply(_complete_intervals)
            )

    # Ensure string columns don't have mixed types
    for col in res.columns:
        if res[col].dtype == "object":
            try:
                res[col] = res[col].astype(str)
            except Exception:
                pass

    logger.info(f"Generated 10s aggregation: {len(res)} rows")
    return res


def generate_agg_fills_1min(agg_10s_df: pd.DataFrame) -> pd.DataFrame:
    """Generate 1-minute aggregated fills from 10-second aggregated fills.

    Floors mkt_timestamp to 1min, then applies similar VWAP/sum aggregation.
    """
    if agg_10s_df.empty:
        return pd.DataFrame()

    df = agg_10s_df.copy()

    # Floor mkt_timestamp to 1min
    mkt_ts = pd.to_datetime(
        df["mkt_timestamp"].astype(str), format="%H:%M:%S", errors="coerce"
    )
    df["mkt_timestamp_1min"] = mkt_ts.dt.floor("1min").dt.strftime("%H:%M:%S")

    # Aggregation rules
    agg_rules: Dict[str, any] = {}
    unique_cols = [
        "Ticker", "equ_ticker", "Exchange", "Amount", "Side", "Currency", "region",
        "order_as_of_date", "route_as_of_time",
        "Broker", "StrategyType", "algo", "TraderName",
        "ccy_ticker", "is_closing_auction",
        "RouteShares",
    ]
    for col in unique_cols:
        if col in df.columns:
            agg_rules[col] = _unique_or_mult

    if "FillShares" in df.columns:
        agg_rules["FillShares"] = "sum"

    res = df.groupby(["OrderId", "mkt_timestamp_1min"]).agg(agg_rules)
    res = res.reset_index()

    # VWAP for FillPrice
    if "FillPrice" in df.columns and "FillShares" in df.columns:
        df["_exec_val"] = df["FillPrice"].astype(float) * df["FillShares"].astype(float)
        g_sum = df.groupby(["OrderId", "mkt_timestamp_1min"])[
            ["_exec_val", "FillShares"]
        ].sum()
        vwap_series = g_sum["_exec_val"] / g_sum["FillShares"].replace(0, np.nan)
        vwap_df = vwap_series.reset_index(name="FillPrice")
        res = pd.merge(res, vwap_df, on=["OrderId", "mkt_timestamp_1min"], how="left")

    # Add mkt_timestamp as alias for 1min
    res["mkt_timestamp"] = res["mkt_timestamp_1min"]

    logger.info(f"Generated 1min aggregation: {len(res)} rows")
    return res

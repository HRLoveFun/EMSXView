"""
Fill Aggregator — route-level 10-second aggregation of processed fills.

Aggregation level changed from order-level to route-level:
    Old: GROUP BY (OrderId, mkt_timestamp)
    New: GROUP BY (OrderId, RouteId, mkt_timestamp)

This enables per-route TCA analysis when combined with BDIB market data.

Active function:
    generate_agg_fills_10s() — used by pipeline.py run_aggregate()

Deprecated functions (not called by current pipeline):
    generate_agg_fills_1min() — 1-minute aggregation disabled in v3 to reduce
        storage overhead. Function body retained for future re-enablement or
        manual ad-hoc use via processed_fills_db.upsert_agg_fills_1min().

"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from DataPipeline.config import Config

logger = logging.getLogger(__name__)

def _unique_or_mult(x: pd.Series):
    """Return unique value or 'Mult' if multiple distinct values."""
    u = x.unique()
    return u[0] if len(u) == 1 else "Mult"

def generate_agg_fills_10s(processed_df: pd.DataFrame) -> pd.DataFrame:
    """Generate route-level 10-second aggregated fills.

    Groups by (OrderId, RouteId, mkt_timestamp), computes VWAP for FillPrice,
    sums FillShares, applies unique_or_mult for categorical columns,
    and fills missing 10s intervals with 0 fills per (OrderId, RouteId).
    """
    if processed_df.empty:
        return pd.DataFrame()

    agg_rules: Dict[str, any] = {}

    unique_cols = [
        "Ticker", "equ_ticker", "Exchange", "Amount", "Side", "Currency", "region",
        "order_as_of_date", "route_as_of_time",
        "Broker", "StrategyType", "algo", "TraderName",
        "ccy_ticker", "is_closing_auction",
        "RouteShares", "ExecType", "DateTimeOfFill",
    ]
    for col in unique_cols:
        if col in processed_df.columns:
            agg_rules[col] = _unique_or_mult

    if "FillShares" in processed_df.columns:
        agg_rules["FillShares"] = "sum"

    # Route-level groupby: (OrderId, RouteId, mkt_timestamp)
    res = processed_df.groupby(["OrderId", "RouteId", "mkt_timestamp"]).agg(agg_rules)
    res = res.reset_index()

    # VWAP for FillPrice
    if "FillPrice" in processed_df.columns and "FillShares" in processed_df.columns:
        processed_df = processed_df.copy()
        processed_df["_exec_val"] = (
            processed_df["FillPrice"].astype(float)
            * processed_df["FillShares"].astype(float)
        )

        g_sum = processed_df.groupby(["OrderId", "RouteId", "mkt_timestamp"])[
            ["_exec_val", "FillShares"]
        ].sum()

        vwap_series = g_sum["_exec_val"] / g_sum["FillShares"].replace(0, np.nan)
        vwap_df = vwap_series.reset_index(name="FillPrice")

        res = pd.merge(res, vwap_df, on=["OrderId", "RouteId", "mkt_timestamp"], how="left")

    # 间歇填充已移除 (v4.0-p1a) — 见 fill_bdib_comprehensive_fix
    # _complete_route_intervals() 生成的填充行上:
    #   - fill_volume=0 在 fill_bdib_integrated 中被过滤, 从未持久化
    #   - LEFT JOIN BDIB 获取的市场数据有效但未利用
    #   - 衍生指标 (vwap_slippage_bps ≈ -10000 bps) 为垃圾值
    #   - 同时此逻辑是 processed_fills.db 膨胀 6.5x (23GB vs 3.5GB) 的主因

    # Ensure string columns don't have mixed types
    for col in res.columns:
        if res[col].dtype == "object":
            try:
                res[col] = res[col].astype(str)
            except Exception:
                pass

    logger.info(f"Generated route-level 10s aggregation: {len(res)} rows")
    return res

def generate_agg_fills_1min(agg_10s_df: pd.DataFrame) -> pd.DataFrame:
    """Generate route-level 1-minute aggregated fills from 10-second data.

    Floors mkt_timestamp to 1min, then aggregates by (OrderId, RouteId, mkt_timestamp_1min).
    """
    if agg_10s_df.empty:
        return pd.DataFrame()

    df = agg_10s_df.copy()

    # Floor mkt_timestamp to 1min
    ts = pd.to_datetime(df["mkt_timestamp"].astype(str), format="%H:%M:%S", errors="coerce")
    df["mkt_timestamp_1min"] = ts.dt.floor("1min").dt.strftime("%H:%M:%S")

    agg_rules: Dict[str, any] = {}
    for col in [
        "Ticker", "equ_ticker", "Exchange", "Amount", "Side", "Currency", "region",
        "order_as_of_date", "route_as_of_time",
        "Broker", "StrategyType", "algo", "TraderName",
        "ccy_ticker", "is_closing_auction",
        "RouteShares", "ExecType",
    ]:
        if col in df.columns:
            agg_rules[col] = _unique_or_mult

    if "FillShares" in df.columns:
        agg_rules["FillShares"] = "sum"

    res = df.groupby(
        ["OrderId", "RouteId", "mkt_timestamp_1min"]
    ).agg(agg_rules).reset_index()
    res.rename(columns={"mkt_timestamp_1min": "mkt_timestamp"}, inplace=True)

    # VWAP
    if "FillPrice" in df.columns and "FillShares" in df.columns:
        df["_exec_val"] = df["FillPrice"].astype(float) * df["FillShares"].astype(float)
        g_sum = df.groupby(["OrderId", "RouteId", "mkt_timestamp_1min"])[
            ["_exec_val", "FillShares"]
        ].sum()
        vwap_series = g_sum["_exec_val"] / g_sum["FillShares"].replace(0, np.nan)
        vwap_df = vwap_series.reset_index(name="FillPrice")
        vwap_df.rename(columns={"mkt_timestamp_1min": "mkt_timestamp"}, inplace=True)
        res = pd.merge(
            res, vwap_df,
            on=["OrderId", "RouteId", "mkt_timestamp"],
            how="left",
        )

    logger.info(f"Generated 1min aggregation: {len(res)} rows")
    return res

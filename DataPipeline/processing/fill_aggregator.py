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

def _load_route_registry_for_routes(processed_df: pd.DataFrame) -> pd.DataFrame:
    """从 route_registry 加载指定路由的静态属性。

    只读取 processed_df 中存在的 (OrderId, RouteId) 组合，避免加载全表。
    """
    from DataPipeline.storage.facade import DatabaseFacade

    unique_routes = processed_df[["OrderId", "RouteId"]].drop_duplicates()
    if unique_routes.empty:
        return pd.DataFrame()

    db = DatabaseFacade()
    conn = db.fills_read._conn_for("route_registry")
    try:
        # route_registry 表通常较小，直接读取全表后按路由过滤
        route_registry = pd.read_sql_query(
            "SELECT OrderId, RouteId, equ_ticker, Side, ccy_ticker, Exchange FROM route_registry",
            conn.raw_connection,
        )
    finally:
        conn.close()

    if route_registry.empty:
        return pd.DataFrame()

    return route_registry.merge(unique_routes, on=["OrderId", "RouteId"], how="inner")


def _enrich_from_route_registry(processed_df: pd.DataFrame) -> pd.DataFrame:
    """在聚合前从 route_registry 补全 Ticker/Side/Currency/ccy_ticker。

    processed_fills 的 schema 已将这四列去冗余，但 agg_fills_10s 的 schema
    仍需要它们。参考 v_processed_fills_legacy 视图的实现，从 route_registry
    的 equ_ticker / ccy_ticker 推导 Ticker / Currency，Side 与 ccy_ticker 直接取。
    """
    enriched_cols = ["Ticker", "Side", "Currency", "ccy_ticker"]
    missing_cols: List[str] = []
    for col in enriched_cols:
        if col not in processed_df.columns:
            missing_cols.append(col)
        elif processed_df[col].isna().all():
            missing_cols.append(col)
            processed_df = processed_df.drop(columns=[col])

    if not missing_cols:
        return processed_df

    registry_df = _load_route_registry_for_routes(processed_df)
    if registry_df.empty:
        logger.warning(
            "route_registry 为空，无法补全 %s 列；下游 BDIB/TCA 可能缺少这些字段",
            missing_cols,
        )
        return processed_df

    registry_df = registry_df.copy()
    # 从 equ_ticker 提取 Ticker（取空格前第一段）
    registry_df["Ticker"] = registry_df["equ_ticker"].astype(str).str.split(" ").str[0]
    # 从 ccy_ticker 提取 Currency（如 "USD Curncy" -> "USD"；"USDJPY Curncy" -> "USD"）
    registry_df["Currency"] = (
        registry_df["ccy_ticker"]
        .astype(str)
        .str.replace(" Curncy", "", regex=False)
        .str[:3]
    )

    merge_cols = ["OrderId", "RouteId"] + [c for c in enriched_cols if c in registry_df.columns]
    processed_df = processed_df.merge(
        registry_df[merge_cols], on=["OrderId", "RouteId"], how="left"
    )
    return processed_df


def generate_agg_fills_10s(processed_df: pd.DataFrame, *, route_registry_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Generate route-level 10-second aggregated fills.

    Groups by (OrderId, RouteId, mkt_timestamp), computes VWAP for FillPrice,
    sums FillShares, applies unique_or_mult for categorical columns,
    and fills missing 10s intervals with 0 fills per (OrderId, RouteId).
    """
    if processed_df.empty:
        return pd.DataFrame()

    # S3 列补全：processed_fills 已去冗余存储 Ticker/Side/Currency/ccy_ticker，
    # 聚合前从 route_registry 补回，与 v_processed_fills_legacy 视图保持一致。
    if route_registry_df is not None:
        registry_df = route_registry_df.copy()
        registry_df["Ticker"] = registry_df["equ_ticker"].astype(str).str.split(" ").str[0]
        registry_df["Currency"] = (
            registry_df["ccy_ticker"]
            .astype(str)
            .str.replace(" Curncy", "", regex=False)
            .str[:3]
        )
        merge_cols = ["OrderId", "RouteId", "Ticker", "Side", "Currency", "ccy_ticker"]
        processed_df = processed_df.merge(
            registry_df[[c for c in merge_cols if c in registry_df.columns]],
            on=["OrderId", "RouteId"],
            how="left",
        )
    else:
        processed_df = _enrich_from_route_registry(processed_df)

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

    # VWAP for FillPrice：过滤零股记录，避免 FillShares=0 产生 NaN FillPrice
    if "FillPrice" in processed_df.columns and "FillShares" in processed_df.columns:
        processed_df = processed_df.copy()
        shares_numeric = pd.to_numeric(processed_df["FillShares"], errors="coerce").fillna(0)
        price_numeric = pd.to_numeric(processed_df["FillPrice"], errors="coerce")
        # 仅正股数参与 VWAP 计算；零股不贡献 exec_val
        processed_df["_exec_val"] = np.where(
            shares_numeric > 0,
            price_numeric * shares_numeric,
            0,
        )

        g_sum = processed_df.groupby(["OrderId", "RouteId", "mkt_timestamp"])[
            ["_exec_val", "FillShares"]
        ].sum()

        # 仅当 FillShares 总和 > 0 时产生 VWAP，否则丢弃该聚合行（无成交量）
        valid_vwap = g_sum["FillShares"] > 0
        vwap_series = g_sum.loc[valid_vwap, "_exec_val"] / g_sum.loc[valid_vwap, "FillShares"]
        vwap_df = vwap_series.reset_index(name="FillPrice")

        res = pd.merge(res, vwap_df, on=["OrderId", "RouteId", "mkt_timestamp"], how="left")
        # 丢弃因无成交量而无法计算 FillPrice 的聚合行
        res = res[res["FillPrice"].notna()].copy()

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

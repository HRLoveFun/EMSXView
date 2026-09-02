"""
Column definitions for CostView database tables.

Single source of truth for all column definitions used across the
database subsystem.

``AGG_COLUMNS`` and ``AGG_1MIN_COLUMNS`` live here (not in the
processed_fills schema module) because they are also referenced by
aggregation queries in the ingestion pipeline.
"""

from __future__ import annotations

from typing import Dict, List

# Raw fill columns — keep FILL_FIELD_EXTRACTORS in fill_fetch.py in sync.

EMSX_FILL_COLUMNS: List[str] = [
    "OrderId", "Account", "SecurityName", "Ticker", "Exchange",
    "Currency", "Side", "Amount", "NyOrderCreateAsOfDateTime",
    "Type", "LimitPrice", "Broker", "StopPrice", "StrategyType",
    "TraderName", "TraderUuid", "RouteId", "NyTranCreateAsOfDateTime",
    "RouteShares", "FillId", "ExecType", "DateTimeOfFill",
    "FillPrice", "FillShares", "LastCapacity", "LastMarket",
    "Liquidity", "LocalExchangeSymbol",
]

DERIVED_COLUMNS: List[str] = [
    "order_as_of_date", "exchange_exec_time",
]

ALL_RAW_COLUMNS: List[str] = EMSX_FILL_COLUMNS + DERIVED_COLUMNS

RAW_METADATA_COLUMNS: List[str] = ["source_date", "fetched_at"]

EXECUTION_HISTORY_SOURCE_COLUMNS: List[str] = [
    "primary_source", "source_priority", "refresh_strategy",
    "source_refreshed_at", "source_lineage",
]

PROCESSED_COLUMNS: List[str] = [
    "FillId", "OrderId", "RouteId", "mkt_timestamp",
    "order_as_of_date", "local_fill_datetime", "exchange_exec_time",
    "route_as_of_time", "DateTimeOfFill", "Broker", "StrategyType",
    "algo", "TraderName", "Exchange", "Amount", "RouteShares",
    "is_closing_auction", "ExecType", "region", "equ_ticker",
    "FillPrice", "FillShares",
    # 007-costview-report-filters: 成交币种 → USD 汇率（USD per 1 单位本币）
    "fx_rate",
]

ROUTE_REGISTRY_COLUMNS: List[str] = [
    "OrderId", "RouteId", "equ_ticker", "Exchange", "ccy_ticker",
    "Side", "count_fill", "count_broker", "count_algo", "count_trader",
]

ORDER_HISTORY_COLUMNS: List[str] = [
    "OrderId", "order_as_of_date", "equ_ticker", "ccy_ticker",
    "Side", "Broker", "algo", "TraderName", "Exchange",
    "route_count", "fill_count", "total_fill_shares",
    "order_amount", "average_fill_price", "first_fill_time",
    "last_fill_time",
] + EXECUTION_HISTORY_SOURCE_COLUMNS

ROUTE_HISTORY_COLUMNS: List[str] = [
    "OrderId", "RouteId", "order_as_of_date", "equ_ticker",
    "ccy_ticker", "Side", "Broker", "algo", "TraderName", "Exchange",
    "fill_count", "total_fill_shares", "order_amount", "route_shares",
    "average_fill_price", "first_fill_time", "last_fill_time",
] + EXECUTION_HISTORY_SOURCE_COLUMNS

ROUTE_EVENT_HISTORY_COLUMNS: List[str] = [
    "event_id", "OrderId", "RouteId", "FillId", "order_as_of_date",
    "event_timestamp", "event_type", "event_source", "event_action",
    "ExecType", "Broker", "algo", "TraderName", "Exchange",
    "equ_ticker", "ccy_ticker", "Side", "FillPrice", "FillShares",
    "Amount", "RouteShares", "source_refreshed_at",
    "refresh_strategy", "source_lineage",
]

COLUMN_TYPE_MAP: Dict[str, str] = {
    "FillPrice": "REAL", "FillShares": "REAL", "Amount": "REAL",
    "RouteShares": "REAL", "is_closing_auction": "INTEGER",
    "LimitPrice": "REAL", "StopPrice": "REAL",
    "count_fill": "INTEGER", "count_broker": "INTEGER",
    "count_algo": "INTEGER", "count_trader": "INTEGER",
    "fill_count": "INTEGER",
    "route_count": "INTEGER", "fill_count": "INTEGER",
    "total_fill_shares": "REAL", "order_amount": "REAL",
    "average_fill_price": "REAL",
    # 007-costview-report-filters: USD per 1 单位本币（成交金额换算用）
    "fx_rate": "REAL",
    # fx-rate-persistence: Bloomberg 原始逆报价（fx_rates 表审计双存）
    "px_last": "REAL",
    # tca_route_summary 数值列
    "fill": "REAL", "fill_continuous": "REAL", "fill_close": "REAL",
    "par_rate": "REAL", "par_rate_continuous": "REAL", "par_rate_close": "REAL",
    "p_avg": "REAL", "p_avg_continuous": "REAL",
    "pnl_vwap": "REAL", "pnl_vwap_continuous": "REAL",
    "RPM": "REAL", "RPM_continuous": "REAL",
    "pwp_5": "REAL", "pwp_10": "REAL", "pwp_15": "REAL", "pwp_20": "REAL", "pwp_25": "REAL",
    # 003-tca-core-benchmarks: Phase 0 核心基准
    "p_arrival": "REAL", "p_close": "REAL",
    "arrival_cost_bps": "REAL", "close_cost_bps": "REAL",
    "opportunity_cost": "REAL",
    # 003-tca-core-benchmarks: Phase 1 Wagner IS / 风险 / 冲击
    "p_decision": "REAL", "delay_cost": "REAL", "trading_cost": "REAL",
    "wagner_is": "REAL", "wagner_is_bps": "REAL",
    "cost_stddev": "REAL", "cost_p95": "REAL", "cost_cvar": "REAL",
    "order_duration_sec": "REAL", "exec_rate_shares_per_min": "REAL",
    "temp_impact_5min_bps": "REAL", "temp_impact_10min_bps": "REAL",
    "temp_impact_30min_bps": "REAL", "perm_impact_bps": "REAL",
    "recovery_truncated": "INTEGER",
}

AGG_COLUMNS: List[str] = [
    "OrderId", "RouteId", "mkt_timestamp", "order_as_of_date",
    "Ticker", "equ_ticker", "Exchange", "Amount", "Side", "Currency",
    "region", "Broker", "StrategyType", "algo", "TraderName",
    "ccy_ticker", "is_closing_auction", "RouteShares",
    "route_as_of_time", "ExecType", "DateTimeOfFill",
    "FillPrice", "FillShares",
]

TCA_ROUTE_SUMMARY_COLUMNS: List[str] = [
    # 源值字段（17）
    "OrderId", "RouteId", "order_as_of_date", "Exchange", "Account",
    "equ_ticker", "Currency", "Side", "Amount", "RouteShares",
    "Type", "LimitPrice", "StopPrice", "Broker", "StrategyType",
    "algo", "TraderName",
    # 计算指标（18）：fill_count 为该路由下 FillId 的去重计数
    "fill_count", "fill", "fill_continuous", "fill_close",
    "par_rate", "par_rate_continuous", "par_rate_close",
    "p_avg", "p_avg_continuous",
    "pnl_vwap", "pnl_vwap_continuous",
    "RPM", "RPM_continuous",
    "pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25",
    # 003-tca-core-benchmarks: Phase 0 核心基准（到达价/收盘价/机会成本）
    "p_arrival", "p_close", "arrival_cost_bps", "close_cost_bps",
    "opportunity_cost",
    # 003-tca-core-benchmarks: Phase 1 Wagner IS / 风险 / 冲击分解
    "p_decision", "delay_cost", "trading_cost", "wagner_is", "wagner_is_bps",
    "cost_stddev", "cost_p95", "cost_cvar",
    "order_duration_sec", "exec_rate_shares_per_min",
    "temp_impact_5min_bps", "temp_impact_10min_bps", "temp_impact_30min_bps",
    "perm_impact_bps", "recovery_truncated",
    # 007-costview-report-filters: 路由级 USD 汇率（成交金额换算）
    "fx_rate",
]

# 003-tca-core-benchmarks: Phase 0 新列（核心基准）
TCA_CORE_BENCHMARKS_COLUMNS: List[str] = [
    "p_arrival", "p_close", "arrival_cost_bps", "close_cost_bps",
    "opportunity_cost",
]

# 003-tca-core-benchmarks: Phase 1 新列（Wagner IS / 风险 / 冲击）
TCA_RISK_IMPACT_COLUMNS: List[str] = [
    "p_decision", "delay_cost", "trading_cost", "wagner_is", "wagner_is_bps",
    "cost_stddev", "cost_p95", "cost_cvar",
    "order_duration_sec", "exec_rate_shares_per_min",
    "temp_impact_5min_bps", "temp_impact_10min_bps", "temp_impact_30min_bps",
    "perm_impact_bps", "recovery_truncated",
]

# fx-rate-persistence: fx_rates 表列（fill_bdib.db，币种 × 交易日汇率唯一真相源）
# ccy_ticker 规范化大写（如 'USDJPY Curncy'）；fx_rate = USD per 1 单位本币；
# px_last 为 Bloomberg 原始逆报价（审计/精度双存）；source 区分 'bloomberg' 拉取
# 与 'fill_bdib_seed' 历史反推。
FX_RATES_COLUMNS: List[str] = [
    "ccy_ticker", "order_as_of_date", "fx_rate",
    "px_last", "source", "fetched_at",
]

AGG_1MIN_COLUMNS: List[str] = [
    "OrderId", "RouteId", "mkt_timestamp_1min", "order_as_of_date",
    "Ticker", "equ_ticker", "Exchange", "Amount", "Side", "Currency",
    "region", "Broker", "StrategyType", "algo", "TraderName",
    "ccy_ticker", "is_closing_auction", "RouteShares",
    "route_as_of_time", "ExecType", "DateTimeOfFill",
    "FillPrice", "FillShares",
]

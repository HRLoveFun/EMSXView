"""Column definitions for CostView database tables.

Migrated from CostView/src/schema.py. This is the single source of truth
for all column definitions used across the database subsystem.
"""

from __future__ import annotations

from typing import Dict, List

# ── Raw fill columns (authoritative list) ──────────────────────────────

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
    "order_as_of_date", "order_as_of_time", "exchange_exec_time",
    "route_as_of_time", "local_fill_datetime",
]

ALL_RAW_COLUMNS: List[str] = EMSX_FILL_COLUMNS + DERIVED_COLUMNS

RAW_METADATA_COLUMNS: List[str] = ["source_date", "fetched_at"]

EXECUTION_HISTORY_SOURCE_COLUMNS: List[str] = [
    "primary_source", "source_priority", "refresh_strategy",
    "source_refreshed_at", "source_lineage",
]

# ── processed_fills table ──────────────────────────────────────────────

PROCESSED_COLUMNS: List[str] = [
    "FillId", "OrderId", "RouteId", "mkt_timestamp",
    "order_as_of_date", "local_fill_datetime", "exchange_exec_time",
    "route_as_of_time", "DateTimeOfFill", "Broker", "StrategyType",
    "algo", "TraderName", "Exchange", "Amount", "RouteShares",
    "is_closing_auction", "ExecType", "region", "FillPrice", "FillShares",
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
    "count_fill": "INTEGER", "count_broker": "INTEGER",
    "count_algo": "INTEGER", "count_trader": "INTEGER",
    "route_count": "INTEGER", "fill_count": "INTEGER",
    "total_fill_shares": "REAL", "order_amount": "REAL",
    "average_fill_price": "REAL",
}

AGG_COLUMNS: List[str] = [
    "OrderId", "RouteId", "mkt_timestamp", "order_as_of_date",
    "Ticker", "equ_ticker", "Exchange", "Amount", "Side", "Currency",
    "region", "Broker", "StrategyType", "algo", "TraderName",
    "ccy_ticker", "is_closing_auction", "RouteShares",
    "route_as_of_time", "ExecType", "DateTimeOfFill",
    "FillPrice", "FillShares",
]

AGG_1MIN_COLUMNS: List[str] = [
    "OrderId", "RouteId", "mkt_timestamp_1min", "order_as_of_date",
    "Ticker", "equ_ticker", "Exchange", "Amount", "Side", "Currency",
    "region", "Broker", "StrategyType", "algo", "TraderName",
    "ccy_ticker", "is_closing_auction", "RouteShares",
    "route_as_of_time", "ExecType", "DateTimeOfFill",
    "FillPrice", "FillShares",
]

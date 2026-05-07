"""
EMSX Fill Data Schema — Single source of truth for column definitions.

Dependency direction:
    schema.py  <--  fill_fetch.py  (fetch layer uses schema)
    schema.py  <--  fill_cleaner.py (cleaning layer uses schema)
    schema.py  <--  raw_fills_db.py (storage layer uses schema)
"""

from __future__ import annotations

from typing import Dict, List


# ── Raw fill columns (authoritative list) ──────────────────────────────────
# These are the columns fetched from Bloomberg EMSX History API.
# fill_fetch.py FILL_FIELD_EXTRACTORS must keep keys in sync with this list.

EMSX_FILL_COLUMNS: List[str] = [
    "OrderId",
    "Account",
    "SecurityName",
    "Ticker",
    "Exchange",
    "Currency",
    "Side",
    "Amount",
    "NyOrderCreateAsOfDateTime",
    "Type",
    "LimitPrice",
    "Broker",
    "StopPrice",
    "StrategyType",
    "TraderName",
    "TraderUuid",
    "RouteId",
    "NyTranCreateAsOfDateTime",
    "RouteShares",
    "FillId",
    "ExecType",
    "DateTimeOfFill",
    "FillPrice",
    "FillShares",
    "LastCapacity",
    "LastMarket",
    "Liquidity",
    "LocalExchangeSymbol",
]


# ── Derived columns (added during cleaning) ────────────────────────────────

DERIVED_COLUMNS: List[str] = [
    "order_as_of_date",       # YYYYMMDD, from DateTimeOfFill -> local exchange date
    "order_as_of_time",       # HH:MM:SS, from NyOrderCreateAsOfDateTime -> local exchange time
    "exchange_exec_time",     # HH:MM:SS, from DateTimeOfFill -> local exchange time
    "route_as_of_time",       # HH:MM:SS, from NyTranCreateAsOfDateTime -> local exchange time
    "local_fill_datetime",    # Full local datetime string, from DateTimeOfFill
]


# ── All columns stored in raw_fills DB ─────────────────────────────────────

ALL_RAW_COLUMNS: List[str] = EMSX_FILL_COLUMNS + DERIVED_COLUMNS


# ── Metadata columns (added by fetch layer) ────────────────────────────────

RAW_METADATA_COLUMNS: List[str] = [
    "source_date",            # YYYYMMDD, the date the API was called for
    "fetched_at",             # ISO timestamp, when the data was fetched
]


EXECUTION_HISTORY_SOURCE_COLUMNS: List[str] = [
    "primary_source",
    "source_priority",
    "refresh_strategy",
    "source_refreshed_at",
    "source_lineage",
]


# ── processed_fills table (Schema V2) ──────────────────────────────────────
# Stored in PROCESSED_FILLS_DB. Fact table containing dynamic attributes.
# Join with route_registry for static attributes and aggregate summaries.

PROCESSED_COLUMNS: List[str] = [
    # Primary key
    "FillId",
    # Foreign keys to route_registry
    "OrderId",
    "RouteId",
    # Partition & time keys
    "mkt_timestamp",
    "order_as_of_date",
    "local_fill_datetime",
    "exchange_exec_time",
    "route_as_of_time",
    "DateTimeOfFill",
    # Dynamic context fields
    "Broker",
    "StrategyType",
    "algo",
    "TraderName",
    "Exchange",
    "Amount",
    "RouteShares",
    "is_closing_auction",
    "ExecType",
    "region",
    # Numeric columns
    "FillPrice",
    "FillShares",
]

# ── route_registry table (Schema V2) ───────────────────────────────────────
# Dimension table containing static order/route attributes and summaries.

ROUTE_REGISTRY_COLUMNS: List[str] = [
    "OrderId",
    "RouteId",
    "equ_ticker",
    "Exchange",
    "ccy_ticker",
    "Side",
    "count_fill",
    "count_broker",
    "count_algo",
    "count_trader",
]


ORDER_HISTORY_COLUMNS: List[str] = [
    "OrderId",
    "order_as_of_date",
    "equ_ticker",
    "ccy_ticker",
    "Side",
    "Broker",
    "algo",
    "TraderName",
    "Exchange",
    "route_count",
    "fill_count",
    "total_fill_shares",
    "order_amount",
    "average_fill_price",
    "first_fill_time",
    "last_fill_time",
] + EXECUTION_HISTORY_SOURCE_COLUMNS


ROUTE_HISTORY_COLUMNS: List[str] = [
    "OrderId",
    "RouteId",
    "order_as_of_date",
    "equ_ticker",
    "ccy_ticker",
    "Side",
    "Broker",
    "algo",
    "TraderName",
    "Exchange",
    "fill_count",
    "total_fill_shares",
    "order_amount",
    "route_shares",
    "average_fill_price",
    "first_fill_time",
    "last_fill_time",
] + EXECUTION_HISTORY_SOURCE_COLUMNS


ROUTE_EVENT_HISTORY_COLUMNS: List[str] = [
    "event_id",
    "OrderId",
    "RouteId",
    "FillId",
    "order_as_of_date",
    "event_timestamp",
    "event_type",
    "event_source",
    "event_action",
    "ExecType",
    "Broker",
    "algo",
    "TraderName",
    "Exchange",
    "equ_ticker",
    "ccy_ticker",
    "Side",
    "FillPrice",
    "FillShares",
    "Amount",
    "RouteShares",
    "source_refreshed_at",
    "refresh_strategy",
    "source_lineage",
]

# ── Column type map for processed_fills and agg tables ─────────────────────
# Only columns listed here use non-TEXT types; all others default to TEXT.

COLUMN_TYPE_MAP: Dict[str, str] = {
    "FillPrice": "REAL",
    "FillShares": "REAL",
    "Amount": "REAL",
    "RouteShares": "REAL",
    "is_closing_auction": "INTEGER",
    "count_fill": "INTEGER",
    "count_broker": "INTEGER",
    "count_algo": "INTEGER",
    "count_trader": "INTEGER",
    "route_count": "INTEGER",
    "fill_count": "INTEGER",
    "total_fill_shares": "REAL",
    "order_amount": "REAL",
    "average_fill_price": "REAL",
}


# ── Aggregation table columns (route-level, ~23 columns) ──────────────────
# agg_fills_10s (ACTIVE) and agg_fills_1min (DEPRECATED in v3) share this schema.

AGG_COLUMNS: List[str] = [
    # Primary key
    "OrderId",
    "RouteId",
    "mkt_timestamp",
    "order_as_of_date",
    # _unique_or_mult columns
    "Ticker",
    "equ_ticker",
    "Exchange",
    "Amount",
    "Side",
    "Currency",
    "region",
    "Broker",
    "StrategyType",
    "algo",
    "TraderName",
    "ccy_ticker",
    "is_closing_auction",
    "RouteShares",
    "route_as_of_time",
    "ExecType",
    "DateTimeOfFill",
    # Numeric columns
    "FillPrice",
    "FillShares",
]

# 1min aggregation table uses mkt_timestamp_1min instead of mkt_timestamp

AGG_1MIN_COLUMNS: List[str] = [
    "OrderId",
    "RouteId",
    "mkt_timestamp_1min",
    "order_as_of_date",
    "Ticker",
    "equ_ticker",
    "Exchange",
    "Amount",
    "Side",
    "Currency",
    "region",
    "Broker",
    "StrategyType",
    "algo",
    "TraderName",
    "ccy_ticker",
    "is_closing_auction",
    "RouteShares",
    "route_as_of_time",
    "ExecType",
    "DateTimeOfFill",
    "FillPrice",
    "FillShares",
]

"""
EMSX Fill Data Schema.

Defines the EMSX raw fill column schema, column derivation rules,
deduplication keys, and EMSX-to-Evaluation column name references.
"""

from __future__ import annotations

from typing import Dict, List


# ── Active EMSX Fill Columns (from FILL_FIELD_EXTRACTORS in fill_fetch.py) ──
# These are the columns fetched from Bloomberg EMSX History API.

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
    "OrderInstruction",
    "IsLeg",
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
    "RouteExecutionInstruction",
    "RouteHandlingInstruction",
    "RouteNotes",
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
# These are computed from the raw EMSX columns.

DERIVED_COLUMNS: List[str] = [
    "order_as_of_date",       # YYYYMMDD, from NyOrderCreateAsOfDateTime
    "order_as_of_time",       # HH:MM:SS, from NyOrderCreateAsOfDateTime
    "exec_date",              # YYYYMMDD, from DateTimeOfFill (NY time, then local exchange)
    "exec_time",              # HH:MM:SS, from DateTimeOfFill (NY time)
    "exchange_exec_time",     # HH:MM:SS, from DateTimeOfFill → local exchange time
    "route_as_of_time",       # HH:MM:SS, from NyTranCreateAsOfDateTime
    "local_fill_datetime",    # Full local datetime string, from DateTimeOfFill
]


# ── Deduplication key ──────────────────────────────────────────────────────
# Each fill in EMSX is uniquely identified by (OrderId, FillId).

EMSX_DEDUP_KEY: List[str] = ["OrderId", "FillId"]


# ── Processing-added columns (added during fill processing) ────────────────
# These are computed from the cleaned data during transformation.

PROCESSING_COLUMNS: List[str] = [
    "algo",                   # Algorithm classification (vwap/twap/pov/close/other)
    "ccy_ticker",             # Bloomberg currency ticker (e.g. "USDJPY Curncy")
    "region",                 # Geographic region (APAC/EMEA/NSA)
    "equ_ticker",             # Bloomberg equity ticker (e.g. "7203 JP Equity")
    "mkt_timestamp",          # Market timestamp, 10-second floor (HH:MM:SS)
    "is_closing_auction",     # Whether fill is during closing auction
    "route_mkt_timestamp",    # Route adjusted market timestamp
]


# ── EMSX column → Evaluation column reference ──────────────────────────────
# For documentation only. Processing functions use EMSX column names directly.
# This mapping documents the semantic equivalence for cross-referencing.

EMSX_TO_EVALUATION_MAP: Dict[str, str] = {
    # EMSX Column             Evaluation Column
    "OrderId":                "Order Number",
    "Ticker":                 "Ticker",
    "Exchange":               "Exchange",
    "SecurityName":           "Security Name",
    "Currency":               "Currency",
    "Side":                   "Side",
    "Amount":                 "Amount",
    "Broker":                 "Broker",
    "StrategyType":           "Strategy Type",
    "TraderName":             "Trader Name",
    "FillPrice":              "Exec Last Fill Px",
    "FillShares":             "Exec Last Fill",
    "ExecType":               "Exec Type",
    "LastMarket":             "Last Market",
    "Liquidity":              "Liquidity",
    "RouteShares":            "Routed Amount",
    # Derived columns
    "order_as_of_date":       "Order As of Date",
    "exec_date":              "Exec Date",
    "exec_time":              "Exec Time",
    "exchange_exec_time":     "Exchange Exec Time",
    "route_as_of_time":       "Route As of Time",
}


# ── Columns only in Evaluation (not in EMSX) ──────────────────────────────
# These columns exist in Evaluation raw fills but do NOT have EMSX equivalents.
# They are NOT fabricated; processing functions are adapted to work without them.

EVALUATION_ONLY_COLUMNS: List[str] = [
    "Order Type",
    "Tran Type",
    "Tran Account",
    "Order Entry Time",
    "Fill Amount",           # Cumulative fill amount (EMSX only has per-fill FillShares)
    "Average Price",         # Avg fill price (can be computed from fills)
    "Day Avg Price",         # Day-level average
    "Exec Avg Price",        # Execution average
    "Exec Seq Number",
    "Exec Prev Seq Number",
]


# ── Columns only in EMSX (not in Evaluation) ──────────────────────────────
# These EMSX-specific columns are preserved in storage but not used by
# Evaluation-derived processing functions.

EMSX_ONLY_COLUMNS: List[str] = [
    "Account",
    "NyOrderCreateAsOfDateTime",
    "OrderInstruction",
    "IsLeg",
    "Type",
    "LimitPrice",
    "StopPrice",
    "TraderUuid",
    "RouteId",
    "NyTranCreateAsOfDateTime",
    "RouteExecutionInstruction",
    "RouteHandlingInstruction",
    "RouteNotes",
    "FillId",
    "LastCapacity",
    "LocalExchangeSymbol",
]

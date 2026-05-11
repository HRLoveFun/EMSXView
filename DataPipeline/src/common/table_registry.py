"""Centralized table name registry — single source of truth for all EMSX database table names.

All modules SHOULD import table names from this module.
Direct string literals in SQL are forbidden outside repository implementations.

This module is the first point of reference when adding or renaming tables.
Only one constant per table — no duplication across modules.
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════
# Database keys (used by ConnectionManager and cross-DB references)
# ═══════════════════════════════════════════════════════════════════════════

DB_RAW_FILLS = "raw_fills"
DB_PROCESSED_FILLS = "processed_fills"
DB_RAW_BDIB = "raw_bdib"
DB_PROCESSED_RAW_BDIB = "processed_raw_bdib"
DB_FILL_BDIB = "fill_bdib"
DB_REGIME = "regime"
DB_FETCH_HISTORY = "fill_fetch_history"

# ═══════════════════════════════════════════════════════════════════════════
# Table names — alphabetized for easy scanning
# ═══════════════════════════════════════════════════════════════════════════

AGG_10S_TABLE = "agg_fills_10s"
AGG_1MIN_TABLE = "agg_fills_1min"
AGG_PROCESSED_FILLS_TABLE = "agg_processed_fills"
BDIB_DAILY_SUMMARY_TABLE = "bdib_daily_summary"
CCY_TICKER_REGISTRY_TABLE = "ccy_ticker_registry"
EQU_TICKER_REGISTRY_TABLE = "equ_ticker_registry"
FETCH_HISTORY_TABLE = "fill_fetch_history"
FETCH_LOG_TABLE = "fetch_log"
FILL_BDIB_TABLE = "fill_bdib"
INGESTION_LOG_TABLE = "ingestion_log"
ORDER_FETCH_LOG_TABLE = "order_fetch_log"
ORDER_HISTORY_TABLE = "order_history"
ORDER_LABEL_TABLE = "order_label"
PROCESSED_FILLS_1MIN_TABLE = "processed_fills_1min"
PROCESSED_FILLS_TABLE = "processed_fills"
PROCESSED_RAW_BDIB_TABLE = "processed_raw_bdib"
PROCESSING_LOG_TABLE = "processing_log"
RAW_BDIB_TABLE = "raw_bdib"
RAW_FILLS_TABLE = "raw_fills"
ROUTE_EVENT_HISTORY_TABLE = "route_event_history"
ROUTE_HISTORY_TABLE = "route_history"
TICKER_DATE_MAPPING_TABLE = "ticker_date_mapping"

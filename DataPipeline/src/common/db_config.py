"""Database configuration — paths, table names, and DB keys."""

from __future__ import annotations

from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE KEYS (used by ConnectionManager)
# ═══════════════════════════════════════════════════════════════════════════

DB_RAW_FILLS = "raw_fills"
DB_PROCESSED_FILLS = "processed_fills"
DB_RAW_BDIB = "raw_bdib"
DB_PROCESSED_RAW_BDIB = "processed_raw_bdib"
DB_FILL_BDIB = "fill_bdib"
DB_REGIME = "regime"
DB_FETCH_HISTORY = "fill_fetch_history"


# ═══════════════════════════════════════════════════════════════════════════
# TABLE NAMES (module-level constants for direct import)
# ═══════════════════════════════════════════════════════════════════════════

RAW_FILLS_TABLE = "raw_fills"
PROCESSED_FILLS_TABLE = "processed_fills"
AGG_10S_TABLE = "agg_fills_10s"
AGG_1MIN_TABLE = "agg_fills_1min"
ORDER_HISTORY_TABLE = "order_history"
ROUTE_HISTORY_TABLE = "route_history"
ROUTE_EVENT_HISTORY_TABLE = "route_event_history"
RAW_BDIB_TABLE = "raw_bdib"
PROCESSED_RAW_BDIB_TABLE = "processed_raw_bdib"
FILL_BDIB_TABLE = "fill_bdib"
BDIB_DAILY_SUMMARY_TABLE = "bdib_daily_summary"
AGG_PROCESSED_FILLS_TABLE = "agg_processed_fills"
PROCESSED_FILLS_1MIN_TABLE = "processed_fills_1min"
ORDER_LABEL_TABLE = "order_label"
PROCESSING_LOG_TABLE = "processing_log"
TICKER_DATE_MAPPING_TABLE = "ticker_date_mapping"
EQU_TICKER_REGISTRY_TABLE = "equ_ticker_registry"
CCY_TICKER_REGISTRY_TABLE = "ccy_ticker_registry"
ORDER_FETCH_LOG_TABLE = "order_fetch_log"
FETCH_LOG_TABLE = "fetch_log"
INGESTION_LOG_TABLE = "ingestion_log"
FETCH_HISTORY_TABLE = "fill_fetch_history"


class DatabaseConfig:
    _PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

    DATA_DIR: Path = _PROJECT_ROOT / "CostView" / "data"
    LOGGING_DIR: Path = _PROJECT_ROOT / "CostView" / "logs"
    RAW_EXCEL_DIR: Path = DATA_DIR / "fills"

    FETCH_HISTORY_DB: Path = DATA_DIR / "fill_fetch_history.db"
    RAW_FILLS_DB: Path = DATA_DIR / "raw_fills.db"
    PROCESSED_FILLS_DB: Path = DATA_DIR / "processed_fills.db"
    RAW_BDIB_DB: Path = DATA_DIR / "raw_bdib.db"
    PROCESSED_RAW_BDIB_DB: Path = DATA_DIR / "processed_raw_bdib.db"
    FILL_BDIB_DB: Path = DATA_DIR / "fill_bdib.db"
    PROCESSED_BDIB_DB: Path = DATA_DIR / "fill_bdib.db"

    LOG_FILE: Path = LOGGING_DIR / "fillfetch.log"
    LOG_DEBUG_FILE: Path = LOGGING_DIR / "fillfetch_debug.log"
    MARKET_FETCH_MANIFEST: Path = DATA_DIR / "market_fetch_manifest.json"
    OUTDATED_TICKERS_FILE: Path = DATA_DIR / "outdated_tickers.json"

    RAW_FILLS_TABLE: str = "raw_fills"
    PROCESSED_FILLS_TABLE: str = "processed_fills"
    AGG_10S_TABLE: str = "agg_fills_10s"
    AGG_1MIN_TABLE: str = "agg_fills_1min"
    ORDER_HISTORY_TABLE: str = "order_history"
    ROUTE_HISTORY_TABLE: str = "route_history"
    ROUTE_EVENT_HISTORY_TABLE: str = "route_event_history"
    RAW_BDIB_TABLE: str = "raw_bdib"
    BDIB_DAILY_SUMMARY_TABLE: str = "bdib_daily_summary"
    PROCESSED_RAW_BDIB_TABLE: str = "processed_raw_bdib"
    FILL_BDIB_TABLE: str = "fill_bdib"
    PROCESSED_BDIB_TABLE: str = "fill_bdib"
    AGG_PROCESSED_FILLS_TABLE: str = "agg_processed_fills"
    PROCESSED_FILLS_1MIN_TABLE: str = "processed_fills_1min"
    ORDER_LABEL_TABLE: str = "order_label"
    PROCESSING_LOG_TABLE: str = "processing_log"
    TICKER_DATE_MAPPING_TABLE: str = "ticker_date_mapping"
    EQU_TICKER_REGISTRY_TABLE: str = "equ_ticker_registry"
    CCY_TICKER_REGISTRY_TABLE: str = "ccy_ticker_registry"
    ORDER_FETCH_LOG_TABLE: str = "order_fetch_log"
    FETCH_LOG_TABLE: str = "fetch_log"
    INGESTION_LOG_TABLE: str = "ingestion_log"
    FETCH_HISTORY_TABLE: str = "fill_fetch_history"

"""
Centralized processing configuration for the EMSX fill data pipeline.

All directory paths, database locations, format strings, and processing
parameters are defined here. Modelled after D:\\Evaluation\\src\\trading_data_processing\\config.py.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np


class ProcessingConfig:
    """
    Centralized configuration for the EMSX fill data processing pipeline.
    """

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 1: BASE DIRECTORIES
    # ═══════════════════════════════════════════════════════════════════════

    ROOT_DIR: Path = Path(__file__).resolve().parents[1]              # CostView/
    DATA_DIR: Path = ROOT_DIR / "data"
    LOGGING_DIR: Path = ROOT_DIR / "logs"

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 2: RAW DATA
    # ═══════════════════════════════════════════════════════════════════════

    # [DEPRECATED] Excel files from legacy FillFetch output.
    # No longer used since fill_fetch.py writes directly to raw_fills.db via Bloomberg API.
    # Directory reference kept for backward-compat of ingest_excel_file().
    RAW_EXCEL_DIR: Path = DATA_DIR / "fills"

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 3: SQLITE DATABASES
    # ═══════════════════════════════════════════════════════════════════════

    # Existing fetch-tracking database (from FillFetch)
    FETCH_HISTORY_DB: Path = DATA_DIR / "fill_fetch_history.db"

    # Raw fills database — cleaned EMSX fills with derived columns
    RAW_FILLS_DB: Path = DATA_DIR / "raw_fills.db"

    # Processed fills database — transformed fills + aggregations + order labels
    PROCESSED_FILLS_DB: Path = DATA_DIR / "processed_fills.db"

    # ── BDIB data pipeline (3-layer architecture, matches D:\\Evaluation convention) ──
    #
    # Layer 1: raw_bdib — Bloomberg-native OHLC/volume/num_trds/value only
    RAW_BDIB_DB: Path = DATA_DIR / "raw_bdib.db"
    # Layer 2: processed_raw_bdib — raw_bdib + derived (vwap, fluctuation, log_chg_pct_10s)
    PROCESSED_RAW_BDIB_DB: Path = DATA_DIR / "processed_raw_bdib.db"
    # Layer 3: fill_bdib — fills + processed_bdib integration + TCA metrics
    FILL_BDIB_DB: Path = DATA_DIR / "fill_bdib.db"
    # Legacy alias for fill_bdib.db (backward compatibility)
    PROCESSED_BDIB_DB: Path = DATA_DIR / "fill_bdib.db"


    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 4: DATE & TIME FORMATS
    # ═══════════════════════════════════════════════════════════════════════

    DATE_FORMAT: str = "%Y%m%d"                         # YYYYMMDD
    DATE_FORMAT_DASH: str = "%Y-%m-%d"                  # YYYY-MM-DD
    TIME_FORMAT: str = "%H:%M:%S"                       # HH:MM:SS
    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"          # Combined

    # EMSX DateTimeOfFill format (NY time with offset)
    # Example: "2026-03-27 14:30:45.123456-04:00" or "2026-03-27T14:30:45"
    EMSX_DATETIME_FORMATS: list = [
        "%Y-%m-%d %H:%M:%S.%f%z",     # With microseconds and TZ offset
        "%Y-%m-%dT%H:%M:%S.%f%z",     # ISO format with microseconds
        "%Y-%m-%d %H:%M:%S%z",        # Without microseconds, with offset
        "%Y-%m-%dT%H:%M:%S%z",        # ISO without microseconds
        "%Y-%m-%d %H:%M:%S.%f",       # Without TZ offset
        "%Y-%m-%dT%H:%M:%S.%f",       # ISO without TZ offset
        "%Y-%m-%d %H:%M:%S",          # Plain datetime
        "%Y-%m-%dT%H:%M:%S",          # ISO plain datetime
    ]

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 5: PROCESSING PARAMETERS
    # ═══════════════════════════════════════════════════════════════════════

    # [UNUSED] These legacy config values are kept for reference only.
    # They are NOT referenced anywhere in the current codebase.
    # Actual batch sizes are controlled per-module:
    #   - fill_fetch.py:       date batching via --batch-size flag (parallel mode only)
    #   - fill_processor.py:   EUR ticker resolution chunk_size=100 (xbbg blp.bdp)
    #   - raw_fills_db.py:     executememany (full day per transaction)
    CHUNKSIZE: int = 100_000                            # [UNUSED] Legacy row-chunk size
    BATCH_SIZE: int = 1_000                              # [UNUSED] Legacy API batch size
    FLOAT_TYPE: type = np.float32
    INT_TYPE: type = np.int32

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 6: SQLITE TABLE NAMES
    # ═══════════════════════════════════════════════════════════════════════

    # Tables in RAW_FILLS_DB
    RAW_FILLS_TABLE: str = "raw_fills"
    INGESTION_LOG_TABLE: str = "ingestion_log"          # deprecated, kept for compat
    FETCH_LOG_TABLE: str = "fetch_log"                  # unified fetch tracking

    # Tables in PROCESSED_FILLS_DB
    PROCESSED_FILLS_TABLE: str = "processed_fills"
    AGG_10S_TABLE: str = "agg_fills_10s"                # route-level 10s aggregation
    AGG_1MIN_TABLE: str = "agg_fills_1min"              # route-level 1min aggregation

    # Tables in RAW_BDIB_DB / PROCESSED_RAW_BDIB_DB / FILL_BDIB_DB (3-layer BDIB pipeline)
    RAW_BDIB_TABLE: str = "raw_bdib"
    BDIB_DAILY_SUMMARY_TABLE: str = "bdib_daily_summary"     # Bloomberg daily summary + intraday carry-over metrics
    PROCESSED_RAW_BDIB_TABLE: str = "processed_raw_bdib"      # Layer 2: raw + derived
    FILL_BDIB_TABLE: str = "fill_bdib"                       # Layer 3: fills + BDIB + TCA
    PROCESSED_BDIB_TABLE: str = "fill_bdib"                   # legacy alias → fill_bdib_table

    # Legacy table names (deprecated, kept for migration)
    AGG_PROCESSED_FILLS_TABLE: str = "agg_processed_fills"
    PROCESSED_FILLS_1MIN_TABLE: str = "processed_fills_1min"
    ORDER_LABEL_TABLE: str = "order_label"
    PROCESSING_LOG_TABLE: str = "processing_log"
    TICKER_DATE_MAPPING_TABLE: str = "ticker_date_mapping"

    # Tables for downstream ticker registries (Phase 4)
    EQU_TICKER_REGISTRY_TABLE: str = "equ_ticker_registry"
    CCY_TICKER_REGISTRY_TABLE: str = "ccy_ticker_registry"

    # Table for order-level fetch tracking (Phase 2B)
    ORDER_FETCH_LOG_TABLE: str = "order_fetch_log"

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 6a: CLEANING PARAMETERS
    # ═══════════════════════════════════════════════════════════════════════

    # ExecType values to filter OUT (not actual fills)
    EXECTYPE_FILTER_OUT: set = {"DFD"}  # Done For Day

    # First-run lookback days (calendar days, not trading days)
    FIRST_RUN_LOOKBACK_DAYS: int = 60

    # Raw BDIB ticker filter whitelist by exchange code (from ticker_repository).
    # Example: ["US", "JP", "LN"]
    BDID_EXCHANGE: list[str] = ["AU", "AV", "BB", "FH", "FP", "GA", "GR", "ID", "IJ", "IM", "IN", "JP", "KS", "LN", "MK", 'NA', "NO", "PL", "SJ", "SM", "SP", "SS", "SW", "US"]

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 6a2: PARALLELIZATION PARAMETERS
    # ═══════════════════════════════════════════════════════════════════════

    # Max threads for date-level parallelism in S2 (ProcessRawFills) and S3 (AggregateFills).
    # Each thread uses its own DB connection. Set to 1 to disable parallelism.
    MAX_PARALLEL_DATES: int = 4

    # Max threads for ticker-level parallelism in S5 (IntegrateBDIB).
    # Bloomberg API session limit is ~3 concurrent requests.
    MAX_PARALLEL_TICKERS: int = 3

    # SQLite busy handling for concurrent pipeline stages.
    SQLITE_CONNECT_TIMEOUT_SEC: int = 30
    SQLITE_BUSY_TIMEOUT_MS: int = 30_000

    # Latest prior trading day becomes eligible for BDIB fetches only after this
    # local hour on the following calendar day. Before that, the pipeline uses
    # the previous safe trading day to avoid xbbg near-real-time warnings.
    BDIB_LATEST_READY_HOUR_LOCAL: int = 18

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 6b: LOGGING PARAMETERS
    # ═══════════════════════════════════════════════════════════════════════

    LOG_FILE: Path = LOGGING_DIR / "fillfetch.log"
    LOG_DEBUG_FILE: Path = LOGGING_DIR / "fillfetch_debug.log"
    LOG_RETENTION_DAYS: int = 30
    LOG_DEBUG_RETENTION_DAYS: int = 7
    LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 6c: DOWNSTREAM INTERFACE
    # ═══════════════════════════════════════════════════════════════════════

    MARKET_FETCH_MANIFEST: Path = DATA_DIR / "market_fetch_manifest.json"
    OUTDATED_TICKERS_FILE: Path = DATA_DIR / "outdated_tickers.json"

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 7: UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def initialize_directories(cls) -> None:
        """Create all required directories if they don't exist.

        Note: RAW_EXCEL_DIR (data/fills/) is intentionally excluded here
        since Excel-based ingest has been deprecated. The directory will only
        be created on-demand if ingest_excel_file() or ingest_all_excel_files()
        is explicitly called.
        """
        directories = [
            cls.DATA_DIR,
            cls.LOGGING_DIR,
            # RAW_EXCEL_DIR intentionally omitted — DEPRECATED, create on-demand only
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

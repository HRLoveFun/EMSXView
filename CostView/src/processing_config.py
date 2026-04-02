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

    # Excel files from FillFetch (existing location)
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

    CHUNKSIZE: int = 100_000                            # Rows per chunk
    BATCH_SIZE: int = 1_000                             # Batch size for API calls
    FLOAT_TYPE: type = np.float32
    INT_TYPE: type = np.int32

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 6: SQLITE TABLE NAMES
    # ═══════════════════════════════════════════════════════════════════════

    # Tables in RAW_FILLS_DB
    RAW_FILLS_TABLE: str = "raw_fills"
    INGESTION_LOG_TABLE: str = "ingestion_log"

    # Tables in PROCESSED_FILLS_DB
    PROCESSED_FILLS_TABLE: str = "processed_fills"
    AGG_PROCESSED_FILLS_TABLE: str = "agg_processed_fills"
    PROCESSED_FILLS_1MIN_TABLE: str = "processed_fills_1min"
    ORDER_LABEL_TABLE: str = "order_label"
    PROCESSING_LOG_TABLE: str = "processing_log"
    TICKER_DATE_MAPPING_TABLE: str = "ticker_date_mapping"

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 7: UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def initialize_directories(cls) -> None:
        """Create all required directories if they don't exist."""
        directories = [
            cls.DATA_DIR,
            cls.RAW_EXCEL_DIR,
            cls.LOGGING_DIR,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

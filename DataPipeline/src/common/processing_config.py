"""
Centralized processing configuration for the EMSX fill data pipeline.

**P2b refactoring**: The monolithic ProcessingConfig has been split into
dedicated sub-modules under ``config/``:

    - ``config/paths.py`` (PathsConfig)    — all file/directory paths
    - ``config/defaults.py`` (DefaultsConfig) — formats, parameters & policies

``ProcessingConfig`` now inherits from both, preserving full backward
compatibility for all existing importers.

New code SHOULD import directly from the split modules::

    from DataPipeline.src.common.config.paths import PathsConfig
    from DataPipeline.src.common.config.defaults import DefaultsConfig

Legacy import (still works)::

    from DataPipeline.src.common.processing_config import ProcessingConfig as Config
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from DataPipeline.src.common.config.paths import PathsConfig
from DataPipeline.src.common.config.defaults import DefaultsConfig

from . import table_registry  # noqa: F401 — exported for convenience

# Re-export DB key constants for convenience
DB_RAW_FILLS = table_registry.DB_RAW_FILLS
DB_PROCESSED_FILLS = table_registry.DB_PROCESSED_FILLS
DB_RAW_BDIB = table_registry.DB_RAW_BDIB
DB_PROCESSED_RAW_BDIB = table_registry.DB_PROCESSED_RAW_BDIB
DB_FILL_BDIB = table_registry.DB_FILL_BDIB
DB_REGIME = table_registry.DB_REGIME
DB_FETCH_HISTORY = table_registry.DB_FETCH_HISTORY


class ProcessingConfig(PathsConfig, DefaultsConfig):
    """
    Centralized configuration for the EMSX fill data processing pipeline.

    Backward-compatible facade inheriting from:
        - ``PathsConfig``    — file/directory paths
        - ``DefaultsConfig`` — format strings, processing parameters & policies

    Supports both static (class-level) and instance access.

    Static usage (legacy)::
        from ...processing_config import ProcessingConfig as Config
        path = Config.RAW_FILLS_DB

    Instance usage (new, allows overrides for testing)::
        config = ProcessingConfig(DATA_DIR=Path("/tmp/custom"))
        assert config.DATA_DIR == Path("/tmp/custom")

    Instance attributes take precedence over class defaults.
    Table name constants are sourced from ``table_registry`` and re-exported
    as class-level attributes for backward compatibility.
    """

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 6: SQLITE TABLE NAMES
    # ═══════════════════════════════════════════════════════════════════════
    #
    # Table names now reference the centralized table_registry module.
    # Direct string literals are defined only in table_registry.py.

    # Tables in RAW_FILLS_DB
    RAW_FILLS_TABLE: str = table_registry.RAW_FILLS_TABLE
    INGESTION_LOG_TABLE: str = table_registry.INGESTION_LOG_TABLE
    FETCH_LOG_TABLE: str = table_registry.FETCH_LOG_TABLE

    # Tables in PROCESSED_FILLS_DB
    PROCESSED_FILLS_TABLE: str = table_registry.PROCESSED_FILLS_TABLE
    AGG_10S_TABLE: str = table_registry.AGG_10S_TABLE
    AGG_1MIN_TABLE: str = table_registry.AGG_1MIN_TABLE
    ORDER_HISTORY_TABLE: str = table_registry.ORDER_HISTORY_TABLE
    ROUTE_HISTORY_TABLE: str = table_registry.ROUTE_HISTORY_TABLE
    ROUTE_EVENT_HISTORY_TABLE: str = table_registry.ROUTE_EVENT_HISTORY_TABLE

    # Tables in RAW_BDIB_DB / PROCESSED_RAW_BDIB_DB / FILL_BDIB_DB
    RAW_BDIB_TABLE: str = table_registry.RAW_BDIB_TABLE
    BDIB_DAILY_SUMMARY_TABLE: str = table_registry.BDIB_DAILY_SUMMARY_TABLE
    PROCESSED_RAW_BDIB_TABLE: str = table_registry.PROCESSED_RAW_BDIB_TABLE
    FILL_BDIB_TABLE: str = table_registry.FILL_BDIB_TABLE
    PROCESSED_BDIB_TABLE: str = table_registry.FILL_BDIB_TABLE  # legacy alias

    # Legacy table names
    AGG_PROCESSED_FILLS_TABLE: str = table_registry.AGG_PROCESSED_FILLS_TABLE
    PROCESSED_FILLS_1MIN_TABLE: str = table_registry.PROCESSED_FILLS_1MIN_TABLE
    ORDER_LABEL_TABLE: str = table_registry.ORDER_LABEL_TABLE
    PROCESSING_LOG_TABLE: str = table_registry.PROCESSING_LOG_TABLE
    TICKER_DATE_MAPPING_TABLE: str = table_registry.TICKER_DATE_MAPPING_TABLE

    # Tables for downstream ticker registries
    EQU_TICKER_REGISTRY_TABLE: str = table_registry.EQU_TICKER_REGISTRY_TABLE
    CCY_TICKER_REGISTRY_TABLE: str = table_registry.CCY_TICKER_REGISTRY_TABLE

    # Table for order-level fetch tracking
    ORDER_FETCH_LOG_TABLE: str = table_registry.ORDER_FETCH_LOG_TABLE

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 7: UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════

    def __init__(self, **overrides: Any) -> None:
        """Instance constructor with optional path overrides.

        Usage::

            # Override DATA_DIR for testing
            config = ProcessingConfig(DATA_DIR=Path("/tmp/test_data"))

            # Override a single DB path
            config = ProcessingConfig(RAW_FILLS_DB=Path("/tmp/test/raw_fills.db"))

        Only class-level attributes that are Path instances (or other simple types)
        may be overridden. Table name constants are immutable and always resolved
        from the class default (which sources from ``table_registry``).

        When an override is set, the instance stores it. Instance attribute access
        is handled by ``__getattribute__`` which checks instance dict first, then
        falls back to the class default.
        """
        for key, value in overrides.items():
            if not hasattr(self.__class__, key):
                raise AttributeError(
                    f"{self.__class__.__name__} has no attribute {key!r}"
                )
            object.__setattr__(self, key, value)

    # ── Instance attribute resolution ────────────────────────────────────────

    def __getattribute__(self, name: str) -> Any:
        """Instance attribute takes precedence over class default.

        This enables::

            config = ProcessingConfig(DATA_DIR=Path("/custom"))
            config.DATA_DIR  # → /custom
            ProcessingConfig.DATA_DIR  # → /original (unchanged)
        """
        try:
            return super().__getattribute__(name)
        except AttributeError:
            return getattr(self.__class__, name)

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

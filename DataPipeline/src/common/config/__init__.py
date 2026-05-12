"""Unified configuration — single source of truth for all EMSX pipeline config.

Usage::

    from DataPipeline.src.common.config import Config

    path = Config.RAW_FILLS_DB
    date_fmt = Config.DATE_FORMAT
    table = Config.PROCESSED_FILLS_TABLE
"""

from __future__ import annotations

from typing import Any

from DataPipeline.src.common.db_config import (  # noqa: F401
    DB_FETCH_HISTORY,
    DB_FILL_BDIB,
    DB_PROCESSED_FILLS,
    DB_PROCESSED_RAW_BDIB,
    DB_RAW_BDIB,
    DB_RAW_FILLS,
    DB_REGIME,
    AGG_10S_TABLE,
    AGG_1MIN_TABLE,
    AGG_PROCESSED_FILLS_TABLE,
    BDIB_DAILY_SUMMARY_TABLE,
    CCY_TICKER_REGISTRY_TABLE,
    EQU_TICKER_REGISTRY_TABLE,
    FETCH_HISTORY_TABLE,
    FETCH_LOG_TABLE,
    FILL_BDIB_TABLE,
    INGESTION_LOG_TABLE,
    ORDER_FETCH_LOG_TABLE,
    ORDER_HISTORY_TABLE,
    ORDER_LABEL_TABLE,
    PROCESSED_FILLS_1MIN_TABLE,
    PROCESSED_FILLS_TABLE,
    PROCESSED_RAW_BDIB_TABLE,
    PROCESSING_LOG_TABLE,
    RAW_BDIB_TABLE,
    RAW_FILLS_TABLE,
    ROUTE_EVENT_HISTORY_TABLE,
    ROUTE_HISTORY_TABLE,
    TICKER_DATE_MAPPING_TABLE,
    DatabaseConfig,
)
from DataPipeline.src.common.processing_params import ProcessingConfig  # noqa: F401
from DataPipeline.src.common.log_config import LoggingConfig  # noqa: F401


class Config(DatabaseConfig, ProcessingConfig, LoggingConfig):
    """Unified EMSX pipeline configuration.

    Inherits from ``DatabaseConfig``, ``ProcessingConfig``, and ``LoggingConfig``.
    Supports static (``Config.XXX``) and instance (``Config(**overrides)``) access.
    """

    def __init__(self, **overrides: Any) -> None:
        for key, value in overrides.items():
            if not hasattr(self.__class__, key):
                raise AttributeError(f"{self.__class__.__name__} has no attribute {key!r}")
            object.__setattr__(self, key, value)

    def __getattribute__(self, name: str) -> Any:
        try:
            return super().__getattribute__(name)
        except AttributeError:
            return getattr(self.__class__, name)

    @classmethod
    def initialize_directories(cls) -> None:
        directories = [cls.DATA_DIR, cls.LOGGING_DIR]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

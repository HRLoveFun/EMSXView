"""
Processed Fills Database — modular repository package.

Provides domain-specific repositories for the processed_fills.db SQLite database.
The legacy ``ProcessedFillsDB`` class is preserved as a Facade that delegates
to the individual repositories for backward compatibility.

Usage (new code — prefer specific repositories):
    from processed_fills_db.fills_repository import ProcessedFillsRepository
    from processed_fills_db.aggregation_repository import AggregationRepository

Usage (legacy — still works):
    from processed_fills_db import ProcessedFillsDB
"""

from ._base import BaseProcessedFillsRepo, init_processed_fills_schema  # noqa: F401
from .aggregation_repository import AggregationRepository  # noqa: F401
from .execution_history_repository import ExecutionHistoryRepository  # noqa: F401
from .facade import ProcessedFillsDB  # noqa: F401 — backward-compatible entry point
from .fills_repository import ProcessedFillsRepository  # noqa: F401
from .legacy_repository import LegacyRepository  # noqa: F401
from .order_label_repository import OrderLabelRepository  # noqa: F401
from .processing_log_repository import ProcessingLogRepository  # noqa: F401
from .ticker_repository import TickerRepository  # noqa: F401

__all__ = [
    "ProcessedFillsDB",
    "BaseProcessedFillsRepo",
    "ProcessedFillsRepository",
    "AggregationRepository",
    "ExecutionHistoryRepository",
    "OrderLabelRepository",
    "ProcessingLogRepository",
    "TickerRepository",
    "LegacyRepository",
    "init_processed_fills_schema",
]
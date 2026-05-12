"""Schema management for CostView databases.

Provides centralized column definitions and migration management.
"""

from .columns import (  # noqa: F401
    AGG_1MIN_COLUMNS,
    AGG_COLUMNS,
    ALL_RAW_COLUMNS,
    COLUMN_TYPE_MAP,
    DERIVED_COLUMNS,
    EMSX_FILL_COLUMNS,
    EXECUTION_HISTORY_SOURCE_COLUMNS,
    ORDER_HISTORY_COLUMNS,
    PROCESSED_COLUMNS,
    RAW_METADATA_COLUMNS,
    ROUTE_EVENT_HISTORY_COLUMNS,
    ROUTE_HISTORY_COLUMNS,
    ROUTE_REGISTRY_COLUMNS,
)
from .migrations.manager import MigrationManager  # noqa: F401

__all__ = [
    "AGG_1MIN_COLUMNS",
    "AGG_COLUMNS",
    "ALL_RAW_COLUMNS",
    "COLUMN_TYPE_MAP",
    "DERIVED_COLUMNS",
    "EMSX_FILL_COLUMNS",
    "EXECUTION_HISTORY_SOURCE_COLUMNS",
    "ORDER_HISTORY_COLUMNS",
    "PROCESSED_COLUMNS",
    "RAW_METADATA_COLUMNS",
    "ROUTE_EVENT_HISTORY_COLUMNS",
    "ROUTE_HISTORY_COLUMNS",
    "ROUTE_REGISTRY_COLUMNS",
    "MigrationManager",
]

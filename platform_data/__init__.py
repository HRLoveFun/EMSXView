"""Canonical logical data-domain entry points for EMSX.

This package defines the shared adapter layer between:

- Execution operational persistence and warm-start data
- CostView analytical queries and reporting

The goal is to keep business domains separate while exposing one stable
integration surface for code that needs platform data access.
"""

from .adapters import (
    CostViewAnalyticsAdapter,
    ExecutionOperationalDataAdapter,
    MarketDailySnapshotRow,
    MarketReferenceDataAdapter,
    MarketSnapshot,
    PlatformDataAccess,
    TcaFilters,
    TcaReport,
    build_platform_data_access,
)

__all__ = [
    "CostViewAnalyticsAdapter",
    "ExecutionOperationalDataAdapter",
    "MarketDailySnapshotRow",
    "MarketReferenceDataAdapter",
    "MarketSnapshot",
    "PlatformDataAccess",
    "TcaFilters",
    "TcaReport",
    "build_platform_data_access",
]
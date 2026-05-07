"""Canonical logical data-domain entry points for EMSX.

This package exposes only the adapter layer — the stable integration surface
between business domains. Dataclass types (MarketSnapshot, TcaFilters, etc.)
are imported directly from platform_data.adapters.
"""

from .adapters import (
    build_platform_data_access,
    PlatformDataAccess,
    # Adapter classes
    CostViewAnalyticsAdapter,
    CostViewDatabaseAdapter,
    ExecutionHistoryAdapter,
    ExecutionOperationalDataAdapter,
    HandoffExchangeAdapter,
    MarketReferenceDataAdapter,
    # Singleton entry points
    get_shared_handoff_exchange,
)
from . import repositories  # noqa: F401 — used by DatabaseView router

__all__ = [
    "build_platform_data_access",
    "PlatformDataAccess",
    "CostViewAnalyticsAdapter",
    "CostViewDatabaseAdapter",
    "ExecutionHistoryAdapter",
    "ExecutionOperationalDataAdapter",
    "HandoffExchangeAdapter",
    "MarketReferenceDataAdapter",
    "get_shared_handoff_exchange",
    "repositories",
]
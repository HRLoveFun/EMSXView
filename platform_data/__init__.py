"""Canonical logical data-domain entry points for EMSX.

This package exposes only the adapter layer — the stable integration surface
between business domains. Dataclass types (MarketSnapshot, TcaFilters, etc.)
are imported directly from platform_data.adapters.
"""

from .adapters import (
    build_platform_data_access,
    PlatformDataAccess,
    CostViewAnalyticsAdapter,
    CostViewDatabaseAdapter,
    DataPlatformIngestionAdapter,
    ExecutionHistoryAdapter,
    ExecutionOperationalDataAdapter,
    HandoffExchangeAdapter,
    MarketReferenceDataAdapter,
    get_shared_handoff_exchange,
)
from . import repositories  # noqa: F401 — backward-compat bridge (deprecated); DatabaseView router imports database_diagnostics directly
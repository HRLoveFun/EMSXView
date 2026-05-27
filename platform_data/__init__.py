"""Canonical logical data-domain entry points for EMSX.

This package exposes the stable integration surface between business domains.
Dataclass types (MarketSnapshot, TcaFilters, etc.) are imported directly from
platform_data.adapters.
"""

from .adapters import (
    HandoffExchangeAdapter,
    MarketReferenceDataAdapter,
    get_shared_handoff_exchange,
)

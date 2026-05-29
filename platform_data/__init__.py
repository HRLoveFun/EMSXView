"""Canonical logical data-domain entry points for EMSX.

This package exposes the stable integration surface between business domains.
Dataclass types (MarketSnapshot, TcaFilters, etc.) are imported directly from
platform_data.adapters. Protocols for DataPipeline integration are in
platform_data.contracts.protocols.
"""

from .adapters import (
    HandoffExchangeAdapter,
    RedisHandoffExchangeAdapter,
    MarketReferenceDataAdapter,
    get_shared_handoff_exchange,
    get_tca_query_service,
)

from .contracts.protocols import (
    ConnectionManagerProtocol,
    ConfigProtocol,
)

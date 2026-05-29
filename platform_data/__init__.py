"""Canonical logical data-domain entry points for EMSX.

This package exposes the stable integration surface between business domains.
Dataclass types are in platform_data.contracts (pure data, no logic).
Adapters are in platform_data.adapters (adapters, factories, services).
Protocols for DataPipeline integration are in platform_data.contracts.protocols.
"""

from .adapters import (
    HandoffExchangeAdapter,
    RedisHandoffExchangeAdapter,
    MarketReferenceDataAdapter,
    get_shared_handoff_exchange,
    get_tca_query_service,
    register_tca_service_impl,
)

from .contracts.protocols import (
    ConnectionManagerProtocol,
    ConfigProtocol,
)

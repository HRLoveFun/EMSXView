"""Adapters subpackage — compatibility re-export entry point.

This module replaces the formerly monolithic ``platform_data/adapters.py``.
All functionality has been extracted into focused submodules:

- ``platform_data.adapters.tca_bridge``  — TCA query service factory
- ``platform_data.adapters.market``      — MarketReferenceDataAdapter
- ``platform_data.adapters.handoff``     — HandoffExchangeAdapter + singleton
- ``platform_data.adapters.redis_handoff`` — RedisHandoffExchangeAdapter

For backward compatibility, this __init__.py re-exports all public symbols
so existing ``from platform_data.adapters import X`` imports continue to work.

New code should import from the canonical submodule paths.
"""

from platform_data.adapters.market import (
    MarketReferenceDataAdapter,
    _DEFAULT_STOCK_POOLS,
    _liquidity_severity,
    _round_or_none,
    _severity_at_least,
    _sort_market_rows,
    _to_optional_float,
    _volatility_severity,
)

from platform_data.adapters.handoff import (
    HandoffExchangeAdapter,
    get_shared_handoff_exchange,
)

from platform_data.adapters.redis_handoff import (
    RedisHandoffExchangeAdapter,
)

from platform_data.adapters.tca_bridge import (
    get_tca_query_service,
    register_tca_service_impl,
    _ConnectionManagerDailySummaryReader,
)

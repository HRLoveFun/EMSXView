"""Adapters subpackage — adapter entry point.

This module replaces the formerly monolithic ``platform_data/adapters.py``.
All functionality has been extracted into focused submodules:

- ``platform_data.adapters.tca_bridge``  — TCA query service factory
- ``platform_data.adapters.market``      — MarketReferenceDataAdapter
- ``platform_data.adapters.handoff``     — HandoffExchangeAdapter + singleton
- ``platform_data.adapters.redis_handoff`` — RedisHandoffExchangeAdapter

本模块**只**暴露适配器与工厂函数，不再承担契约类型或私有符号的 re-export 职责：

- 跨模块数据类型一律从 ``platform_data.contracts`` 导入
  （见 docs/spec/module-api-contracts.md「跨域数据契约」规则）；
- ``market`` / ``tca_bridge`` 内的下划线私有符号属适配器内部实现，
  跨域**禁止**访问（见 .codebuddy/rules/module-boundary.md §2.3），
  故不在包入口暴露；模块内部需要时从 canonical 子模块路径导入。

2026-09-16 收敛：原 ``__init__.py`` 曾为「向后兼容」re-export 27 个契约类型
与 8 个私有符号，经双仓库 AST 核查确认其中契约类型仅有 2 个违规消费者
（已迁移至 ``platform_data.contracts``）、私有符号零消费者。实现本身全部保留，
仅收窄本模块公开面（42 → 7 个符号）。
"""

from platform_data.adapters.market import (
    MarketReferenceDataAdapter,
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
    register_costview_bridge_dependencies,
)

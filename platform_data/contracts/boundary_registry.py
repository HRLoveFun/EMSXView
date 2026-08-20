"""模块边界契约注册表 (P2, 2026-08-14)。

声明式登记每个模块的边界契约 — 可读数据域、可写数据域、禁止 import、
API 认证要求。检测工具 (审计脚本 / 边界测试) 从注册表**生成**检测规则,
新增模块只需追加一条注册, 无需修改任何检测代码。

与 ``.codebuddy/rules/module-boundary.md`` 的五元组规则同构:

    CAN / CANNOT / DETECT / TEST / RATIONALE

本模块承载 CAN/CANNOT 的**机器可读**形式; 检测命令 (DETECT) 由
``scripts/audit_*.py`` 从注册表生成。

用法::

    from platform_data.contracts.boundary_registry import (
        boundary_registry, ModuleBoundaryContract,
    )

    boundary_registry.register(ModuleBoundaryContract(
        module_id="mymodule",
        can_read=("processed_fills",),
        can_write=(),
        api_auth_required=True,
        forbidden_imports=("DataPipeline.src",),
    ))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleBoundaryContract:
    """单个模块的边界契约声明。

    Attributes:
        module_id: 模块唯一标识 (如 "execution", "costview", "backend_api")
        can_read: 可读数据域 (DB 键或数据域名); 空 tuple 表示无
        can_write: 可写数据域; 空 tuple 表示只读模块
        api_auth_required: 该模块的 API 端点是否要求认证 (默认 True)
        forbidden_imports: 禁止的 import 前缀 (如 "CostView.src", "@costview")
    """

    module_id: str
    can_read: tuple[str, ...] = ()
    can_write: tuple[str, ...] = ()
    api_auth_required: bool = True
    forbidden_imports: tuple[str, ...] = ()


@dataclass
class BoundaryContractRegistry:
    """模块边界契约的进程级注册表 (线程安全, 支持动态注册)。"""

    _contracts: dict[str, ModuleBoundaryContract] = field(default_factory=dict)

    def register(self, contract: ModuleBoundaryContract) -> None:
        """注册模块契约。同 id 重复注册时保留先注册者并告警。"""
        existing = self._contracts.get(contract.module_id)
        if existing is not None:
            logger.warning(
                "边界契约重复注册被忽略: %s (首注册者胜出)", contract.module_id
            )
            return
        self._contracts[contract.module_id] = contract
        logger.debug("边界契约已注册: %s", contract.module_id)

    def get(self, module_id: str) -> ModuleBoundaryContract | None:
        """按模块 id 查询契约。"""
        return self._contracts.get(module_id)

    def all_contracts(self) -> list[ModuleBoundaryContract]:
        """返回全部已注册契约 (按 module_id 排序)。"""
        return sorted(self._contracts.values(), key=lambda c: c.module_id)

    def all_forbidden_imports(self) -> dict[str, tuple[str, ...]]:
        """{module_id: forbidden_imports} 映射 — 供审计脚本生成检测规则。"""
        return {c.module_id: c.forbidden_imports for c in self.all_contracts()}

    def data_owners(self) -> dict[str, tuple[str, ...]]:
        """{data_domain: (owner_module_ids)} 映射 — 供越界写检测使用。"""
        owners: dict[str, list[str]] = {}
        for contract in self.all_contracts():
            for domain in contract.can_write:
                owners.setdefault(domain, []).append(contract.module_id)
        return {k: tuple(v) for k, v in owners.items()}

    def validate_cross_module_read(
        self, module_id: str, domain: str
    ) -> tuple[bool, str]:
        """校验模块对数据域的读取权限。

        Returns:
            (allowed, reason)
        """
        contract = self._contracts.get(module_id)
        if contract is None:
            return True, f"模块 {module_id} 未注册契约, 默认放行"
        if domain in contract.can_read:
            return True, ""
        return (
            False,
            f"模块 {module_id} 无权限读取数据域 '{domain}'",
        )

    def validate_cross_module_write(
        self, module_id: str, domain: str
    ) -> tuple[bool, str]:
        """校验模块对数据域的写入权限。"""
        contract = self._contracts.get(module_id)
        if contract is None:
            return True, f"模块 {module_id} 未注册契约, 默认放行"
        if domain in contract.can_write:
            return True, ""
        return (
            False,
            f"模块 {module_id} 无权限写入数据域 '{domain}'",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 默认契约 — 与 .codebuddy/rules/module-boundary.md 对齐 (2026-08-14)
# 新增模块: 追加注册即可, 检测工具自动纳入
# ═══════════════════════════════════════════════════════════════════════════

boundary_registry = BoundaryContractRegistry()


def _register_default_contracts() -> None:
    """注册内置模块的默认边界契约。"""
    defaults = [
        # ── 前端模块 (import 边界) ──
        ModuleBoundaryContract(
            module_id="frontend_execution",
            can_read=("execution_state",),
            can_write=("execution_state",),
            forbidden_imports=("@costview", "@marketview", "@databaseview"),
        ),
        ModuleBoundaryContract(
            module_id="frontend_costview",
            can_read=("tca_route_summary",),
            can_write=(),
            forbidden_imports=("@execution", "@marketview", "@databaseview"),
        ),
        ModuleBoundaryContract(
            module_id="frontend_marketview",
            can_read=("market_snapshot",),
            can_write=("market_snapshot",),
            forbidden_imports=("@execution", "@costview", "@databaseview"),
        ),
        ModuleBoundaryContract(
            module_id="frontend_databaseview",
            can_read=(),
            can_write=(),
            forbidden_imports=("@execution", "@costview", "@marketview"),
        ),
        # ── 后端模块 ──
        ModuleBoundaryContract(
            module_id="backend_api",
            can_read=("processed_fills", "tca_route_summary", "execution_history"),
            can_write=("execution_state",),
            api_auth_required=True,
            forbidden_imports=("CostView.src", "DataPipeline.src"),
        ),
        ModuleBoundaryContract(
            module_id="costview_src",
            can_read=("processed_fills", "fill_bdib", "tca_route_summary", "regime"),
            can_write=("regime",),
            api_auth_required=True,
            forbidden_imports=("backend.api", "DataPipeline.src"),
        ),
        ModuleBoundaryContract(
            module_id="datapipeline",
            can_read=("raw_fills",),
            can_write=(
                "raw_fills", "processed_fills", "raw_bdib", "fill_bdib",
                "execution_history", "ticker_registry", "tca_route_summary",
            ),
            api_auth_required=False,  # 管道为后台进程, 无 HTTP API
            forbidden_imports=("backend.api", "CostView.src"),
        ),
    ]
    for contract in defaults:
        boundary_registry.register(contract)


_register_default_contracts()

"""下单前检查统一入口（审计 A02 / H2）。

四个下单入口共用本模块，避免「同一笔订单换入口即绕过」：
- `routers/orders_crud.route_order`
- `routers/route_plans.confirm_proposal`
- `routers/route_plans.batch_confirm_proposals`
- `services/batch_route_service._evaluate_route_item`

固定顺序：准入白名单（071）→ 订单合规（072）→ 策略注册表（070/073）→
通用合规（碎股白名单，071）。仅 `severity == "BLOCK"` 阻断；`WARN` 记录后放行。

　　本模块是 `evaluate_access` / `evaluate_order_compliance` /
`validate_route_submission` 的唯一入口（边界测试锁定）；内部逻辑、阈值与
特性开关均沿用既有实现，不做二次判定。
"""

from __future__ import annotations

import logging
from typing import Any

from services import access_policy_service, compliance_service
from services.order_compliance_service import evaluate_order_compliance
from services.strategy_registry import validate_route_submission

logger = logging.getLogger(__name__)


def split_by_severity(violations: list[dict]) -> tuple[list[dict], list[dict]]:
    """拆 BLOCK / WARN（仅 BLOCK 阻断）。"""
    blocking = [v for v in violations if v.get("severity") == "BLOCK"]
    warnings = [v for v in violations if v.get("severity") == "WARN"]
    return blocking, warnings


def _access_violations(parent_order: Any, proposal: dict) -> list[dict]:
    """准入白名单（071）：manual_review_required → WARN，其余 BLOCK。"""
    if parent_order is None:
        return []
    return [
        {
            "code": violation.code,
            "message": violation.message,
            "severity": "WARN" if violation.manual_review_required else "BLOCK",
            "details": {"source": "access_policy"},
        }
        for violation in access_policy_service.evaluate_access(parent_order, proposal)
    ]


async def _order_compliance_violations(
    parent_order: Any, proposal: dict, bloomberg: Any
) -> list[dict]:
    """订单合规（072）：数量守恒 / 反向单 / 算法参数（开关沿用既有实现）。"""
    if parent_order is None:
        return []
    violations = await evaluate_order_compliance(
        parent_order,
        route_qty=int(proposal.get("quantity") or 0),
        broker=str(proposal.get("broker") or ""),
        bloomberg=bloomberg,
        strategy_params=proposal.get("strategy_params") or {},
    )
    return [
        {
            **violation,
            "details": {
                **(violation.get("details") or {}),
                "source": "order_compliance",
            },
        }
        for violation in violations
    ]


def _strategy_code(message: str) -> str:
    """白名单未命中与参数错误共用错误列表，按消息前缀区分（既有实现不改）。"""
    return "STRATEGY_NOT_ALLOWED" if message.startswith("algo whitelist:") else "STRATEGY_PARAM_INVALID"


def _strategy_violations(proposal: dict) -> list[dict]:
    """策略注册表（070/073）：errors → BLOCK，warnings → WARN。"""
    params = proposal.get("strategy_params") or {}
    strategy_name = str(params.get("strategyName") or "")
    validation = validate_route_submission(
        str(proposal.get("broker") or ""), strategy_name, params
    )
    violations = [
        {
            "code": _strategy_code(error),
            "message": error,
            "severity": "BLOCK",
            "details": {"source": "strategy_registry"},
        }
        for error in validation.errors
    ]
    violations.extend(
        {
            "code": "STRATEGY_WARNING",
            "message": warning,
            "severity": "WARN",
            "details": {"source": "strategy_registry"},
        }
        for warning in validation.warnings
    )
    return violations


def _route_compliance_violations(parent_order: Any, proposal: dict) -> list[dict]:
    """通用合规（notional / 整手碎股）：碎股白名单由 fractional_markets 提供。"""
    if parent_order is None:
        return []
    violations = compliance_service.check_route(
        parent_order,
        route_qty=int(proposal.get("quantity") or 0),
        limit_price=proposal.get("limit_price"),
        stop_price=proposal.get("stop_price"),
        order_type=str(proposal.get("order_type") or ""),
        fractional_markets=access_policy_service.fractional_markets(),
    )
    return [
        {
            "code": violation.code,
            "message": violation.message,
            "severity": violation.severity,
            "details": {"source": "route_compliance"},
        }
        for violation in violations
    ]


async def pre_trade_checks(
    parent_order: Any,
    proposal: dict,
    bloomberg: Any = None,
) -> list[dict]:
    """下单前检查统一入口（四入口共用）。

    `proposal` 键：broker / quantity / limit_price / stop_price / order_type /
    strategy_params / parent_order_id。返回 `{code, message, severity, details}`
    列表；空列表 = 通过。

    `parent_order is None` 时跳过需要订单对象的检查（准入 / 订单合规 / 通用合规），
    策略注册表仍执行——与既有单笔确认语义一致；「订单缺失即拒单」留给 A07。
    """
    violations = _access_violations(parent_order, proposal)
    violations.extend(await _order_compliance_violations(parent_order, proposal, bloomberg))
    violations.extend(_strategy_violations(proposal))
    violations.extend(_route_compliance_violations(parent_order, proposal))
    return violations

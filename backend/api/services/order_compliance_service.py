"""订单合规服务（057 DL-17b/072）：反向单判定与金额拆分计划。

- **禁止同日同券商反向单**：甲1 被券商 A 执行后，甲2（同日同标的反向）的
  剩余部分不得再路由 A（轧差基数 = 甲1 在 A 的已执行量，精确剩余量口径）；
- **金额上限拆分**：唯一允许拆单场景，产物是既有订单的子路由（数量守恒），
  不是新订单（交易员意见第 4 项 + 用户 2026-10-23 边界确认）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from platform_data.contracts import (
    DEFAULT_MAX_NOTIONAL_USD,
    ReverseOrderDecision,
    SplitPlan,
    plan_notional_split,
    reverse_order_decision,
)

logger = logging.getLogger(__name__)


async def executed_on_broker(order_id: str, broker: str) -> int | None:
    """某订单在某券商的已执行量（运营库 slices × routes_projection 聚合）。

    存在无法归属券商的 slice（route_id 为空）时返回 None（转人工，不猜）。
    """
    from db import get_db_session
    from models.parent_child_orders import ChildSlice, ParentExecution
    from models.execution_state import RouteProjection
    from sqlalchemy import select

    try:
        async with get_db_session() as session:
            result = await session.execute(
                select(ChildSlice, RouteProjection)
                .join(ParentExecution, ParentExecution.id == ChildSlice.parent_id)
                .outerjoin(RouteProjection, RouteProjection.route_id == ChildSlice.route_id)
                .where(ParentExecution.order_id == order_id)
            )
            total = 0
            unassignable = False
            for child, route in result.all():
                if route is None or not getattr(route, "broker", ""):
                    if int(child.filled_quantity or 0) > 0:
                        unassignable = True
                    continue
                if route.broker == broker:
                    total += int(child.filled_quantity or 0)
            if unassignable:
                logger.warning(
                    "executed_on_broker %s/%s: some filled slices have no broker attribution",
                    order_id,
                    broker,
                )
                return None
            return total
    except Exception:
        logger.warning("executed_on_broker query failed for %s", order_id, exc_info=True)
        return None


def _opposite_orders(bloomberg: Any, parent_order: Any) -> list[Any]:
    """内存中的同日同标的反向订单（不同 order_id）。"""
    orders = getattr(bloomberg, "_orders", None) if bloomberg is not None else None
    if not orders:
        return []
    symbol = getattr(parent_order, "symbol", None)
    side = (getattr(parent_order, "side", "") or "").upper()
    order_id = getattr(parent_order, "id", None) or getattr(parent_order, "orderId", None)
    if not symbol or side not in {"BUY", "SELL"}:
        return []
    opposite_side = "SELL" if side == "BUY" else "BUY"
    with getattr(bloomberg, "_data_lock", _NullLock()):
        candidates = list(orders.values())
    return [
        order
        for order in candidates
        if getattr(order, "symbol", None) == symbol
        and (getattr(order, "side", "") or "").upper() == opposite_side
        and (getattr(order, "id", None) or getattr(order, "orderId", None)) != order_id
    ]


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


async def evaluate_reverse_order(
    parent_order: Any,
    broker: str,
    bloomberg: Any = None,
    *,
    new_order_remaining: int | None = None,
) -> ReverseOrderDecision:
    """同日同券商反向单判定（聚合全部反向订单的该券商已执行量）。"""
    if parent_order is None or not broker:
        return reverse_order_decision(executed_on_broker=None, new_order_remaining=new_order_remaining)

    if new_order_remaining is None:
        from services.remaining_quantity_service import remaining_quantity

        remaining = await remaining_quantity(getattr(parent_order, "id", "") or "", bloomberg)
        new_order_remaining = remaining.quantity

    candidates = _opposite_orders(bloomberg, parent_order)
    if not candidates:
        return reverse_order_decision(executed_on_broker=0, new_order_remaining=new_order_remaining)

    total_executed: int | None = 0
    for opposite in candidates:
        opposite_id = getattr(opposite, "id", None) or getattr(opposite, "orderId", None)
        if not opposite_id:
            continue
        executed = await executed_on_broker(str(opposite_id), broker)
        if executed is None:
            total_executed = None
            break
        total_executed += executed
    return reverse_order_decision(
        executed_on_broker=total_executed,
        new_order_remaining=new_order_remaining,
    )


def load_volume_cap_mapping(path: str | None = None) -> dict[str, str]:
    """券商 → volume cap 参数名映射（每券商 JSON 记录，hand_instruction 同款）。

    读取优先级（057 DL-17c/073）：`broker_algorithms.json` 的
    strategies[].parameters（EMSX 菜单刷新后填充，参数名含 vol/pct 即采用）
    > `broker_volume_cap_params.json`（手工记录）> 缺省 PctVol（契约缺省）。
    后者由 `param_name_for` 在检查时给出并标注来源。
    """
    from pathlib import Path

    mapping: dict[str, str] = {}

    # ① EMSX 策略菜单缓存（已填充才用）
    algo_path = Path(__file__).resolve().parent.parent / "data" / "broker_algorithms.json"
    if algo_path.exists():
        try:
            payload = json.loads(algo_path.read_text(encoding="utf-8"))
            for config in payload.get("configs") or []:
                broker = str(config.get("broker") or "").strip()
                for strategy in config.get("strategies") or []:
                    for param in strategy.get("parameters") or []:
                        name = str(param.get("fieldName") or "")
                        lowered = name.lower()
                        if broker and ("vol" in lowered or "pct" in lowered):
                            mapping.setdefault(broker, name)
        except (OSError, json.JSONDecodeError):
            logger.warning("broker_algorithms.json 解析失败，回落手工映射", exc_info=True)

    # ② 手工记录（与 broker_hand_instruction.json 同款模式）
    record_path = path or str(
        Path(__file__).resolve().parent.parent / "data" / "broker_volume_cap_params.json"
    )
    if Path(record_path).exists():
        try:
            record = json.loads(Path(record_path).read_text(encoding="utf-8"))
            for broker, name in record.items():
                if broker.startswith("_") or broker == "EXAMPLE_BROKER":
                    continue
                if isinstance(name, str) and name:
                    mapping.setdefault(broker.strip(), name)
        except (OSError, json.JSONDecodeError):
            logger.warning("broker_volume_cap_params.json 解析失败", exc_info=True)
    return mapping


def _market_of(parent_order: Any) -> str:
    """订单市场码（exchange 经 DL-03 折叠）。"""
    from platform_data.adapters import ExchangeSessionAdapter

    exchange = getattr(parent_order, "exchange", "") or ""
    return ExchangeSessionAdapter().market_code_for(exchange) if exchange else ""


async def evaluate_order_compliance(
    parent_order: Any,
    *,
    route_qty: int,
    broker: str,
    bloomberg: Any = None,
    strategy_params: dict | None = None,
) -> list[dict]:
    """订单合规检查（submission_service 与 orders_crud.route_order 共用）。

    返回违规字典列表（code/message/severity），空 = 通过：
    - QUANTITY_EXCEEDS_REMAINING（BLOCK）：路由量超过剩余订单量——引擎不得造单/改量；
    - REVERSE_ORDER_BROKER_BLOCKED（BLOCK）：同日同券商反向单命中——该券商不可再路由；
    - REVERSE_ORDER_MANUAL_REVIEW（WARN）：已执行量或剩余量不可得——转人工；
    - VOLUME_CAP_MISSING（BLOCK，057 DL-17c）：每路由必带 volume cap（按券商命名）；
    - RELEASE_TIME_MISSING（BLOCK）：收盘拍卖市场订单必带 release time。
    """
    if parent_order is None:
        return []
    from services.remaining_quantity_service import remaining_quantity

    order_id = getattr(parent_order, "id", None) or getattr(parent_order, "orderId", None) or ""
    violations: list[dict] = []

    remaining = await remaining_quantity(str(order_id), bloomberg)
    if remaining.quantity is not None and route_qty > remaining.quantity:
        violations.append(
            {
                "code": "QUANTITY_EXCEEDS_REMAINING",
                "message": (
                    f"route quantity {route_qty} exceeds remaining order quantity {remaining.quantity} "
                    f"(source={remaining.source}); engine must not create or resize orders"
                ),
                "severity": "BLOCK",
            }
        )

    decision = await evaluate_reverse_order(
        parent_order, broker, bloomberg, new_order_remaining=route_qty
    )
    if not decision.allowed:
        violations.append(
            {
                "code": "REVERSE_ORDER_BROKER_BLOCKED",
                "message": decision.reason,
                "severity": "BLOCK",
            }
        )
    elif decision.needs_manual:
        violations.append(
            {
                "code": "REVERSE_ORDER_MANUAL_REVIEW",
                "message": decision.reason,
                "severity": "WARN",
            }
        )

    # 057 DL-17c/073：算法参数合规（volume cap 必带 + 收盘拍卖 release time）
    # 特性开关默认关闭（G2 新能力默认关闭）：既有路由大多未带 volume cap，
    # 直接 BLOCK 会使系统停摆；开启（EMSXVIEW_ALGO_PARAMS_ENFORCED=true）后阻断。
    if algo_params_enforced():
        from platform_data.contracts import check_release_time_present, check_volume_cap_present

        mapping = load_volume_cap_mapping()
        for error in check_volume_cap_present(strategy_params, broker, mapping=mapping):
            violations.append({"code": "VOLUME_CAP_MISSING", "message": error, "severity": "BLOCK"})
        market = _market_of(parent_order)
        for error in check_release_time_present(strategy_params, market):
            violations.append({"code": "RELEASE_TIME_MISSING", "message": error, "severity": "BLOCK"})
    return violations


def algo_params_enforced() -> bool:
    """算法参数合规是否阻断（默认关闭；EMSXVIEW_ALGO_PARAMS_ENFORCED=true 开启）。"""
    import os

    return os.getenv("EMSXVIEW_ALGO_PARAMS_ENFORCED", "").strip().lower() in {"1", "true", "yes"}


def build_split_plan(
    *,
    order_id: str,
    remaining_qty: int,
    price: float | None,
    fx_rate: float | None,
    broker: str,
    max_notional_usd: float = DEFAULT_MAX_NOTIONAL_USD,
) -> SplitPlan:
    """金额上限拆分计划（数量守恒，子路由而非新订单）。"""
    return plan_notional_split(
        order_id=order_id,
        remaining_qty=remaining_qty,
        price=price,
        fx_rate=fx_rate,
        max_notional_usd=max_notional_usd,
        broker=broker,
    )

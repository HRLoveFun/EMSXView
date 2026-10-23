"""精确剩余订单量服务（057 DL-17b/072）。

交易员口径（2026-10-23）：「剩余订单数量必须精确，不仅为反向单情形服务，
也为常规的多次路由订单情形服务」。

双源：
- 订阅源：`bloomberg._orders[order_id].remainingQuantity`（内存实时）；
- 落盘源：运营库 `parent_executions`（`target_quantity − filled_quantity`，
  DL-02 已落盘）。

不一致时取**保守值（min）**并标 `consistent=False`（暴露审计，不静默选边）；
两源皆不可得 → `quantity=None`（调用方转人工，不猜）。
"""

from __future__ import annotations

import logging
from typing import Any

from platform_data.contracts import RemainingQuantity

logger = logging.getLogger(__name__)


def _subscription_remaining(bloomberg: Any, order_id: str) -> int | None:
    """内存订单的剩余量（Bloomberg 订阅实时）。"""
    if bloomberg is None or not hasattr(bloomberg, "_orders"):
        return None
    lock = getattr(bloomberg, "_data_lock", None)
    try:
        if lock is not None:
            with lock:
                order = bloomberg._orders.get(order_id)
        else:
            order = bloomberg._orders.get(order_id)
    except Exception:  # 订阅状态异常不阻断读取路径
        return None
    if order is None:
        return None
    remaining = getattr(order, "remainingQuantity", None)
    if remaining is None:
        return None
    try:
        value = int(remaining)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


async def _projection_remaining(order_id: str) -> int | None:
    """运营库 parent_executions 的剩余量（target − filled）。"""
    from db import get_db_session
    from models.parent_child_orders import ParentExecution
    from sqlalchemy import select

    try:
        async with get_db_session() as session:
            result = await session.execute(
                select(ParentExecution).where(ParentExecution.order_id == order_id).limit(1)
            )
            parent = result.scalar_one_or_none()
            if parent is None:
                return None
            return max(int(parent.target_quantity) - int(parent.filled_quantity), 0)
    except Exception:  # 持久化不可用 → 单源降级（不阻断）
        logger.warning("remaining quantity projection unavailable for %s", order_id, exc_info=True)
        return None


async def remaining_quantity(order_id: str, bloomberg: Any = None) -> RemainingQuantity:
    """双源剩余量（保守取值 + 一致性标记）。"""
    subscription = _subscription_remaining(bloomberg, order_id)
    projection = await _projection_remaining(order_id)

    if subscription is None and projection is None:
        return RemainingQuantity(
            order_id=order_id,
            quantity=None,
            source="unavailable",
            consistent=False,
            subscription_qty=None,
            projection_qty=None,
        )
    if subscription is not None and projection is not None:
        if subscription == projection:
            return RemainingQuantity(
                order_id=order_id,
                quantity=subscription,
                source="both",
                consistent=True,
                subscription_qty=subscription,
                projection_qty=projection,
            )
        conservative = min(subscription, projection)
        logger.warning(
            "remaining quantity mismatch for %s: subscription=%s projection=%s → using %s",
            order_id,
            subscription,
            projection,
            conservative,
        )
        return RemainingQuantity(
            order_id=order_id,
            quantity=conservative,
            source="both(min)",
            consistent=False,
            subscription_qty=subscription,
            projection_qty=projection,
        )
    value = subscription if subscription is not None else projection
    return RemainingQuantity(
        order_id=order_id,
        quantity=value,
        source="subscription" if subscription is not None else "projection",
        consistent=True,
        subscription_qty=subscription,
        projection_qty=projection,
    )

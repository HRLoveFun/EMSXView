"""订单合规契约（057 DL-17b/072）——纯数据 + 纯函数，无 IO。

语义边界（2026-10-23 用户确认）：
- **订单创建** = PM 创建「买入 100 股 AAPL US」这样的订单；交易员接收 PM 订单后
  执行。引擎**禁止自行创建订单**；
- **拆分** = 对已有订单（parent order）拆出**子路由**（数量守恒，sum == 剩余量），
  **不是新订单**；且拆分**仅限路由金额上限**一个场景（交易员意见第 4 项），
  不得为现金/卖空等其它约束拆单或改量。

现金账户口径（用户 2026-10-23）：默认所有组合都是现金账户（`AccountType.CASH`），
不引入现金/持仓数据源——杠杆与卖空由券商侧（EMSX）校验兜底，引擎侧以数量
守恒不变量固化「不造单、不改量」纪律。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

# 契约版本：结构/口径变更时升版（审计记录所用版本）
ORDER_SPLIT_VERSION = "order-split-v1"

# 路由金额上限默认值（交易员意见：「49M 为当前检查值」，参数待建）
DEFAULT_MAX_NOTIONAL_USD = 49_000_000.0


class AccountType(str, Enum):
    """账户类型（默认现金账户；MARGIN 预留）。"""

    CASH = "CASH"
    MARGIN = "MARGIN"


@dataclass(frozen=True)
class SplitLeg:
    """子路由（对已有订单的切分，不是新订单）。"""

    quantity: int
    broker: str
    reason: str = "notional_cap"


@dataclass(frozen=True)
class SplitPlan:
    """拆分计划：数量守恒（sum(legs) == remaining_qty）是硬不变量。"""

    order_id: str
    remaining_qty: int
    legs: tuple[SplitLeg, ...]
    max_notional_usd: float
    reason: str | None = None  # 无法拆分时的原因（价格/fx 不可得等）


@dataclass(frozen=True)
class ReverseOrderDecision:
    """同日同券商反向单判定（轧差基数 = 甲1 在该券商的已执行量）。"""

    allowed: bool
    needs_manual: bool
    reason: str
    executed_on_broker: int | None = None
    new_order_remaining: int | None = None


def plan_notional_split(
    *,
    order_id: str,
    remaining_qty: int,
    price: float | None,
    fx_rate: float | None,
    max_notional_usd: float = DEFAULT_MAX_NOTIONAL_USD,
    broker: str = "",
) -> SplitPlan:
    """按金额上限生成子路由切分（数量守恒）。

    每段数量 = floor(max_notional_usd / (price × fx_rate))；不足一段则整单一段。
    price/fx 不可得或非正 → 返回空 legs + reason（不猜、不拆）。
    """
    if remaining_qty <= 0:
        return SplitPlan(order_id=order_id, remaining_qty=remaining_qty, legs=(), max_notional_usd=max_notional_usd)
    if price is None or price <= 0 or fx_rate is None or fx_rate <= 0:
        return SplitPlan(
            order_id=order_id,
            remaining_qty=remaining_qty,
            legs=(),
            max_notional_usd=max_notional_usd,
            reason="price_or_fx_unavailable",
        )
    unit_notional = price * fx_rate
    max_qty = int(math.floor(max_notional_usd / unit_notional))
    if max_qty <= 0:
        return SplitPlan(
            order_id=order_id,
            remaining_qty=remaining_qty,
            legs=(),
            max_notional_usd=max_notional_usd,
            reason="single_share_exceeds_notional_cap",
        )
    legs: list[SplitLeg] = []
    left = remaining_qty
    while left > 0:
        take = min(max_qty, left)
        legs.append(SplitLeg(quantity=take, broker=broker))
        left -= take
    return SplitPlan(
        order_id=order_id,
        remaining_qty=remaining_qty,
        legs=tuple(legs),
        max_notional_usd=max_notional_usd,
    )


def check_quantity_invariant(original_qty: int, leg_quantities: tuple[int, ...] | list[int]) -> list[str]:
    """数量守恒不变量：禁止造单/改量。

    - 每段必须 > 0；sum(legs) 必须 == original_qty（剩余订单量）；
    - 违反返回可读错误（空列表 = 通过）。
    """
    errors: list[str] = []
    if any(q <= 0 for q in leg_quantities):
        errors.append("split legs must all be positive quantities")
    total = sum(leg_quantities)
    if total != original_qty:
        errors.append(
            f"split legs sum {total} != remaining quantity {original_qty} "
            f"(engine must not create or resize orders)"
        )
    return errors


def reverse_order_decision(
    *,
    executed_on_broker: int | None,
    new_order_remaining: int | None,
) -> ReverseOrderDecision:
    """同日同券商反向单：甲1 被券商 A 执行后，甲2 剩余部分不得再路由 A。

    - 甲1 在该券商已执行 0 → 允许（该券商未看到甲1 的执行）；
    - 甲2 剩余 0 → 允许（全部被内部轧差）；
    - 已执行 > 0 且甲2 剩余 > 0 → 禁止该券商（可改路由其它券商）；
    - 已执行量不可得 → 转人工（不猜）。
    """
    if executed_on_broker is None:
        return ReverseOrderDecision(
            allowed=True,
            needs_manual=True,
            reason="executed quantity on broker unavailable: manual review required",
            executed_on_broker=None,
            new_order_remaining=new_order_remaining,
        )
    if executed_on_broker <= 0:
        return ReverseOrderDecision(
            allowed=True,
            needs_manual=False,
            reason="no execution on this broker for the opposite order",
            executed_on_broker=executed_on_broker,
            new_order_remaining=new_order_remaining,
        )
    if new_order_remaining is None:
        return ReverseOrderDecision(
            allowed=True,
            needs_manual=True,
            reason="remaining quantity unavailable: manual review required",
            executed_on_broker=executed_on_broker,
            new_order_remaining=None,
        )
    if new_order_remaining <= 0:
        return ReverseOrderDecision(
            allowed=True,
            needs_manual=False,
            reason="new order fully netted against opposite order",
            executed_on_broker=executed_on_broker,
            new_order_remaining=new_order_remaining,
        )
    return ReverseOrderDecision(
        allowed=False,
        needs_manual=False,
        reason=(
            f"broker executed the opposite order (executed={executed_on_broker}); "
            f"remaining {new_order_remaining} must be routed to another broker"
        ),
        executed_on_broker=executed_on_broker,
        new_order_remaining=new_order_remaining,
    )


@dataclass(frozen=True)
class RemainingQuantity:
    """精确剩余订单量（双源：订阅实时 + 运营库落盘）。"""

    order_id: str
    quantity: int | None
    source: str  # subscription / projection / both(min) / unavailable
    consistent: bool = True
    subscription_qty: int | None = None
    projection_qty: int | None = None

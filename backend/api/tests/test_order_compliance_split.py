"""057 DL-17b/072：订单合规（金额拆分 / 反向单 / 精确剩余量 / 数量守恒）测试。

夹具全部虚构：fake bloomberg（内存订单）、monkeypatch 运营库读取。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from platform_data.contracts import (  # noqa: E402
    DEFAULT_MAX_NOTIONAL_USD,
    SplitLeg,
    check_quantity_invariant,
    plan_notional_split,
    reverse_order_decision,
)
from services import remaining_quantity_service, order_compliance_service  # noqa: E402


class _FakeBloomberg:
    def __init__(self, orders=None):
        import threading

        self._orders = orders or {}
        self._data_lock = threading.Lock()


def _order(order_id="1001", symbol="AAPL US Equity", side="BUY", remaining=1000):
    return SimpleNamespace(
        id=order_id,
        orderId=order_id,
        symbol=symbol,
        side=side,
        remainingQuantity=remaining,
    )


class TestNotionalSplit:
    """① 金额拆分（守恒 + 边界）。"""

    def test_exact_division(self):
        plan = plan_notional_split(
            order_id="1001", remaining_qty=1000, price=100.0, fx_rate=1.0, max_notional_usd=50_000.0
        )
        assert [leg.quantity for leg in plan.legs] == [500, 500]
        assert sum(leg.quantity for leg in plan.legs) == plan.remaining_qty  # 守恒

    def test_remainder_kept_conserved(self):
        plan = plan_notional_split(
            order_id="1001", remaining_qty=1001, price=100.0, fx_rate=1.0, max_notional_usd=50_000.0
        )
        assert [leg.quantity for leg in plan.legs] == [500, 500, 1]
        assert sum(leg.quantity for leg in plan.legs) == 1001

    def test_single_leg_when_under_cap(self):
        plan = plan_notional_split(
            order_id="1001", remaining_qty=10, price=100.0, fx_rate=1.0, max_notional_usd=50_000.0
        )
        assert [leg.quantity for leg in plan.legs] == [10]

    def test_price_unavailable_returns_reason(self):
        plan = plan_notional_split(
            order_id="1001", remaining_qty=1000, price=None, fx_rate=1.0
        )
        assert plan.legs == ()
        assert plan.reason == "price_or_fx_unavailable"

    def test_single_share_exceeds_cap(self):
        plan = plan_notional_split(
            order_id="1001", remaining_qty=10, price=10_000_000.0, fx_rate=1.0, max_notional_usd=1.0
        )
        assert plan.legs == ()
        assert plan.reason == "single_share_exceeds_notional_cap"

    def test_default_cap_constant(self):
        assert DEFAULT_MAX_NOTIONAL_USD == 49_000_000.0


class TestQuantityInvariant:
    """② 数量守恒不变量（禁止造单/改量）。"""

    def test_conserved_passes(self):
        assert check_quantity_invariant(1000, (600, 400)) == []

    def test_sum_mismatch_blocks(self):
        errors = check_quantity_invariant(1000, (600, 399))
        assert errors and "must not create or resize orders" in errors[0]

    def test_non_positive_leg_blocks(self):
        assert check_quantity_invariant(1000, (1000, 0))
        assert check_quantity_invariant(1000, (-100, 1100))


class TestReverseOrderDecision:
    """③ 反向单判定四态。"""

    def test_no_execution_allows(self):
        decision = reverse_order_decision(executed_on_broker=0, new_order_remaining=500)
        assert decision.allowed is True and decision.needs_manual is False

    def test_execution_and_remaining_blocks_broker(self):
        decision = reverse_order_decision(executed_on_broker=300, new_order_remaining=200)
        assert decision.allowed is False
        assert "another broker" in decision.reason

    def test_fully_netted_allows(self):
        decision = reverse_order_decision(executed_on_broker=300, new_order_remaining=0)
        assert decision.allowed is True

    def test_executed_unavailable_manual(self):
        decision = reverse_order_decision(executed_on_broker=None, new_order_remaining=200)
        assert decision.allowed is True and decision.needs_manual is True


class TestRemainingQuantity:
    """④ 剩余量双源（保守取值 + 一致性标记）。"""

    @pytest.mark.asyncio
    async def test_both_consistent(self, monkeypatch):
        async def _projection(order_id):
            return 400

        monkeypatch.setattr(remaining_quantity_service, "_projection_remaining", _projection)
        remaining = await remaining_quantity_service.remaining_quantity("1001", _FakeBloomberg())

        # 无内存订单 → 单源落盘
        assert remaining.source == "projection"
        assert remaining.quantity == 400
        assert remaining.consistent is True

    @pytest.mark.asyncio
    async def test_mismatch_takes_conservative_min(self, monkeypatch):
        async def _projection(order_id):
            return 300

        monkeypatch.setattr(remaining_quantity_service, "_projection_remaining", _projection)
        bloomberg = _FakeBloomberg({"1001": _order(remaining=500)})
        remaining = await remaining_quantity_service.remaining_quantity("1001", bloomberg)

        assert remaining.quantity == 300  # min(500, 300)
        assert remaining.consistent is False
        assert remaining.source == "both(min)"

    @pytest.mark.asyncio
    async def test_both_unavailable_none(self, monkeypatch):
        async def _projection(order_id):
            return None

        monkeypatch.setattr(remaining_quantity_service, "_projection_remaining", _projection)
        remaining = await remaining_quantity_service.remaining_quantity("9999", _FakeBloomberg())

        assert remaining.quantity is None
        assert remaining.source == "unavailable"


class TestEvaluateOrderCompliance:
    """⑤ 接入检查（BLOCK/WARN）。"""

    @pytest.mark.asyncio
    async def test_exceed_remaining_blocks(self, monkeypatch):
        async def _projection(order_id):
            return 100

        monkeypatch.setattr(remaining_quantity_service, "_projection_remaining", _projection)
        parent = _order(remaining=100)
        violations = await order_compliance_service.evaluate_order_compliance(
            parent, route_qty=150, broker="EQ-AAA", bloomberg=_FakeBloomberg({"1001": parent})
        )

        codes = {v["code"] for v in violations}
        assert "QUANTITY_EXCEEDS_REMAINING" in codes
        assert all(v["severity"] == "BLOCK" for v in violations if v["code"] == "QUANTITY_EXCEEDS_REMAINING")

    @pytest.mark.asyncio
    async def test_reverse_order_blocks_broker(self, monkeypatch):
        async def _projection(order_id):
            return 500

        async def _executed(order_id, broker):
            return 300 if order_id == "2002" else 0

        monkeypatch.setattr(remaining_quantity_service, "_projection_remaining", _projection)
        monkeypatch.setattr(order_compliance_service, "executed_on_broker", _executed)
        parent = _order(order_id="1001", side="SELL", remaining=200)
        opposite = _order(order_id="2002", side="BUY", remaining=0)
        bloomberg = _FakeBloomberg({"1001": parent, "2002": opposite})

        violations = await order_compliance_service.evaluate_order_compliance(
            parent, route_qty=200, broker="EQ-AAA", bloomberg=bloomberg
        )

        codes = {v["code"] for v in violations}
        assert "REVERSE_ORDER_BROKER_BLOCKED" in codes

    @pytest.mark.asyncio
    async def test_no_violation_when_clean(self, monkeypatch):
        async def _projection(order_id):
            return 500

        async def _executed(order_id, broker):
            return 0

        monkeypatch.setattr(remaining_quantity_service, "_projection_remaining", _projection)
        monkeypatch.setattr(order_compliance_service, "executed_on_broker", _executed)
        parent = _order(order_id="1001", side="SELL", remaining=200)

        violations = await order_compliance_service.evaluate_order_compliance(
            parent, route_qty=200, broker="EQ-AAA", bloomberg=_FakeBloomberg({"1001": parent})
        )

        assert violations == []

    def test_split_plan_is_subroute_not_new_order(self):
        """拆分产物是既有订单的子路由：legs 关联同一 order_id 且数量守恒。"""
        plan = order_compliance_service.build_split_plan(
            order_id="1001", remaining_qty=1000, price=100.0, fx_rate=1.0, broker="EQ-AAA",
            max_notional_usd=50_000.0,
        )

        assert plan.order_id == "1001"
        assert all(isinstance(leg, SplitLeg) for leg in plan.legs)
        assert sum(leg.quantity for leg in plan.legs) == 1000

"""Tests for parent-child execution models, repository, and route service."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from models.parent_child_orders import (
    ParentExecution,
    ChildSlice,
    ScheduleType,
    ExecutionStatus,
    SliceStatus,
)
from services.route_service import (
    validate_route_request,
    validate_trader_ownership,
    build_strategy_elements,
    ROUTABLE_STATUSES,
)
from schemas import RouteOrderRequest
from fastapi import HTTPException


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# -----------------------------------------------------------------------
# Model instantiation tests
# -----------------------------------------------------------------------

class TestParentExecutionModel:
    """Verify ORM model can be instantiated with valid data."""

    def test_create_twap_parent(self):
        p = ParentExecution(
            sequence=1001,
            order_id="1001",
            trader="JDOE",
            schedule_type=ScheduleType.TWAP.value,
            target_quantity=10000,
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc) + timedelta(hours=2),
            status=ExecutionStatus.PENDING.value,
        )
        assert p.schedule_type == "TWAP"
        assert p.filled_quantity is None  # default=0 applies on flush, not construction
        assert p.status == "PENDING"

    def test_create_manual_parent(self):
        p = ParentExecution(
            sequence=2002,
            order_id="2002",
            trader="JDOE",
            schedule_type=ScheduleType.MANUAL.value,
            target_quantity=500,
            status=ExecutionStatus.ACTIVE.value,
        )
        assert p.start_time is None
        assert p.end_time is None

    def test_create_pov_parent_with_participation(self):
        p = ParentExecution(
            sequence=3003,
            order_id="3003",
            trader="JSMITH",
            schedule_type=ScheduleType.POV.value,
            target_quantity=50000,
            participation_rate=0.15,
            broker="BMTB",
            status=ExecutionStatus.PENDING.value,
        )
        assert p.participation_rate == 0.15
        assert p.broker == "BMTB"


class TestChildSliceModel:
    def test_create_slice(self):
        s = ChildSlice(
            parent_id=1,
            sequence=1001,
            slice_index=0,
            planned_quantity=2500,
            status=SliceStatus.PENDING.value,
        )
        assert s.route_id is None
        assert s.filled_quantity is None  # default=0 applies on flush
        assert s.slice_index == 0

    def test_slice_with_route(self):
        s = ChildSlice(
            parent_id=1,
            sequence=1001,
            route_id=42,
            slice_index=1,
            planned_quantity=2500,
            limit_price=145.50,
            status=SliceStatus.SENT.value,
        )
        assert s.route_id == 42
        assert s.limit_price == 145.50


# -----------------------------------------------------------------------
# Route service validation tests
# -----------------------------------------------------------------------

class TestValidateRouteRequest:
    def _make_request(self, **overrides):
        defaults = dict(
            orderId="1001",
            broker="BMTB",
            quantity=100,
            orderType="LIMIT",
            price=50.0,
            timeInForce="DAY",
        )
        defaults.update(overrides)
        return RouteOrderRequest(**defaults)

    def _make_order(self, status="WORKING", remaining=1000, trader="JDOE"):
        m = MagicMock()
        m.status = status
        m.remainingQuantity = remaining
        m.trader = trader
        return m

    def test_valid_request_passes(self):
        req = self._make_request()
        order = self._make_order()
        validate_route_request(req, order)  # Should not raise

    def test_order_not_found(self):
        req = self._make_request()
        with pytest.raises(HTTPException) as exc:
            validate_route_request(req, None)
        assert exc.value.status_code == 404

    def test_non_routable_status(self):
        req = self._make_request()
        order = self._make_order(status="FILLED")
        with pytest.raises(HTTPException) as exc:
            validate_route_request(req, order)
        assert exc.value.status_code == 400

    def test_all_routable_statuses_pass(self):
        req = self._make_request()
        for status in ROUTABLE_STATUSES:
            order = self._make_order(status=status)
            validate_route_request(req, order)

    def test_quantity_exceeds_remaining(self):
        req = self._make_request(quantity=500)
        order = self._make_order(remaining=100)
        with pytest.raises(HTTPException) as exc:
            validate_route_request(req, order)
        assert exc.value.status_code == 400


class TestValidateTraderOwnership:
    def test_matching_traders(self):
        validate_trader_ownership("1001", "JDOE", "JDOE")

    def test_case_insensitive(self):
        validate_trader_ownership("1001", "jdoe", "JDOE")

    def test_mismatch_raises_403(self):
        with pytest.raises(HTTPException) as exc:
            validate_trader_ownership("1001", "JDOE", "ASMITH")
        assert exc.value.status_code == 403

    def test_none_terminal_trader_skips(self):
        validate_trader_ownership("1001", "JDOE", None)

    def test_none_order_trader_skips(self):
        validate_trader_ownership("1001", None, "JDOE")


class TestBuildStrategyElements:
    def test_none_input(self):
        assert build_strategy_elements(None) is None

    def test_empty_dict(self):
        assert build_strategy_elements({}) is None

    def test_missing_name(self):
        assert build_strategy_elements({"fields": []}) is None

    def test_valid_strategy(self):
        result = build_strategy_elements({
            "strategyName": "VWAP",
            "fields": [
                {"value": "09:30", "disabled": False},
                {"value": "", "disabled": True},
            ],
        })
        assert result is not None
        assert len(result) == 2
        assert result[0]["value"] == "09:30"
        assert result[0]["indicator"] == 0
        assert result[1]["value"] == ""
        assert result[1]["indicator"] == 1


# -----------------------------------------------------------------------
# RouteOrderRequest schema tests
# -----------------------------------------------------------------------

class TestRouteOrderRequestSchema:
    def test_without_strategy(self):
        req = RouteOrderRequest(
            orderId="1001",
            broker="BMTB",
            quantity=100,
            orderType="LIMIT",
            timeInForce="DAY",
        )
        assert req.strategyParams is None

    def test_with_strategy_params(self):
        req = RouteOrderRequest(
            orderId="1001",
            broker="BMTB",
            quantity=100,
            orderType="MARKET",
            timeInForce="DAY",
            strategyParams={
                "strategyName": "TWAP",
                "fields": [
                    {"value": "09:30", "disabled": False},
                ],
            },
        )
        assert req.strategyParams is not None
        assert req.strategyParams["strategyName"] == "TWAP"

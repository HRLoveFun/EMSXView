"""Integration tests for batch route / batch modify-route endpoints."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schemas import Order, OrderSide, OrderStatus, OrderType, Route, TimeInForce


# ---------------------------------------------------------------------------
# Test app fixture — bypass auth, inject a mocked Bloomberg adapter.
# ---------------------------------------------------------------------------

@pytest.fixture
def make_order_record():
    def _build(order_id: str, **overrides) -> Order:
        defaults = dict(
            id=order_id,
            symbol="AAPL US Equity",
            side=OrderSide.BUY,
            status=OrderStatus.WORKING,
            orderType=OrderType.LIMIT,
            quantity=1000,
            filledQuantity=0,
            remainingQuantity=1000,
            price=200.0,
            timeInForce=TimeInForce.DAY,
            account="ACCT1",
            trader="TRADER1",
            createdAt="2026-04-28T09:30:00",
            updatedAt="2026-04-28T09:30:00",
            currency="USD",
            exchange="US",
            fxRate=1.0,
            lastPrice=200.0,
        )
        defaults.update(overrides)
        return Order(**defaults)
    return _build


@pytest.fixture
def app_with_mock_bloomberg(monkeypatch, make_order_record):
    """Build a minimal FastAPI app wiring orders + routes routers with a mock adapter."""
    # Bypass auth entirely for endpoint tests.
    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")

    import importlib
    import deps
    importlib.reload(deps)
    from routers import orders as orders_router
    from routers import routes as routes_router
    importlib.reload(orders_router)
    importlib.reload(routes_router)

    bloomberg = MagicMock()
    bloomberg._orders = {}
    bloomberg._routes = {}
    bloomberg._data_lock = threading.Lock()
    bloomberg.get_terminal_trader_name = MagicMock(return_value="TRADER1")
    bloomberg.route_order = AsyncMock(
        side_effect=lambda req: {
            "success": True,
            "orderId": req.orderId,
            "routeId": 9001,
            "broker": req.broker,
            "quantity": req.quantity,
        }
    )
    bloomberg.modify_route = AsyncMock(return_value=True)

    deps._bloomberg_service = bloomberg

    app = FastAPI()
    app.include_router(orders_router.router)
    app.include_router(routes_router.router)
    return app, bloomberg


# ---------------------------------------------------------------------------
# /api/orders/batch-route
# ---------------------------------------------------------------------------

def test_batch_route_dry_run_warns_notional_too_small(
    app_with_mock_bloomberg, make_order_record,
):
    app, bloomberg = app_with_mock_bloomberg
    # Order with notional too small: 100 qty * $5 limit = $500 < $10K
    # NOTIONAL_TOO_SMALL is now a soft WARN — route should SUCCEED with violation.
    bloomberg._orders["100"] = make_order_record("100", price=5.0, lastPrice=5.0, remainingQuantity=100)
    client = TestClient(app)

    payload = {
        "template": {"broker": "BB", "orderType": "LIMIT", "timeInForce": "DAY", "price": 5.0},
        "items": [{"orderId": "100", "override": {"quantity": 100}}],
        "dryRun": True,
    }
    resp = client.post("/api/orders/batch-route", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body["data"]
    assert data["total"] == 1
    assert data["blocked"] == 0
    assert data["succeeded"] == 1
    assert data["items"][0]["status"] == "SUCCESS"
    codes = [v["code"] for v in data["items"][0]["violations"]]
    assert "NOTIONAL_TOO_SMALL" in codes
    # Soft warning should not prevent routing — assert bloomberg.route_order
    # will be called in the live path (not checked here since this is dry-run).


def test_batch_route_dry_run_validates_passing_rows(
    app_with_mock_bloomberg, make_order_record,
):
    app, bloomberg = app_with_mock_bloomberg
    bloomberg._orders["200"] = make_order_record("200", price=200.0, lastPrice=200.0)
    client = TestClient(app)

    payload = {
        "template": {"broker": "BB", "orderType": "LIMIT", "timeInForce": "DAY", "price": 200.0},
        "items": [{"orderId": "200", "override": {"quantity": 100}}],
        "dryRun": True,
    }
    resp = client.post("/api/orders/batch-route", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["succeeded"] == 1
    assert data["blocked"] == 0
    bloomberg.route_order.assert_not_awaited()


def test_batch_route_streaming_mixes_blocked_success_failed(
    app_with_mock_bloomberg, make_order_record,
):
    app, bloomberg = app_with_mock_bloomberg
    # Order #1: passes compliance and submits successfully
    bloomberg._orders["1"] = make_order_record("1", price=200.0, lastPrice=200.0)
    # Order #2: notional too small (500 USD < 10K) — soft WARN, route proceeds
    bloomberg._orders["2"] = make_order_record("2", price=5.0, lastPrice=5.0, remainingQuantity=100)
    # Order #3: passes compliance, but adapter raises HTTPException (e.g. EMSX reject)
    bloomberg._orders["3"] = make_order_record("3", price=200.0, lastPrice=200.0)
    # Order #4: missing — should be blocked

    async def route_side_effect(req):
        if req.orderId == "3":
            raise HTTPException(400, "EMSX rejected the order")
        return {"success": True, "orderId": req.orderId, "routeId": 5000 + int(req.orderId)}

    bloomberg.route_order.side_effect = route_side_effect

    client = TestClient(app)
    payload = {
        "template": {"broker": "BB", "orderType": "LIMIT", "timeInForce": "DAY", "price": 200.0},
        "items": [
            {"orderId": "1", "override": {"quantity": 100}},
            # Item 2 overrides price to 5.0 -> 500 USD notional -> blocked
            {"orderId": "2", "override": {"quantity": 100, "price": 5.0}},
            {"orderId": "3", "override": {"quantity": 100}},
            {"orderId": "4", "override": {"quantity": 100}},
        ],
        "dryRun": False,
    }
    with client.stream("POST", "/api/orders/batch-route", json=payload) as resp:
        assert resp.status_code == 200
        lines = [line for line in resp.iter_lines() if line.strip()]

    # 4 item lines + 1 summary line
    assert len(lines) == 5
    parsed = [json.loads(line) for line in lines]
    item_results = parsed[:4]
    summary_line = parsed[4]

    # Streaming order is not strict because submissions are concurrent and
    # may complete out-of-order; assert by membership.
    by_key = {r["key"]: r for r in item_results}
    assert by_key["1"]["status"] == "SUCCESS"
    assert by_key["1"]["routeId"] == 5001
    # Order #2: notional too small is now a soft WARN — status is SUCCESS, carries violation
    assert by_key["2"]["status"] == "SUCCESS"
    codes2 = [v["code"] for v in by_key["2"]["violations"]]
    assert "NOTIONAL_TOO_SMALL" in codes2
    assert by_key["3"]["status"] == "FAILED"
    assert by_key["4"]["status"] == "BLOCKED"
    assert "summary" in summary_line
    summary = summary_line["summary"]
    assert summary["total"] == 4
    assert summary["succeeded"] == 2  # orders #1 (clean) + #2 (soft warn)
    assert summary["blocked"] == 1  # order #4 only
    assert summary["failed"] == 1


def test_batch_route_size_limit_returns_422(app_with_mock_bloomberg, make_order_record):
    app, _bloomberg = app_with_mock_bloomberg
    client = TestClient(app)

    # Build a 501-item payload (default BATCH_ROUTE_MAX_SIZE = 500)
    items = [{"orderId": str(i), "override": {"quantity": 100}} for i in range(501)]
    payload = {
        "template": {"broker": "BB", "orderType": "LIMIT", "timeInForce": "DAY", "price": 200.0},
        "items": items,
        "dryRun": True,
    }
    resp = client.post("/api/orders/batch-route", json=payload)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /api/routes/batch-modify
# ---------------------------------------------------------------------------

def make_route(seq: int, route_id: int, **overrides) -> Route:
    defaults = dict(
        routeId=route_id,
        sequence=seq,
        id=f"{seq}.{route_id}",
        status="WORKING",
        broker="BB",
        amount=500,
        filled=0,
        working=500,
        orderType="LMT",
        tif="DAY",
        limitPrice=200.0,
        currency="USD",
        exchange="US",
        ticker="AAPL US Equity",
    )
    defaults.update(overrides)
    return Route(**defaults)


def test_batch_modify_dry_run(app_with_mock_bloomberg, make_order_record):
    app, bloomberg = app_with_mock_bloomberg
    bloomberg._routes["10.20"] = make_route(10, 20)
    bloomberg._orders["10"] = make_order_record("10", price=200.0, lastPrice=200.0)
    client = TestClient(app)

    payload = {
        "template": {"amount": 500, "orderType": "LMT", "tif": "DAY", "limitPrice": 200.0},
        "items": [{"sequence": 10, "routeId": 20}],
        "dryRun": True,
    }
    resp = client.post("/api/routes/batch-modify", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["succeeded"] == 1
    bloomberg.modify_route.assert_not_awaited()


def test_batch_modify_streaming_failure(app_with_mock_bloomberg, make_order_record):
    app, bloomberg = app_with_mock_bloomberg
    bloomberg._routes["10.20"] = make_route(10, 20)
    bloomberg._orders["10"] = make_order_record("10", price=200.0, lastPrice=200.0)
    bloomberg.modify_route.side_effect = HTTPException(400, "Blpapi rejected")
    client = TestClient(app)

    payload = {
        "template": {"amount": 500, "orderType": "LMT", "tif": "DAY", "limitPrice": 200.0},
        "items": [{"sequence": 10, "routeId": 20}],
        "dryRun": False,
    }
    with client.stream("POST", "/api/routes/batch-modify", json=payload) as resp:
        assert resp.status_code == 200
        lines = [json.loads(l) for l in resp.iter_lines() if l.strip()]

    assert len(lines) == 2
    assert lines[0]["status"] == "FAILED"
    assert lines[1]["summary"]["failed"] == 1


# ---------------------------------------------------------------------------
# Phase 3 — clientKey + multi-broker split totals
# ---------------------------------------------------------------------------

def test_batch_route_client_key_echoed_in_results(
    app_with_mock_bloomberg, make_order_record,
):
    """When items send `clientKey`, results must echo that key (not orderId)."""
    app, bloomberg = app_with_mock_bloomberg
    bloomberg._orders["50"] = make_order_record(
        "50", price=200.0, lastPrice=200.0, remainingQuantity=1000,
    )
    client = TestClient(app)
    payload = {
        "template": {"broker": "BB", "orderType": "LIMIT", "timeInForce": "DAY", "price": 200.0},
        "items": [
            {"orderId": "50", "clientKey": "50#0", "override": {"quantity": 400}},
            {"orderId": "50", "clientKey": "50#1", "override": {"quantity": 500, "broker": "MS"}},
        ],
        "dryRun": True,
    }
    resp = client.post("/api/orders/batch-route", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    keys = sorted(item["key"] for item in data["items"])
    assert keys == ["50#0", "50#1"]
    assert data["succeeded"] == 2


def test_batch_route_split_oversum_blocks_all_destinations(
    app_with_mock_bloomberg, make_order_record,
):
    """Sum of split quantities exceeds remaining → every destination BLOCKED."""
    app, bloomberg = app_with_mock_bloomberg
    bloomberg._orders["60"] = make_order_record(
        "60", price=200.0, lastPrice=200.0, remainingQuantity=1000,
    )
    client = TestClient(app)
    payload = {
        "template": {"broker": "BB", "orderType": "LIMIT", "timeInForce": "DAY", "price": 200.0},
        "items": [
            {"orderId": "60", "clientKey": "60#0", "override": {"quantity": 700}},
            {"orderId": "60", "clientKey": "60#1", "override": {"quantity": 600, "broker": "MS"}},
        ],
        "dryRun": True,
    }
    resp = client.post("/api/orders/batch-route", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["blocked"] == 2
    assert data["succeeded"] == 0
    for item in data["items"]:
        assert item["status"] == "BLOCKED"
        assert "exceeds available capacity" in item["message"]


def test_batch_route_split_within_limit_streams_success(
    app_with_mock_bloomberg, make_order_record,
):
    """Sum of split quantities within remaining → both destinations submit."""
    app, bloomberg = app_with_mock_bloomberg
    bloomberg._orders["70"] = make_order_record(
        "70", price=200.0, lastPrice=200.0, remainingQuantity=1000,
    )
    counter = {"n": 0}

    async def route_side_effect(req):
        counter["n"] += 1
        return {"success": True, "orderId": req.orderId, "routeId": 7000 + counter["n"]}

    bloomberg.route_order.side_effect = route_side_effect
    client = TestClient(app)
    payload = {
        "template": {"broker": "BB", "orderType": "LIMIT", "timeInForce": "DAY", "price": 200.0},
        "items": [
            {"orderId": "70", "clientKey": "70#0", "override": {"quantity": 400}},
            {"orderId": "70", "clientKey": "70#1", "override": {"quantity": 500, "broker": "MS"}},
        ],
        "dryRun": False,
    }
    with client.stream("POST", "/api/orders/batch-route", json=payload) as resp:
        assert resp.status_code == 200
        lines = [json.loads(l) for l in resp.iter_lines() if l.strip()]

    item_lines = [l for l in lines if "summary" not in l]
    summary = next(l for l in lines if "summary" in l)["summary"]
    assert sorted(item["key"] for item in item_lines) == ["70#0", "70#1"]
    assert all(item["status"] == "SUCCESS" for item in item_lines)
    assert summary["succeeded"] == 2
    assert bloomberg.route_order.await_count == 2

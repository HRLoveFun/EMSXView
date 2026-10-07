"""S2 (031) — confirm_proposal 接入 pre-trade 合规测试。

锁死行为：建议确认入口与单笔路由入口（orders_crud.route_order）执行同一
compliance 口径——notional 超上限（USD_NOTIONAL_MAX=49,000,000）必须拦截，
边界内放行；订单不在缓存时与 orders_crud 同口径跳过检查直接路由。
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schemas import Order, OrderSide, OrderStatus, OrderType, TimeInForce


def _make_order(order_id: str, price: float) -> Order:
    """构造指定限价的 WORKING 订单（notional = price × quantity）。"""
    return Order(
        id=order_id,
        symbol="AAPL US Equity",
        side=OrderSide.BUY,
        status=OrderStatus.WORKING,
        orderType=OrderType.LIMIT,
        quantity=100,
        filledQuantity=0,
        remainingQuantity=100,
        price=price,
        timeInForce=TimeInForce.DAY,
        account="ACCT1",
        trader="TRADER1",
        createdAt="2026-10-07T09:30:00",
        updatedAt="2026-10-07T09:30:00",
        currency="USD",
        exchange="US",
        fxRate=1.0,
        lastPrice=price,
    )


@pytest.fixture
def confirm_app(monkeypatch):
    """工厂 fixture：注入指定订单缓存，返回 (client, bloomberg, route_plans 模块)。"""
    def _build(order: Order | None):
        monkeypatch.setenv("BYPASS_AUTH", "true")
        monkeypatch.setenv("JWT_SECRET", "testsecret")

        import importlib

        import deps
        importlib.reload(deps)
        from routers import route_plans as route_plans_router
        importlib.reload(route_plans_router)

        bloomberg = MagicMock()
        bloomberg._orders = {order.id: order} if order else {}
        bloomberg._data_lock = threading.Lock()
        bloomberg.route_order = AsyncMock(return_value={"success": True, "routeId": 9001})

        app = FastAPI()
        app.state.bloomberg_service = bloomberg
        app.include_router(route_plans_router.router)
        return TestClient(app), bloomberg, route_plans_router

    return _build


def _create_plan_and_apply(client: TestClient, order_id: str) -> list[dict]:
    """创建 AUTO BROKER_SPLIT 计划并对订单 apply，返回生成的建议列表。"""
    resp = client.post("/api/route-plans", json={
        "name": "compliance-check",
        "matchMarket": "US",
        "activationMode": "AUTO",
        "splitType": "BROKER_SPLIT",
        "allocations": [
            {"broker": "CSFB", "allocationType": "PERCENTAGE", "allocationValue": 100.0},
        ],
    })
    assert resp.status_code == 200, resp.text
    plan_id = resp.json()["data"]["id"]

    resp = client.post("/api/route-engine/apply/" + order_id, params={"plan_id": plan_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True, resp.json()
    return resp.json()["data"]


def test_confirm_blocked_above_notional_max(confirm_app):
    """49,000,001 USD 建议确认：必须被 NOTIONAL_TOO_LARGE 拦截，不下单。"""
    # price=490,000.01 × qty=100 → 49,000,001 > 49M
    client, bloomberg, _ = confirm_app(_make_order("2001", 490_000.01))
    proposals = _create_plan_and_apply(client, "2001")
    assert len(proposals) == 1

    resp = client.post(f"/api/sub-order-proposals/{proposals[0]['id']}/confirm")
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["message"] == "Pre-trade compliance check failed"
    assert any(v["code"] == "NOTIONAL_TOO_LARGE" for v in detail["violations"])
    # 拦截后不得触碰下单适配器
    bloomberg.route_order.assert_not_awaited()


def test_confirm_allowed_at_notional_max(confirm_app):
    """49,000,000 USD（== 上限，非 '>'）：放行并提交路由。"""
    client, bloomberg, _ = confirm_app(_make_order("2002", 490_000.00))
    proposals = _create_plan_and_apply(client, "2002")

    resp = client.post(f"/api/sub-order-proposals/{proposals[0]['id']}/confirm")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True, body
    bloomberg.route_order.assert_awaited_once()


def test_confirm_skips_check_when_order_not_cached(confirm_app):
    """订单不在订阅缓存：与 orders_crud.route_order 同口径跳过检查直接路由。"""
    client, bloomberg, route_plans_router = confirm_app(None)
    # 白盒注入一条待确认建议（apply 依赖订单在缓存，无法走端点生成）
    route_plans_router._proposals[1] = {
        "id": 1,
        "parent_order_id": "3001",
        "broker": "CSFB",
        "quantity": 100,
        "status": "PENDING_CONFIRM",
        "order_type": "LIMIT",
        "limit_price": 490_000.00,
        "tif": "DAY",
        "created_at": "2026-10-07T09:30:00+00:00",
        "updated_at": "2026-10-07T09:30:00+00:00",
    }

    resp = client.post("/api/sub-order-proposals/1/confirm")
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    bloomberg.route_order.assert_awaited_once()

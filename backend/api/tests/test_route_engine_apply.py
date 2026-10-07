"""S1 (030) — apply_route_engine 链路回归测试。

锁死行为：RouteEngine 与内存仓库适配器（_engine_repo）的异步契约。
修复前 _engine_repo 为同步 staticmethod，引擎对返回值执行 await 抛 TypeError，
apply 端点被 except 吞成通用错误（success=False）；修复后返回真实 proposals。
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


# ---------------------------------------------------------------------------
# 测试 fixture —— 绕过 auth，注入 mock Bloomberg 适配器（内存缓存一条订单）
# ---------------------------------------------------------------------------


@pytest.fixture
def apply_app(monkeypatch):
    """构建挂载 route_plans 路由器的最小 FastAPI app；reload 重置模块级内存态。"""
    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")

    import importlib

    import deps
    importlib.reload(deps)
    from routers import route_plans as route_plans_router
    importlib.reload(route_plans_router)

    order = Order(
        id="1001",
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
        createdAt="2026-10-07T09:30:00",
        updatedAt="2026-10-07T09:30:00",
        currency="USD",
        exchange="US",
        fxRate=1.0,
        lastPrice=200.0,
    )

    bloomberg = MagicMock()
    bloomberg._orders = {"1001": order}
    bloomberg._data_lock = threading.Lock()
    bloomberg.route_order = AsyncMock(return_value={"success": True, "routeId": 9001})

    app = FastAPI()
    app.state.bloomberg_service = bloomberg
    app.include_router(route_plans_router.router)
    return TestClient(app)


def _create_plan(client: TestClient, payload: dict) -> dict:
    """创建路由计划并断言成功。"""
    resp = client.post("/api/route-plans", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True, body
    return body["data"]


# ---------------------------------------------------------------------------
# apply 端点 —— 计划 → 建议链路
# ---------------------------------------------------------------------------


def test_apply_time_schedule_generates_proposals(apply_app):
    """AUTO + TIME_SCHEDULE 计划：apply 应生成 numSlices 条待确认建议。"""
    plan = _create_plan(apply_app, {
        "name": "twap-auto",
        "matchMarket": "US",
        "activationMode": "AUTO",
        "splitType": "TIME_SCHEDULE",
        "scheduleType": "TWAP",
        "numSlices": 4,
        "defaultStartOffsetMin": 1,
    })
    resp = apply_app.post("/api/route-engine/apply/1001", params={"plan_id": plan["id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True, body
    assert len(body["data"]) == 4
    assert all(p["status"] == "PENDING_CONFIRM" for p in body["data"])
    assert all(p["parentOrderId"] == "1001" for p in body["data"])


def test_apply_broker_split_uses_allocations(apply_app):
    """AUTO + BROKER_SPLIT 计划：allocations 按百分比切分剩余量。"""
    plan = _create_plan(apply_app, {
        "name": "broker-auto",
        "matchMarket": "US",
        "activationMode": "AUTO",
        "splitType": "BROKER_SPLIT",
        "allocations": [
            {"broker": "CSFB", "allocationType": "PERCENTAGE", "allocationValue": 60.0},
            {"broker": "JPM", "allocationType": "PERCENTAGE", "allocationValue": 40.0},
        ],
    })
    resp = apply_app.post("/api/route-engine/apply/1001", params={"plan_id": plan["id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True, body
    assert len(body["data"]) == 2
    assert {p["broker"] for p in body["data"]} == {"CSFB", "JPM"}
    quantities = {p["broker"]: p["quantity"] for p in body["data"]}
    assert quantities == {"CSFB": 600, "JPM": 400}


def test_apply_auto_match_without_plan_id(apply_app):
    """不带 plan_id：AUTO 模式按 match criteria 自动匹配并生成建议。"""
    _create_plan(apply_app, {
        "name": "auto-match",
        "matchMarket": "US",
        "activationMode": "AUTO",
        "splitType": "TIME_SCHEDULE",
        "scheduleType": "TWAP",
        "numSlices": 3,
        "defaultStartOffsetMin": 1,
    })
    resp = apply_app.post("/api/route-engine/apply/1001")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True, body
    assert len(body["data"]) == 3


def test_generated_proposals_listed_as_pending(apply_app):
    """apply 产生的建议应出现在 /api/sub-order-proposals 列表（PENDING_CONFIRM）。"""
    _create_plan(apply_app, {
        "name": "list-check",
        "matchMarket": "US",
        "activationMode": "AUTO",
        "splitType": "TIME_SCHEDULE",
        "scheduleType": "TWAP",
        "numSlices": 2,
        "defaultStartOffsetMin": 1,
    })
    resp = apply_app.post("/api/route-engine/apply/1001")
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True

    listing = apply_app.get("/api/sub-order-proposals")
    assert listing.status_code == 200, listing.text
    data = listing.json()["data"]
    assert len(data) == 2
    assert all(p["status"] == "PENDING_CONFIRM" for p in data)


def test_apply_order_not_in_cache_fails(apply_app):
    """订单不在订阅缓存：apply 返回 404，不触发引擎。"""
    resp = apply_app.post("/api/route-engine/apply/9999")
    assert resp.status_code == 404

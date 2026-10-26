"""A02（审计 H2）— 下单前检查收敛测试。

锁死行为：
1. 四个下单入口对同一「被白名单拒绝」的订单给出一致结论
   （单笔 400；批量逐条 BLOCKED）；
2. 同日同券商反向单在 batch-route 路径被拦；
3. WARN 不阻断（记录后放行）；
4. 单笔路由补齐策略注册表层（此前缺失）；
5. 无入口绕过 pre_trade_checks 直接调用检查函数（见 boundaries 用例）。
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

from platform_data.contracts import (  # noqa: E402
    ACCESS_POLICY_VERSION,
    BrokerMarketPolicy,
    FractionalSharePolicy,
    PolicyBundle,
    PolicyViolation,
    TraderMarketPolicy,
    TraderPortfolioPolicy,
)
from routers import orders_crud, route_plans  # noqa: E402
from schemas import Order, OrderSide, OrderStatus, OrderType, TimeInForce  # noqa: E402
from services import access_policy_service, order_compliance_service  # noqa: E402
from services import pre_trade_checks as ptc  # noqa: E402
from services import remaining_quantity_service  # noqa: E402


def _order(order_id: str = "1001", *, side: OrderSide = OrderSide.BUY, remaining: int = 100) -> Order:
    return Order(
        id=order_id,
        symbol="AAPL US Equity",
        side=side,
        status=OrderStatus.WORKING,
        orderType=OrderType.LIMIT,
        quantity=remaining,
        filledQuantity=0,
        remainingQuantity=remaining,
        price=200.0,
        timeInForce=TimeInForce.DAY,
        account="ACCT1",
        portfolio="PF1",
        trader="TRADER1",
        createdAt="2026-10-26T09:30:00",
        updatedAt="2026-10-26T09:30:00",
        currency="USD",
        exchange="US",
        fxRate=1.0,
        lastPrice=200.0,
    )


@pytest.fixture(autouse=True)
def _isolate_checks(monkeypatch):
    """订单合规不落库：订阅源给剩余量，运营库查询返回空。"""

    async def _no_projection(order_id):
        return None

    async def _no_fills(order_id, broker):
        return 0

    monkeypatch.setattr(remaining_quantity_service, "_projection_remaining", _no_projection)
    monkeypatch.setattr(order_compliance_service, "executed_on_broker", _no_fills)


@pytest.fixture
def bloomberg():
    service = MagicMock()
    service._orders = {"1001": _order()}
    service._routes = {}
    service._data_lock = threading.Lock()
    service.route_order = AsyncMock(return_value={"success": True, "routeId": 9001})
    service.get_terminal_trader_name = MagicMock(return_value=None)
    return service


@pytest.fixture
def client(bloomberg):
    app = FastAPI()
    app.state.bloomberg_service = bloomberg
    app.include_router(orders_crud.router)
    app.include_router(route_plans.router)
    return TestClient(app)


@pytest.fixture
def policy(monkeypatch):
    """已配置准入策略：US 只允许 EQ-AAA。"""
    bundle = PolicyBundle(
        trader_markets=TraderMarketPolicy(traders={"TRADER1": frozenset({"US"})}),
        trader_portfolios=TraderPortfolioPolicy(traders={"TRADER1": frozenset({"*"})}),
        broker_markets=BrokerMarketPolicy(markets={"US": frozenset({"EQ-AAA"})}),
        fractional_shares=FractionalSharePolicy(markets={"US": True}),
        version=ACCESS_POLICY_VERSION,
        loaded_at="2026-10-26T00:00:00",
        configured=True,
    )
    monkeypatch.setattr(access_policy_service, "load_policy_bundle", lambda path=None: bundle)
    return bundle


def _route_payload(broker: str) -> dict:
    return {
        "orderId": "1001",
        "broker": broker,
        "quantity": 100,
        "orderType": "LIMIT",
        "price": 200.0,
        "timeInForce": "DAY",
    }


def _batch_payload(broker: str, *, dry_run: bool = True) -> dict:
    return {
        "template": {
            "broker": broker,
            "orderType": "LIMIT",
            "timeInForce": "DAY",
            "price": 200.0,
        },
        "items": [{"orderId": "1001", "override": {"quantity": 100}}],
        "dryRun": dry_run,
    }


def _proposal(proposal_id: int, broker: str) -> dict:
    return {
        "id": proposal_id,
        "status": "PENDING_CONFIRM",
        "parent_order_id": "1001",
        "broker": broker,
        "quantity": 100,
        "order_type": "LIMIT",
        "limit_price": 200.0,
        "strategy_params": {},
        "updated_at": "2026-10-26T09:30:00",
    }


def test_four_entries_blocked_by_access_policy(client, policy, bloomberg, monkeypatch):
    """同一被白名单拒绝的订单：四入口一致拒绝。"""
    # 单笔路由 → 400
    single = client.post("/api/orders/route", json=_route_payload("EQ-ZZZ"))
    assert single.status_code == 400
    assert any(v["code"] == "BROKER_MARKET_NOT_ALLOWED" for v in single.json()["detail"]["violations"])

    # 批量路由（dry-run）→ 逐条 BLOCKED
    batch = client.post("/api/orders/batch-route", json=_batch_payload("EQ-ZZZ"))
    assert batch.status_code == 200
    item = batch.json()["data"]["items"][0]
    assert item["status"] == "BLOCKED"
    assert any(v["code"] == "BROKER_MARKET_NOT_ALLOWED" for v in item["violations"])

    # 单笔确认 → 400
    monkeypatch.setitem(route_plans._proposals, 9001, _proposal(9001, "EQ-ZZZ"))
    confirm = client.post("/api/sub-order-proposals/9001/confirm")
    assert confirm.status_code == 400
    assert any(v["code"] == "BROKER_MARKET_NOT_ALLOWED" for v in confirm.json()["detail"]["violations"])

    # 批量确认 → NDJSON 逐条 BLOCKED（不中断整批）
    monkeypatch.setitem(route_plans._proposals, 9002, _proposal(9002, "EQ-ZZZ"))
    with client.stream(
        "POST", "/api/sub-order-proposals/batch-confirm", json={"proposalIds": [9002]}
    ) as response:
        assert response.status_code == 200
        lines = [json.loads(line) for line in response.iter_lines() if line.strip()]
    assert lines[0]["status"] == "BLOCKED"
    assert "BROKER_MARKET_NOT_ALLOWED" in json.dumps(lines[0]["message"])

    bloomberg.route_order.assert_not_awaited()


def test_batch_route_blocked_by_reverse_order(client, policy, bloomberg, monkeypatch):
    """同日同券商反向单：batch-route 路径必须拦截（此前完全缺失）。"""
    bloomberg._orders = {
        "1001": _order("1001", side=OrderSide.SELL, remaining=200),
        "2002": _order("2002", side=OrderSide.BUY, remaining=0),
    }

    async def _executed(order_id, broker):
        return 300 if order_id == "2002" else 0

    monkeypatch.setattr(order_compliance_service, "executed_on_broker", _executed)
    payload = _batch_payload("EQ-AAA")
    payload["items"][0]["override"]["quantity"] = 100

    response = client.post("/api/orders/batch-route", json=payload)
    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["status"] == "BLOCKED"
    assert any(v["code"] == "REVERSE_ORDER_BROKER_BLOCKED" for v in item["violations"])
    bloomberg.route_order.assert_not_awaited()


def test_warn_does_not_block(client, bloomberg, monkeypatch):
    """WARN（转人工提示）不阻断：路由照常提交。"""
    monkeypatch.setattr(
        access_policy_service,
        "evaluate_access",
        lambda parent_order, proposal: [
            PolicyViolation(
                code="BROKER_MARKET_NOT_ALLOWED",
                message="manual review required",
                manual_review_required=True,
            )
        ],
    )
    response = client.post("/api/orders/route", json=_route_payload("EQ-ZZZ"))
    assert response.status_code == 200
    bloomberg.route_order.assert_awaited_once()


def test_single_route_enforces_strategy_layer(client, bloomberg, monkeypatch):
    """单笔路由此前缺策略注册表层：A02 后应阻断错误参数。"""
    monkeypatch.setattr(
        ptc,
        "validate_route_submission",
        lambda broker, strategy, params, **kwargs: SimpleNamespace(
            errors=["VWAP: 必填参数 pctVol 缺失"], warnings=[]
        ),
    )
    response = client.post("/api/orders/route", json=_route_payload("EQ-AAA"))
    assert response.status_code == 400
    codes = [v["code"] for v in response.json()["detail"]["violations"]]
    assert "STRATEGY_PARAM_INVALID" in codes
    bloomberg.route_order.assert_not_awaited()


def test_clean_order_passes_all_entries(client, policy, bloomberg):
    """允许的券商：单笔与批量都放行。"""
    single = client.post("/api/orders/route", json=_route_payload("EQ-AAA"))
    assert single.status_code == 200

    batch = client.post("/api/orders/batch-route", json=_batch_payload("EQ-AAA"))
    assert batch.status_code == 200
    assert batch.json()["data"]["items"][0]["status"] == "SUCCESS"

"""050 — batch 路径授权预检 + 审计回填 + GET 噪音治理测试。

演练 D3 实测发现的三个缺口：batch 路径未接入授权校验（大单无授权放行）、
BATCH_ROUTE 审计永远 PENDING、只读 GET 端点刷审计噪音。
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import deps


def _fake_provider(intents, parents, payloads) -> MagicMock:
    provider = MagicMock()
    provider.is_active = True
    provider.persist_audit_event = AsyncMock(return_value=True)
    provider.update_audit_result = AsyncMock(return_value=True)
    provider.load_authorizations = AsyncMock(return_value=intents)
    provider.run_parent_child_op = AsyncMock(
        side_effect=lambda op, *a, **k: parents if op == "list_active_parents" else None
    )
    provider.load_orders = AsyncMock(return_value=list(payloads.values()))
    return provider


_INTENT = [{
    "id": 1, "symbol": "HLMA LN Equity", "side": "SELL", "portfolio": None,
    "target_quantity": 100, "status": "ACTIVE", "note": None, "updated_at": "",
}]
_PAYLOADS = {"5019350": {"id": "5019350", "symbol": "HLMA LN Equity", "side": "SELL", "portfolio": "UK"}}
_PARENTS = []


def _parent(order_id: str, symbol: str) -> object:
    return SimpleNamespace(
        id=1, order_id=order_id, symbol=symbol, side="SELL", portfolio="UK",
        remainingQuantity=807, price=None, lastPrice=26.0,
        currency="GBP", exchange="LN", fxRate=1.3245, roundLotSize=None,
        status="NEW",
    )


@pytest.fixture
def batch_env(monkeypatch):
    """端点级 fixture：mock provider + fake stream，返回 (client, deps)。"""
    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")

    import importlib

    import deps
    deps_mod = importlib.reload(deps)
    from routers import orders_crud
    orders_crud_mod = importlib.reload(orders_crud)
    from schemas import ApiResponse  # noqa: F401

    bloomberg = MagicMock()
    bloomberg._orders = {"5019350": _parent("5019350", "HLMA LN Equity")}
    bloomberg._data_lock = threading.Lock()
    bloomberg.get_orders = AsyncMock(return_value=[])
    bloomberg.get_terminal_trader_name = MagicMock(return_value=None)

    app = FastAPI()
    app.state.bloomberg_service = bloomberg
    app.include_router(orders_crud_mod.router)
    return TestClient(app), bloomberg, deps_mod, orders_crud_mod


def test_batch_exceeded_blocks_whole_request(batch_env, monkeypatch):
    """授权 exceeded：整体 403（audit fail），不进入流提交。"""
    client, bloomberg, deps_mod, _ = batch_env
    intents = [{
        "id": 1, "symbol": "HLMA LN Equity", "side": "SELL", "portfolio": None,
        "target_quantity": 100, "status": "ACTIVE", "note": None, "updated_at": "",
    }]
    provider = _fake_provider(intents, [], {})
    monkeypatch.setattr(deps_mod, "_repo_provider", provider)

    req = {"items": [{"orderId": "5019350"}], "template": {"broker": "EQ-SEB", "orderType": "LIMIT", "price": 20.0}, "dryRun": False}
    resp = client.post("/api/orders/batch-route", json=req)
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["message"].startswith("PM authorization limit exceeded")
    assert detail["blocked"][0]["remainingQuantity"] == 100
    provider.update_audit_result.assert_awaited_once_with(
        correlation_id=provider.persist_audit_event.await_args.kwargs["correlation_id"],
        result="fail",
    )


def test_batch_not_covered_proceeds_and_audits(batch_env, monkeypatch):
    """not_covered：warning 放行；流结束后审计回填 ok。"""
    client, bloomberg, deps_mod, orders_crud_mod = batch_env
    provider = _fake_provider([], [], {})  # 无授权 → not_covered
    monkeypatch.setattr(deps_mod, "_repo_provider", provider)

    # fake 流：绕开真实 batch_route_service 提交
    async def _fake_stream(*args, **kwargs):
        yield '{"key": "1", "status": "SUCCESS"}'

    monkeypatch.setattr(orders_crud_mod.batch_route_service, "stream_batch_route", _fake_stream)

    req = {"items": [{"orderId": "5019350"}], "template": {}, "dryRun": False}
    resp = client.post("/api/orders/batch-route", json=req)
    assert resp.status_code == 200, resp.text
    assert "SUCCESS" in resp.text

    cid = provider.persist_audit_event.await_args.kwargs["correlation_id"]
    provider.update_audit_result.assert_awaited_once_with(correlation_id=cid, result="ok")


def test_get_orders_no_longer_writes_audit(batch_env, monkeypatch):
    """只读 GET /api/orders 不再写审计（噪音治理）。"""
    client, bloomberg, deps_mod, _ = batch_env
    provider = _fake_provider([], [], {})
    monkeypatch.setattr(deps_mod, "_repo_provider", provider)

    resp = client.get("/api/orders")
    assert resp.status_code == 200, resp.text
    actions = [
        c.kwargs.get("action") for c in provider.persist_audit_event.await_args_list
    ]
    assert "GET_ORDERS" not in actions

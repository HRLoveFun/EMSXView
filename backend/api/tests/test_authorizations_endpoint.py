"""049 — /api/authorizations 正常路径端点测试（演练实测 500 的回归锁）。

实测发现：list_authorizations 对 async 的 provider.load_orders 少 await
（'coroutine' object is not iterable）——此前测试只覆盖了 provider 不可用
的降级分支，正常路径漏测。本文件补齐：fake provider 全链路。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import deps


def _fake_provider() -> MagicMock:
    provider = MagicMock()
    provider.is_active = True
    provider.load_authorizations = AsyncMock(return_value=[{
        "id": 1, "symbol": "AAPL US Equity", "side": "BUY", "portfolio": None,
        "target_quantity": 600_000, "status": "ACTIVE",
        "note": None, "updated_at": "2026-10-09T10:00:00+00:00",
    }])
    parents = [SimpleNamespaceParent(1)]
    provider.run_parent_child_op = AsyncMock(
        side_effect=lambda op, *a, **k: parents if op == "list_active_parents" else None
    )
    provider.load_orders = AsyncMock(return_value=[
        {"id": "1001", "symbol": "AAPL US Equity", "side": "BUY", "portfolio": "TECH"},
    ])
    return provider


class SimpleNamespaceParent:
    """list_active_parents 返回的父单最小对象。"""

    def __init__(self, parent_id: int):
        import types
        from datetime import datetime, timezone
        self.__dict__.update(
            id=parent_id, order_id="1001", target_quantity=300_000,
            filled_quantity=100_000, status="ACTIVE",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )


@pytest.fixture
def authz_client(monkeypatch):
    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")

    import importlib

    import deps
    importlib.reload(deps)
    from routers import authorizations as authorizations_router
    importlib.reload(authorizations_router)

    app = FastAPI()
    app.include_router(authorizations_router.router)
    return TestClient(app), authorizations_router, deps


def test_list_authorizations_happy_path(authz_client, monkeypatch):
    """正常路径：授权 + 剩余量计算完整返回（演练实测 500 的回归锁）。"""
    client, _, deps_mod = authz_client
    provider = _fake_provider()
    monkeypatch.setattr(deps_mod, "_repo_provider", provider)

    resp = client.get("/api/authorizations")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert len(body["data"]) == 1
    view = body["data"][0]
    assert view["targetQuantity"] == 600_000
    assert view["committedQuantity"] == 300_000
    assert view["remainingQuantity"] == 300_000


def test_create_authorization_happy_path(authz_client, monkeypatch):
    """创建授权：provider.create_authorization 被调用并返回 id。"""
    client, _, deps_mod = authz_client
    provider = _fake_provider()
    provider.create_authorization = AsyncMock(return_value=7)
    monkeypatch.setattr(deps_mod, "_repo_provider", provider)

    resp = client.post("/api/authorizations", json={
        "symbol": "MSFT US Equity", "side": "BUY", "targetQuantity": 100_000,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["id"] == 7
    provider.create_authorization.assert_awaited_once()

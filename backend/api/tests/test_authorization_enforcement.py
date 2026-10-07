"""S13 (043) — 下单入口授权硬校验测试。

锁死行为：exceeded 硬拒绝（403 且不触达下单适配器）；not_covered 放行并
告警；持久化不可用跳过检查；ok 放行。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import deps
from services.authorization_service import enforce_for_order


def _fake_provider(intents, parents, payloads) -> MagicMock:
    provider = MagicMock()
    provider.is_active = True
    # 审计两阶段（S6）在授权检查之前执行——必须返回协程
    provider.persist_audit_event = AsyncMock(return_value=True)
    provider.update_audit_result = AsyncMock(return_value=True)
    provider.load_authorizations = AsyncMock(return_value=intents)
    provider.run_parent_child_op = AsyncMock(
        side_effect=lambda op, *a, **k: parents if op == "list_active_parents" else None
    )
    provider.load_orders = AsyncMock(return_value=list(payloads.values()))
    return provider


_INTENT = [{
    "id": 1, "symbol": "AAPL US Equity", "side": "BUY", "portfolio": None,
    "target_quantity": 600_000, "status": "ACTIVE", "note": None, "updated_at": "",
}]
_PARENTS = [SimpleNamespace(id=1, order_id="1001", target_quantity=550_000,
                            filled_quantity=100_000, status="ACTIVE")]
_PAYLOADS = {"1001": {"id": "1001", "symbol": "AAPL US Equity", "side": "BUY", "portfolio": "TECH"}}


@pytest.mark.asyncio
async def test_enforce_exceeded():
    provider = _fake_provider(_INTENT, _PARENTS, _PAYLOADS)
    result = await enforce_for_order(
        provider, symbol="AAPL US Equity", side="BUY", portfolio="TECH",
        additional_qty=60_000,
    )
    assert result["outcome"] == "exceeded"
    assert result["remainingQuantity"] == 50_000


@pytest.mark.asyncio
async def test_enforce_not_covered_when_no_intents():
    provider = _fake_provider([], [], {})
    result = await enforce_for_order(
        provider, symbol="AAPL US Equity", side="BUY", portfolio=None,
        additional_qty=100,
    )
    assert result["outcome"] == "not_covered"


@pytest.mark.asyncio
async def test_enforce_skipped_without_provider():
    assert await enforce_for_order(None, symbol="A", side="BUY", portfolio=None,
                                   additional_qty=1) is None
    inactive = MagicMock()
    inactive.is_active = False
    assert await enforce_for_order(inactive, symbol="A", side="BUY", portfolio=None,
                                   additional_qty=1) is None


@pytest.mark.asyncio
async def test_route_order_blocked_on_exceeded(monkeypatch):
    """端点集成：route_order 超授权 403 且不调用下单适配器。"""
    import importlib
    import config as config_mod

    provider = _fake_provider(_INTENT, _PARENTS, _PAYLOADS)

    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")
    importlib.reload(deps)
    from routers import orders_crud
    orders_crud = importlib.reload(orders_crud)

    # orders_crud 经 from deps import get_repo_provider 绑定原函数，
    # 该函数读 deps._repo_provider 全局——必须在 reload 之后注入
    # （reload 会把 _repo_provider 重置为 None）
    monkeypatch.setattr(deps, "_repo_provider", provider)

    parent_order = SimpleNamespace(
        symbol="AAPL US Equity", side="BUY", portfolio="TECH",
        price=200.0, lastPrice=200.0, currency="USD", exchange="US",
        fxRate=1.0, roundLotSize=None, remainingQuantity=1000,
    )
    bloomberg = MagicMock()
    bloomberg._orders = {"1001": parent_order}
    bloomberg._data_lock = threading.Lock()
    bloomberg.route_order = AsyncMock(return_value={"success": True, "routeId": 1})

    from schemas import RouteOrderRequest
    req = RouteOrderRequest(
        orderId="1001", broker="CSFB", quantity=60_000,
        orderType="LIMIT", price=200.0, timeInForce="DAY",
    )
    with pytest.raises(HTTPException) as exc_info:
        await orders_crud.route_order(req, {"sub": "t1"}, bloomberg)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["outcome"] == "exceeded"
    bloomberg.route_order.assert_not_awaited()

"""S6 (036) — 审计结果真实化测试。

锁死行为：审计事件两阶段语义——发起记 PENDING（不再预写 ok），
完成后按 correlation_id 回填 ok / fail / unknown（请求超时）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# import 链触发 config.settings 校验，须在首次 import 前备好环境变量
os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import deps
from schemas import RouteOrderRequest


def _fake_provider() -> MagicMock:
    """伪造 RepositoryProvider：捕获 persist/update 调用序列。"""
    provider = MagicMock()
    provider.is_active = True
    provider.persist_audit_event = AsyncMock(return_value=True)
    provider.update_audit_result = AsyncMock(return_value=True)
    return provider


@pytest.fixture
def provider(monkeypatch) -> MagicMock:
    fake = _fake_provider()
    monkeypatch.setattr(deps, "_repo_provider", fake)
    return fake


def _reload(mod_name: str):
    """reload 模块以重置其模块级内存态（proposals/locks 等）。"""
    import importlib
    module = importlib.import_module(mod_name)
    return importlib.reload(module)


@pytest.mark.asyncio
async def test_audit_log_defaults_to_pending(provider):
    """audit_log 默认记录 PENDING——操作尚未完成不得宣称 ok。"""
    audit_log = deps.audit_log
    audit_log("SOME_ACTION", "t1", {"k": "v"}, correlation_id="cid-1")
    await asyncio.sleep(0)

    provider.persist_audit_event.assert_awaited_once()
    kwargs = provider.persist_audit_event.await_args.kwargs
    assert kwargs["result"] == "PENDING"
    assert kwargs["correlation_id"] == "cid-1"
    provider.update_audit_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_audit_result_updates_by_correlation(provider):
    """audit_result 按 correlation_id 回填真实结果。"""
    deps.audit_result("cid-2", "unknown")
    await asyncio.sleep(0)

    provider.update_audit_result.assert_awaited_once_with(
        correlation_id="cid-2", result="unknown"
    )
    provider.persist_audit_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_proposal_records_pending_then_ok(provider):
    """建议确认成功流：persist(PENDING) → update(ok)。"""
    import threading
    from routers import route_plans as rp
    importlib_reload = _reload("routers.route_plans")
    rp = importlib_reload

    rp._proposals[1] = {
        "id": 1,
        "parent_order_id": "1001",
        "broker": "CSFB",
        "quantity": 100,
        "status": "PENDING_CONFIRM",
        "order_type": "LIMIT",
        "limit_price": 200.0,
        "tif": "DAY",
        "created_at": "2026-10-07T09:30:00+00:00",
        "updated_at": "2026-10-07T09:30:00+00:00",
    }
    bloomberg = MagicMock()
    bloomberg._orders = {}
    bloomberg._data_lock = threading.Lock()
    bloomberg.route_order = AsyncMock(return_value={"success": True, "routeId": 9001})

    result = await rp.confirm_proposal(1, {"sub": "t1"}, bloomberg)
    assert result.success is True
    await asyncio.sleep(0)

    provider.persist_audit_event.assert_awaited_once()
    assert provider.persist_audit_event.await_args.kwargs["result"] == "PENDING"
    cid = provider.persist_audit_event.await_args.kwargs["correlation_id"]
    assert cid is not None
    provider.update_audit_result.assert_awaited_once_with(correlation_id=cid, result="ok")


@pytest.mark.asyncio
async def test_route_order_timeout_records_unknown(provider):
    """route_order 超时（504）：结果未知——券商可能已收到订单。"""
    orders_crud = _reload("routers.orders_crud")

    bloomberg = MagicMock()
    bloomberg._orders = {}
    import threading as _threading
    bloomberg._data_lock = _threading.Lock()
    bloomberg.route_order = AsyncMock(side_effect=HTTPException(504, "Bloomberg request timed out"))

    req = RouteOrderRequest(
        orderId="1001", broker="CSFB", quantity=100,
        orderType="LIMIT", price=490_000.01, timeInForce="DAY",
    )
    with pytest.raises(HTTPException) as exc_info:
        await orders_crud.route_order(req, {"sub": "t1"}, bloomberg)
    assert exc_info.value.status_code == 504
    await asyncio.sleep(0)

    cid = provider.persist_audit_event.await_args.kwargs["correlation_id"]
    provider.update_audit_result.assert_awaited_once_with(correlation_id=cid, result="unknown")


@pytest.mark.asyncio
async def test_route_order_compliance_fail(provider):
    """route_order 风控拦截：结果 fail。"""
    orders_crud = _reload("routers.orders_crud")

    # 超限订单：100 × 490,000.01 = 49,000,001 USD > 49M 上限
    parent_order = SimpleNamespace(
        price=490_000.01, lastPrice=490_000.01,
        currency="USD", exchange="US", fxRate=1.0, roundLotSize=None,
    )
    bloomberg = MagicMock()
    bloomberg._orders = {"1001": parent_order}
    import threading as _threading
    bloomberg._data_lock = _threading.Lock()

    req = RouteOrderRequest(
        orderId="1001", broker="CSFB", quantity=100,
        orderType="LIMIT", price=490_000.01, timeInForce="DAY",
    )
    with pytest.raises(HTTPException) as exc_info:
        await orders_crud.route_order(req, {"sub": "t1"}, bloomberg)
    assert exc_info.value.status_code == 400
    await asyncio.sleep(0)

    cid = provider.persist_audit_event.await_args.kwargs["correlation_id"]
    provider.update_audit_result.assert_awaited_once_with(correlation_id=cid, result="fail")

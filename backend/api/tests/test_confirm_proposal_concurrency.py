"""S3 (032) — confirm_proposal 并发幂等测试。

锁死行为：同一建议并发确认只产生一次有效提交（per-proposal 锁 +
CONFIRMING 中间态）；风控拦截/提交失败回退 PENDING_CONFIRM 可重试。
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 本文件直接调用路由协程（不经 TestClient/Depends），但 import 链会触发
# config.settings 校验，须在首次 import 前备好环境变量
os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

from schemas import ApiResponse


def _reload_router():
    """reload route_plans 模块以重置模块级内存态（plans/proposals/locks）。"""
    import importlib

    from routers import route_plans as route_plans_router
    return importlib.reload(route_plans_router)


def _proposal(proposal_id: int = 1) -> dict:
    """构造一条待确认建议（最小字段集）。"""
    return {
        "id": proposal_id,
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


def _bloomberg(route_side_effect=None) -> MagicMock:
    bloomberg = MagicMock()
    bloomberg._orders = {}
    bloomberg._data_lock = threading.Lock()
    if route_side_effect is not None:
        bloomberg.route_order = AsyncMock(side_effect=route_side_effect)
    else:
        bloomberg.route_order = AsyncMock(return_value={"success": True, "routeId": 9001})
    return bloomberg


@pytest.mark.asyncio
async def test_concurrent_confirm_single_submission():
    """并发确认同一建议：恰好一次 route_order、一次成功、一次被拒。"""
    router = _reload_router()
    router._proposals[1] = _proposal()

    async def _slow_route(req):
        # 模拟下单适配器延迟，放大 check-then-act 竞态窗口
        await asyncio.sleep(0.05)
        return {"success": True, "routeId": 9001}

    bloomberg = _bloomberg(route_side_effect=_slow_route)

    results = await asyncio.gather(
        router.confirm_proposal(1, {"sub": "t1"}, bloomberg),
        router.confirm_proposal(1, {"sub": "t2"}, bloomberg),
        return_exceptions=True,
    )

    succeeded = [r for r in results if isinstance(r, ApiResponse) and r.success]
    rejected = [r for r in results if isinstance(r, HTTPException)]
    assert len(succeeded) == 1, results
    assert len(rejected) == 1, results
    assert "SUBMITTED" in rejected[0].detail
    # 竞态若未修复，两个协程都会通过状态检查 → route_order 被调用两次
    bloomberg.route_order.assert_awaited_once()
    assert router._proposals[1]["status"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_confirm_retries_after_submission_failure():
    """提交失败回退 PENDING_CONFIRM，重试可成功。"""
    router = _reload_router()
    router._proposals[1] = _proposal()

    bloomberg = _bloomberg(route_side_effect=RuntimeError("connection lost"))
    result = await router.confirm_proposal(1, {"sub": "t1"}, bloomberg)
    assert result.success is False
    assert router._proposals[1]["status"] == "PENDING_CONFIRM"

    # 重试：适配器恢复正常
    bloomberg.route_order = AsyncMock(return_value={"success": True, "routeId": 9002})
    result = await router.confirm_proposal(1, {"sub": "t1"}, bloomberg)
    assert result.success is True
    assert router._proposals[1]["status"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_confirm_retries_after_compliance_block():
    """风控拦截回退 PENDING_CONFIRM（未被通用异常处理吞掉），可重试。"""
    router = _reload_router()
    proposal = _proposal()
    proposal["limit_price"] = 490_000.01  # qty=100 → 49,000,001 USD，超上限
    router._proposals[1] = proposal

    bloomberg = MagicMock()
    bloomberg._orders = {
        "1001": SimpleNamespaceOrder(price=490_000.01, lastPrice=490_000.01),
    }
    bloomberg._data_lock = threading.Lock()
    bloomberg.route_order = AsyncMock(return_value={"success": True, "routeId": 9001})

    with pytest.raises(HTTPException) as exc_info:
        await router.confirm_proposal(1, {"sub": "t1"}, bloomberg)
    assert exc_info.value.status_code == 400
    assert any(v["code"] == "NOTIONAL_TOO_LARGE" for v in exc_info.value.detail["violations"])
    assert router._proposals[1]["status"] == "PENDING_CONFIRM"
    bloomberg.route_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_conflicting_state_returns_409():
    """崩溃遗留的 CONFIRMING 中间态：确认返回 409，reject 同样 409。"""
    router = _reload_router()
    proposal = _proposal()
    proposal["status"] = "CONFIRMING"
    router._proposals[1] = proposal

    bloomberg = _bloomberg()
    with pytest.raises(HTTPException) as exc_info:
        await router.confirm_proposal(1, {"sub": "t1"}, bloomberg)
    assert exc_info.value.status_code == 409
    bloomberg.route_order.assert_not_awaited()

    with pytest.raises(HTTPException) as exc_info:
        await router.reject_proposal(1, {"sub": "t1"})
    assert exc_info.value.status_code == 409
    assert router._proposals[1]["status"] == "CONFIRMING"


class SimpleNamespaceOrder:
    """风控检查所需的 parent_order 最小属性对象（缺省字段返回 None/默认）。"""

    def __init__(self, price: float, lastPrice: float):
        self.price = price
        self.lastPrice = lastPrice
        self.currency = "USD"
        self.exchange = "US"
        self.fxRate = 1.0
        self.roundLotSize = None

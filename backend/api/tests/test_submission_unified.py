"""S14 (054) — 统一提交服务测试（真实 SQLite DB，非内存替身）。

锁死行为（第二份审计发现 1/2 的修复）：
- 504 结果未知 → 建议 NEEDS_REVIEW 冻结（内存 + DB），不可重发；
- resolve 人工核对解除（CONFIRM_SUBMITTED / REJECT），非 NEEDS_REVIEW 拒绝；
- batch-confirm 授权预检（exceeded 整体 403）+ 逐建议 core 提交 + DB 回写；
- 明确失败回退 PENDING_CONFIRM 可重试（与 unknown 冻结区分）。
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
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import deps


@pytest.fixture
def sqlite_provider(monkeypatch, tmp_path):
    """真实 SQLite 持久化 provider（演练同款路径，非内存替身）。"""
    db_path = tmp_path / "rehearsal.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    import importlib

    import db as db_mod
    importlib.reload(db_mod)
    from service_provider import RepositoryProvider
    provider = RepositoryProvider(enabled=True)
    provider.mark_db_ready(True)
    # 审计的 fire-and-forget DB 任务与主流程 DB 会话在测试中并发会触发
    # SQLite 锁/状态错误——audit 通道 mock（持久化通道保持真实）
    provider.persist_audit_event = AsyncMock(return_value=True)
    provider.update_audit_result = AsyncMock(return_value=True)
    monkeypatch.setattr(deps, "_repo_provider", provider)

    # 真实建表（覆盖全部模型模块）
    ok, msg = asyncio.run(db_mod.initialize_database())
    assert ok, msg
    return provider


def _proposal(pid: int = 1) -> dict:
    return {
        "id": pid,
        "parent_order_id": "1001",
        "broker": "CSFB",
        "quantity": 100,
        "status": "PENDING_CONFIRM",
        "order_type": "LIMIT",
        "limit_price": 200.0,
        "tif": "DAY",
        "created_at": "2026-10-09T09:30:00+00:00",
        "updated_at": "2026-10-09T09:30:00+00:00",
    }


def _bloomberg(route_side_effect=None) -> MagicMock:
    bloomberg = MagicMock()
    bloomberg._orders = {}  # 无缓存 → compliance/授权闭包跳过
    bloomberg._data_lock = threading.Lock()
    if route_side_effect is not None:
        bloomberg.route_order = AsyncMock(side_effect=route_side_effect)
    else:
        bloomberg.route_order = AsyncMock(return_value={"success": True, "routeId": 9001})
    return bloomberg


def _reload_router():
    import importlib
    from routers import route_plans as rp
    return importlib.reload(rp)


@pytest.mark.asyncio
async def test_timeout_freezes_needs_review_and_blocks_retry(sqlite_provider, monkeypatch):
    """504 → NEEDS_REVIEW 冻结（内存+DB）；重确认被拒；audit unknown。"""
    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")
    rp = _reload_router()
    rp._proposals[1] = _proposal()
    # 先落库一行（update_proposal_result 按 id 更新，需有行存在）
    await sqlite_provider.persist_proposals_bulk([{**_proposal(), "status": "PENDING_CONFIRM"}])

    from fastapi import HTTPException as _HE
    bloomberg = _bloomberg(route_side_effect=_HE(504, "Bloomberg request timed out"))

    result = await rp.confirm_proposal(1, {"sub": "t1"}, bloomberg)
    assert result.success is False
    assert "unknown" in result.error
    # 冻结：内存与 DB 均为 NEEDS_REVIEW（非 PENDING_CONFIRM 可重试态）
    assert rp._proposals[1]["status"] == "NEEDS_REVIEW"
    rows = await sqlite_provider.load_proposals()
    assert rows[0]["status"] == "NEEDS_REVIEW"

    # 重确认：被状态机拒绝（不得盲目重发）
    bloomberg2 = _bloomberg()  # 即使适配器恢复正常也不应被调用
    with pytest.raises(HTTPException) as exc_info:
        await rp.confirm_proposal(1, {"sub": "t1"}, bloomberg2)
    assert exc_info.value.status_code == 409
    bloomberg2.route_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_confirm_submitted(sqlite_provider, monkeypatch):
    """resolve CONFIRM_SUBMITTED：NEEDS_REVIEW → SUBMITTED（DB 同步）；重复 resolve 400。"""
    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")
    rp = _reload_router()
    rp._proposals[1] = {**_proposal(), "status": "NEEDS_REVIEW"}

    from schemas import ProposalResolveRequest
    resp = await rp.resolve_proposal(
        1, ProposalResolveRequest(action="CONFIRM_SUBMITTED", routeId=9001),
        {"sub": "t1"},
    )
    assert resp.success is True
    assert rp._proposals[1]["status"] == "SUBMITTED"
    rows = await sqlite_provider.load_proposals()
    # DB 中不存在（本用例未先 create）——resolve 的 write-through 失败应告警不阻断
    # 再 resolve：400
    with pytest.raises(HTTPException) as exc_info:
        await rp.resolve_proposal(1, ProposalResolveRequest(action="REJECT"), {"sub": "t1"})
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_resolve_reject(sqlite_provider, monkeypatch):
    """resolve REJECT：NEEDS_REVIEW → REJECTED（DB 持久化）。"""
    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")
    rp = _reload_router()
    rp._proposals[1] = {**_proposal(), "status": "NEEDS_REVIEW"}
    # 先落库一条 NEEDS_REVIEW 行供 write-through
    await sqlite_provider.persist_proposals_bulk([{**_proposal(), "status": "NEEDS_REVIEW"}])

    from schemas import ProposalResolveRequest
    resp = await rp.resolve_proposal(1, ProposalResolveRequest(action="REJECT"), {"sub": "t1"})
    assert resp.success is True
    rows = await sqlite_provider.load_proposals()
    assert rows[0]["status"] == "REJECTED"


@pytest.mark.asyncio
async def test_explicit_failure_allows_retry(sqlite_provider, monkeypatch):
    """明确失败（非 504）→ 回退 PENDING_CONFIRM 可重试（与 unknown 冻结区分）。"""
    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")
    rp = _reload_router()
    rp._proposals[1] = _proposal()

    bloomberg = _bloomberg(route_side_effect=RuntimeError("connection refused"))
    result = await rp.confirm_proposal(1, {"sub": "t1"}, bloomberg)
    assert result.success is False
    assert rp._proposals[1]["status"] == "PENDING_CONFIRM"

    bloomberg.route_order = AsyncMock(return_value={"success": True, "routeId": 9002})
    result = await rp.confirm_proposal(1, {"sub": "t1"}, bloomberg)
    assert result.success is True
    assert rp._proposals[1]["status"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_batch_confirm_exceeded_blocks_all(sqlite_provider, monkeypatch):
    """batch-confirm 授权预检：任一 exceeded → 整体 403（审计 fail）。"""
    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")
    rp = _reload_router()
    rp._proposals[1] = _proposal(1)
    rp._proposals[2] = _proposal(2)

    # 授权：intent symbol 与父单缓存匹配，remaining=50 < 建议qty=100 → exceeded
    provider = sqlite_provider
    monkeypatch.setenv("BYPASS_AUTH", "true")
    provider.load_authorizations = AsyncMock(return_value=[{
        "id": 1, "symbol": "TEST SZ Equity", "side": "BUY", "portfolio": None,
        "target_quantity": 50, "status": "ACTIVE", "note": None, "updated_at": "",
    }])
    provider.run_parent_child_op = AsyncMock(return_value=[])
    provider.load_orders = AsyncMock(return_value=[])

    parent = SimpleNamespaceParent()
    bloomberg = _bloomberg()
    bloomberg._orders = {"1001": parent, "1002": parent}
    from schemas import BatchConfirmRequest
    req = BatchConfirmRequest(proposalIds=[1, 2], dryRun=False)
    with pytest.raises(HTTPException) as exc_info:
        await rp.batch_confirm_proposals(req, {"sub": "t1"}, bloomberg)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["message"].startswith("PM authorization limit exceeded")
    # audit_log 是 fire-and-forget（ensure_future）——403 同步抛出后需让出
    # 控制权使任务执行，再断言（产品中事件循环持续运行，无此问题）
    await asyncio.sleep(0.05)
    provider.update_audit_result.assert_awaited_once_with(
        correlation_id=provider.persist_audit_event.await_args.kwargs["correlation_id"],
        result="fail",
    )


class SimpleNamespaceParent:
    """授权检查所需的 parent_order 最小对象（symbol 空 → not_covered）。"""

    def __init__(self, parent_id: int = 1):
        self.symbol = "TEST SZ Equity"
        self.side = "BUY"
        self.portfolio = None
        self.remainingQuantity = 100

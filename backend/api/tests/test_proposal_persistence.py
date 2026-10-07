"""S8 (038) — 建议持久化幂等测试。

锁死行为：确认状态机 write-through（先落库再应答）、幂等键 =
SubOrderProposal 数据库主键、重启后从 DB 恢复且已 SUBMITTED 的建议
拒绝重复确认；持久化不可用时回退内存 id（既有行为）。
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

# import 链触发 config.settings 校验，须在首次 import 前备好环境变量
os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import deps


class FakeProposalDB:
    """内存字典模拟 DB——持久化行为的可观测替身。"""

    is_active = True

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self._next_id = 1

    async def persist_proposals_bulk(self, proposals):
        ids = []
        for p in proposals:
            pid = self._next_id
            self._next_id += 1
            row = dict(p)
            row["id"] = pid  # DB 行自带主键（真实行为）
            self.rows[pid] = row
            ids.append(pid)
        return ids

    async def update_proposal_result(self, proposal_id, *, status, route_id=None,
                                     confirmed_at=None, submitted_at=None, updated_at=None):
        row = self.rows.get(proposal_id)
        if row is None:
            return False
        row["status"] = status
        row["route_id"] = route_id
        return True

    async def load_proposals(self, limit=2000):
        return [dict(r) for r in self.rows.values()]


def _reload_router():
    import importlib
    from routers import route_plans as rp
    return importlib.reload(rp)


def _proposal_dict() -> dict:
    return {
        "route_plan_id": 1,
        "parent_order_id": "1001",
        "broker": "CSFB",
        "quantity": 100,
        "order_type": "LIMIT",
        "limit_price": 200.0,
        "tif": "DAY",
        "status": "PENDING_CONFIRM",
    }


def _bloomberg() -> MagicMock:
    bloomberg = MagicMock()
    bloomberg._orders = {}
    bloomberg._data_lock = threading.Lock()
    bloomberg.route_order = AsyncMock(return_value={"success": True, "routeId": 9001})
    return bloomberg


@pytest.mark.asyncio
async def test_create_persists_and_uses_db_id(monkeypatch):
    """创建建议：先落库拿幂等键，内存 id 与 DB 主键一致。"""
    fake = FakeProposalDB()
    monkeypatch.setattr(deps, "get_repo_provider", lambda: fake)
    rp = _reload_router()

    created = await rp._create_proposals([_proposal_dict()])
    assert created[0]["id"] == 1
    assert list(fake.rows.keys()) == [1]
    assert rp._proposals[1]["id"] == 1


@pytest.mark.asyncio
async def test_confirm_writes_through_before_response(monkeypatch):
    """确认成功：状态迁移落库（SUBMITTED），响应前完成。"""
    fake = FakeProposalDB()
    monkeypatch.setattr(deps, "get_repo_provider", lambda: fake)
    rp = _reload_router()
    created = await rp._create_proposals([_proposal_dict()])
    pid = created[0]["id"]

    await rp.confirm_proposal(pid, {"sub": "t1"}, _bloomberg())
    assert fake.rows[pid]["status"] == "SUBMITTED"
    assert fake.rows[pid]["route_id"] == 9001
    assert rp._proposals[pid]["status"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_restart_recovery_and_duplicate_confirm_rejected(monkeypatch):
    """模拟重启：reload 清空内存 → 从 DB 恢复 → 已 SUBMITTED 拒绝重复确认。"""
    fake = FakeProposalDB()
    monkeypatch.setattr(deps, "get_repo_provider", lambda: fake)
    rp = _reload_router()
    created = await rp._create_proposals([_proposal_dict()])
    pid = created[0]["id"]
    await rp.confirm_proposal(pid, {"sub": "t1"}, _bloomberg())

    # ── 重启：内存清空，从 DB 恢复 ──
    rp = _reload_router()
    restored = await rp.init_proposals_from_db(fake)
    assert restored == 1
    assert rp._proposals[pid]["status"] == "SUBMITTED"

    # 恢复后重复确认：被状态机拒绝（幂等）
    with pytest.raises(HTTPException) as exc_info:
        await rp.confirm_proposal(pid, {"sub": "t1"}, _bloomberg())
    assert exc_info.value.status_code == 400
    assert "SUBMITTED" in exc_info.value.detail


@pytest.mark.asyncio
async def test_fallback_to_inmemory_id_without_provider(monkeypatch):
    """持久化不可用（provider=None）：回退内存自增 id——既有行为不变。"""
    monkeypatch.setattr(deps, "get_repo_provider", lambda: None)
    rp = _reload_router()

    created = await rp._create_proposals([_proposal_dict()])
    assert created[0]["id"] == 1  # 内存自增
    assert rp._proposals[1]["status"] == "PENDING_CONFIRM"


@pytest.mark.asyncio
async def test_reject_writes_through(monkeypatch):
    """拒绝：REJECTED 状态落库。"""
    fake = FakeProposalDB()
    monkeypatch.setattr(deps, "get_repo_provider", lambda: fake)
    rp = _reload_router()
    created = await rp._create_proposals([_proposal_dict()])
    pid = created[0]["id"]

    resp = await rp.reject_proposal(pid, {"sub": "t1"})
    assert resp.success is True
    assert fake.rows[pid]["status"] == "REJECTED"

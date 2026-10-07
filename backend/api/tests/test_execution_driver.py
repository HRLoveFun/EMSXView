"""S9 (039) — 执行驱动循环、成交反馈、重启恢复测试。

锁死行为（离线可测部分）：
- 到期切片提交（submit 注入式——未接线时不提交且 ERROR 可见）；
- 成交反馈按路由 id 回填切片并汇总父单成交量；人工路由不命中；
- 重启恢复重建内存 store 与调度器 registry。
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# import 链触发 config.settings 校验，须在首次 import 前备好环境变量
os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

from models.parent_child_orders import SliceStatus
from services.algo_scheduler import _registry, register_active_execution
from services.execution_driver import ExecutionDriver


class FakeRepo:
    """内存替身——与 ParentChildRepository 同 duck-type 的子集。"""

    def __init__(self):
        self.parents: dict[int, object] = {}
        self.slices: dict[int, object] = {}
        self._next_slice_id = 1

    def add_parent(self, parent_id: int, status: str = "ACTIVE"):
        self.parents[parent_id] = SimpleNamespace(
            id=parent_id, status=status, filled_quantity=0,
            target_quantity=1000, created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def add_slice(self, parent_id: int, slice_index: int = 0, planned: int = 100,
                  scheduled_start=None, status: str = "PENDING", route_id: int | None = None):
        sid = self._next_slice_id
        self._next_slice_id += 1
        self.slices[sid] = SimpleNamespace(
            id=sid, parent_id=parent_id, slice_index=slice_index,
            planned_quantity=planned, filled_quantity=0,
            scheduled_start=scheduled_start, scheduled_end=None,
            status=status, route_id=route_id,
        )
        return sid

    async def list_due_slices(self, now, limit=100):
        return [
            s for s in self.slices.values()
            if s.status == "PENDING" and s.scheduled_start and s.scheduled_start <= now
        ]

    async def get_parent(self, parent_id):
        return self.parents.get(parent_id)

    async def update_slice_status(self, slice_id, status, **kwargs):
        s = self.slices[slice_id]
        s.status = status
        for k, v in kwargs.items():
            setattr(s, k, v)

    async def get_slice_by_route_id(self, route_id):
        return next((s for s in self.slices.values() if s.route_id == route_id), None)

    async def update_slice_fill(self, slice_id, filled_quantity, status):
        s = self.slices[slice_id]
        s.filled_quantity = filled_quantity
        s.status = status

    async def list_slices_for_parent(self, parent_id):
        return [s for s in self.slices.values() if s.parent_id == parent_id]

    async def update_parent_filled(self, parent_id, filled_quantity):
        p = self.parents.get(parent_id)
        if p:
            p.filled_quantity = filled_quantity


def _driver(repo, submit=None) -> ExecutionDriver:
    return ExecutionDriver(repo=repo, submit_slice=submit, tick_interval=5.0)


@pytest.mark.asyncio
async def test_tick_submits_due_slices():
    """到期 PENDING 切片被提交：状态 SENT + route_id 回写。"""
    repo = FakeRepo()
    repo.add_parent(1, status="ACTIVE")
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    repo.add_slice(1, slice_index=0, planned=100, scheduled_start=past)

    submitted_args: list = []

    async def fake_submit(parent, slice_row):
        submitted_args.append((parent.id, slice_row.id))
        return 9001

    driver = _driver(repo, submit=fake_submit)
    count = await driver.tick()

    assert count == 1
    assert submitted_args == [(1, 1)]
    assert repo.slices[1].status == SliceStatus.SENT.value
    assert repo.slices[1].route_id == 9001


@pytest.mark.asyncio
async def test_tick_without_submit_logs_error(caplog):
    """未接线 submit：不提交且 ERROR 可见（绝不静默自动下单）。"""
    repo = FakeRepo()
    repo.add_parent(1, status="ACTIVE")
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    repo.add_slice(1, slice_index=0, planned=100, scheduled_start=past)

    with caplog.at_level(logging.ERROR, logger="services.execution_driver"):
        count = await _driver(repo).tick()

    assert count == 0
    assert repo.slices[1].status == SliceStatus.PENDING.value
    assert any("no submit function" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_tick_skips_future_and_nonactive_parents():
    """未到期切片、非 ACTIVE 父单：不提交。"""
    repo = FakeRepo()
    repo.add_parent(1, status="ACTIVE")
    repo.add_parent(2, status="PAUSED")
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    repo.add_slice(1, slice_index=0, planned=100, scheduled_start=future)  # 未到期
    repo.add_slice(2, slice_index=0, planned=100, scheduled_start=past)    # 父单 PAUSED

    calls: list = []

    async def fake_submit(parent, slice_row):
        calls.append(parent.id)
        return 9002

    count = await _driver(repo, submit=fake_submit).tick()
    assert count == 0
    assert calls == []


@pytest.mark.asyncio
async def test_record_fill_updates_slice_and_parent():
    """成交反馈：切片回填 + 父单汇总；未命中路由返回 False。"""
    repo = FakeRepo()
    repo.add_parent(1)
    repo.add_slice(1, slice_index=0, planned=100, route_id=9001)
    repo.add_slice(1, slice_index=1, planned=100, route_id=9002)

    driver = _driver(repo)

    # 部分成交
    assert await driver.record_fill(9001, 60) is True
    assert repo.slices[1].status == SliceStatus.WORKING.value
    assert repo.slices[1].filled_quantity == 60
    assert repo.parents[1].filled_quantity == 60

    # 补足至全量
    assert await driver.record_fill(9001, 100) is True
    assert repo.slices[1].status == SliceStatus.FILLED.value

    # 人工路由（不属于任何切片）
    assert await driver.record_fill(7777, 50) is False
    assert repo.parents[1].filled_quantity == 100


@pytest.mark.asyncio
async def test_restart_recovery_restores_registry():
    """重启恢复：内存 store 与调度器 registry 从 DB 行重建。"""
    import importlib
    from routers import orders_execution as oe
    oe = importlib.reload(oe)

    # 模拟 DB 行（ACTIVE 父单 + 2 切片，最后切片 index=1）
    parent = SimpleNamespace(
        id=7, status="ACTIVE", filled_quantity=0, target_quantity=1000,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    slices = [
        SimpleNamespace(id=11, parent_id=7, slice_index=0, planned_quantity=100,
                        filled_quantity=100, scheduled_start=None, scheduled_end=None,
                        status="FILLED", route_id=1),
        SimpleNamespace(id=12, parent_id=7, slice_index=1, planned_quantity=100,
                        filled_quantity=0, scheduled_start=None, scheduled_end=None,
                        status="PENDING", route_id=None),
    ]

    provider = MagicMock()
    provider.parent_child_available.return_value = True

    async def run_op(op_name, *args, **kwargs):
        if op_name == "list_active_parents":
            return [parent]
        if op_name == "list_slices_for_parent":
            return slices
        return None

    provider.run_parent_child_op = run_op

    # restore_active_executions 经 deps.get_repo_provider() 取 provider
    import deps
    import pytest as _pytest
    _pytest.MonkeyPatch().setattr(deps, "_repo_provider", provider)

    restored = await oe.restore_active_executions()
    assert restored == 1
    assert oe._parent_store[7] is parent
    assert len(oe._slices_store[7]) == 2
    # registry 重建：提交进度 = 最后切片 index + 1
    entry = _registry.get(7)
    assert entry is not None
    assert entry.next_slice_index == 2
    assert entry.is_paused is False

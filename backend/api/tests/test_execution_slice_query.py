"""S5 (035) — 父子单执行切片查询测试。

锁死行为：create 后查询返回一致切片数（修复前 _MockParentChildRepo 切片
存实例本地列表，查询端点新建实例 → 0 切片但状态 ACTIVE）；
持久化配置开启时模拟仓库产生告警。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def exec_app(monkeypatch):
    """挂载 orders_execution 路由器；reload 重置模块级内存态与调度器注册表。"""
    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")

    import importlib

    import deps
    importlib.reload(deps)
    from services import algo_scheduler
    importlib.reload(algo_scheduler)
    from routers import orders_execution as orders_execution_router
    importlib.reload(orders_execution_router)

    app = FastAPI()
    app.include_router(orders_execution_router.router)
    return TestClient(app), orders_execution_router


def _create_payload(order_id: str = "1001", num_slices: int = 4) -> dict:
    return {
        "orderId": order_id,
        "scheduleType": "TWAP",
        "targetQuantity": 1000,
        "numSlices": num_slices,
        "startTime": "2026-10-07T09:30:00",
        "endTime": "2026-10-07T15:30:00",
        "broker": "CSFB",
        "urgency": "MEDIUM",
    }


def test_create_then_query_returns_same_slices(exec_app):
    """create 4 切片 → get 返回 totalSlices=4 且状态 ACTIVE（修复前为 0）。"""
    client, _ = exec_app
    resp = client.post("/api/executions", json=_create_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True, body
    parent_id = body["data"]["parentId"]

    detail = client.get(f"/api/executions/{parent_id}")
    assert detail.status_code == 200, detail.text
    state = detail.json()["data"]
    assert state["totalSlices"] == 4, state
    assert state["status"] == "ACTIVE"
    assert state["isRunning"] is True


def test_query_across_new_repo_instance(exec_app):
    """查询端点新建 repo 实例后切片仍可见（模块级存储跨实例共享）。"""
    client, oe = exec_app
    resp = client.post("/api/executions", json=_create_payload("1002", 3))
    parent_id = resp.json()["data"]["parentId"]

    # 模拟任意端点新建 repo 实例后的直接查询
    import asyncio
    repo = oe._MockParentChildRepo(parent=object())
    children = asyncio.run(repo.list_slices_for_parent(parent_id))
    assert len(children) == 3
    # 切片 id 全局唯一且带 parent_id 归属
    assert all(getattr(c, "parent_id") == parent_id for c in children)
    assert len({getattr(c, "id") for c in children}) == 3


def test_multiple_parents_slices_isolated(exec_app):
    """两个 parent 的切片按 parent_id 分桶互不混淆。"""
    client, _ = exec_app
    resp1 = client.post("/api/executions", json=_create_payload("2001", 4))
    resp2 = client.post("/api/executions", json=_create_payload("2002", 2))
    pid1 = resp1.json()["data"]["parentId"]
    pid2 = resp2.json()["data"]["parentId"]

    state1 = client.get(f"/api/executions/{pid1}").json()["data"]
    state2 = client.get(f"/api/executions/{pid2}").json()["data"]
    assert state1["totalSlices"] == 4
    assert state2["totalSlices"] == 2


def test_mock_repo_warns_when_persistence_enabled(exec_app, monkeypatch, caplog):
    """ENABLE_DB_PERSISTENCE=true 时创建执行：记录 MOCK 仓库告警。"""
    client, oe = exec_app
    monkeypatch.setattr(oe.settings, "ENABLE_DB_PERSISTENCE", True)

    with caplog.at_level(logging.WARNING, logger=oe.__name__):
        resp = client.post("/api/executions", json=_create_payload("3001", 2))
    assert resp.status_code == 200
    assert any("MOCK in-memory repo" in r.message for r in caplog.records)

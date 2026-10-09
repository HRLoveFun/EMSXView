"""S15 (055) — 路由计划持久化 + 演示账号收紧测试（真实 SQLite DB）。

锁死行为（第二份审计发现 4/5 的修复）：
- route plan create/update/delete write-through（建议表 FK 锚点闭环）；
- 重启恢复：init_route_plans_from_db 重建内存缓存；
- 配置用户存在时 DEMO_USERS 不再兜底（fail-closed）。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import deps


@pytest.fixture
def sqlite_provider(monkeypatch, tmp_path):
    db_path = tmp_path / "rehearsal.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    import db as db_mod
    db_mod = importlib.reload(db_mod)
    from service_provider import RepositoryProvider
    provider = RepositoryProvider(enabled=True)
    provider.mark_db_ready(True)
    # 审计 fire-and-forget mock（避免与主流程 DB 并发干扰，见 054 教训）
    provider.persist_audit_event = AsyncMock(return_value=True)
    provider.update_audit_result = AsyncMock(return_value=True)
    monkeypatch.setattr(deps, "_repo_provider", provider)

    ok, msg = asyncio.run(db_mod.initialize_database())
    assert ok, msg
    return provider


def _reload_router():
    from routers import route_plans as rp
    return importlib.reload(rp)


def _plan_create(name: str = "p1"):
    from schemas import RoutePlanCreate
    return RoutePlanCreate(
        name=name, matchMarket="US", activationMode="AUTO",
        splitType="TIME_SCHEDULE", scheduleType="TWAP", numSlices=2,
    )


@pytest.mark.asyncio
async def test_create_persists_and_uses_db_id(sqlite_provider, monkeypatch):
    """create：计划落库取 DB 主键（建议 FK 锚点闭环）。"""
    monkeypatch.setenv("BYPASS_AUTH", "true")
    rp = _reload_router()

    resp = await rp.create_route_plan(_plan_create("persist-plan"), {"sub": "admin"})
    assert resp.success is True
    pid = resp.data["id"]

    rows = await sqlite_provider.load_route_plans()
    assert len(rows) == 1
    assert rows[0]["id"] == pid
    assert rows[0]["name"] == "persist-plan"
    assert rp._plans[pid]["id"] == pid


@pytest.mark.asyncio
async def test_update_delete_write_through(sqlite_provider, monkeypatch):
    """update/delete 落库同步。"""
    from schemas import RoutePlanUpdate
    monkeypatch.setenv("BYPASS_AUTH", "true")
    rp = _reload_router()
    resp = await rp.create_route_plan(_plan_create("to-update"), {"sub": "admin"})
    pid = resp.data["id"]

    upd = RoutePlanUpdate(description="updated-desc", priority=5)
    await rp.update_route_plan(pid, upd, {"sub": "admin"})
    rows = await sqlite_provider.load_route_plans()
    assert rows[0]["description"] == "updated-desc"

    await rp.delete_route_plan(pid, {"sub": "admin"})
    rows = await sqlite_provider.load_route_plans()
    assert rows == []


@pytest.mark.asyncio
async def test_restart_recovery_restores_plans(sqlite_provider, monkeypatch):
    """重启恢复：reload 清内存 → init_route_plans_from_db 重建。"""
    monkeypatch.setenv("BYPASS_AUTH", "true")
    rp = _reload_router()
    await rp.create_route_plan(_plan_create("recover-me"), {"sub": "admin"})

    rp = _reload_router()  # 模拟重启：内存清空
    assert rp._plans == {}
    restored = await rp.init_route_plans_from_db(sqlite_provider)
    assert restored == 1
    assert list(rp._plans.values())[0]["name"] == "recover-me"


def test_config_users_authoritative(monkeypatch):
    """配置用户存在：DEMO_USERS 不再兜底（fail-closed）——审计发现 5 修复。"""
    import auth as auth_mod
    users = json.dumps([{
        "username": "alice", "password_hash": auth_mod.pwd_context.hash("s3cret"),
        "full_name": "Alice", "role": "trader",
    }])
    monkeypatch.setattr(auth_mod._settings, "EMSXVIEW_USERS", users)
    auth = importlib.reload(auth_mod)

    # 配置内用户正常
    assert auth.AuthManager.authenticate_user("alice", "s3cret") is not None
    # demo 管理员被拒绝（配置存在即权威）
    assert auth.AuthManager.authenticate_user("admin", "password") is None
    assert auth.AuthManager.authenticate_user("trader1", "password") is None


def test_empty_config_falls_back_to_demo(monkeypatch):
    """配置为空：回落 DEMO_USERS + WARNING（现状保留，开发友好）。"""
    import auth as auth_mod
    monkeypatch.setattr(auth_mod._settings, "EMSXVIEW_USERS", "")
    auth = importlib.reload(auth_mod)
    assert auth.AuthManager.authenticate_user("admin", "password") is not None

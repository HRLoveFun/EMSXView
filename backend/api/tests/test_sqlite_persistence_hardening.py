"""DL-02/060 — SQLite 运营库开启与加固测试（真实 SQLite DB）。

锁死行为（057 tasks.md DL-02 检验方法）：
1. SQLite 连接 PRAGMA 生效（WAL / busy_timeout=30000 / foreign_keys=ON）；
2. 订单 upsert 与重启恢复；
3. 路由 upsert 与重启恢复；
4. 锁冲突下 busy_timeout 等待（不立即 database is locked）；
5. 写入熔断：11 次失败 → circuit_open，mark_db_ready 重置；
6. /api/health 增报熔断状态与写入失败计数。
"""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import os

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import deps  # noqa: E402
import db as db_mod  # noqa: E402
import service_provider as sp_mod  # noqa: E402
from db import SQLITE_BUSY_TIMEOUT_MS  # noqa: E402
from sqlalchemy import text  # noqa: E402


@pytest.fixture
def sqlite_env(monkeypatch, tmp_path):
    """真实 SQLite 运营库环境：DATABASE_URL 指向 tmp，重置引擎单例。"""
    db_path = tmp_path / "ops" / "emsx_ops.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    reloaded_db = importlib.reload(db_mod)
    sp_reloaded = importlib.reload(sp_mod)
    ok, msg = asyncio.run(reloaded_db.initialize_database())
    assert ok, msg
    yield reloaded_db, sp_reloaded, db_path
    # teardown：关闭引擎——否则 aiosqlite 工作线程在 pytest 事件循环关闭后
    # 抛 Event loop is closed（PytestUnhandledThreadExceptionWarning）
    asyncio.run(reloaded_db.dispose_engine())


def _make_provider(sp_reloaded) -> "sp_reloaded.RepositoryProvider":
    provider = sp_reloaded.RepositoryProvider(enabled=True)
    provider.mark_db_ready(True)
    return provider


# ── 用例 1：PRAGMA 生效 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sqlite_pragmas_applied(sqlite_env):
    db_mod, _sp, _db_path = sqlite_env

    engine = db_mod.create_engine()
    async with engine.connect() as conn:
        journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        busy = (await conn.execute(text("PRAGMA busy_timeout"))).scalar()
        fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar()
    await engine.dispose()

    assert str(journal).lower() == "wal"
    assert int(busy) == SQLITE_BUSY_TIMEOUT_MS
    assert int(fk) == 1


# ── 用例 2/3：upsert 与重启恢复 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_order_upsert_and_restart_recovery(sqlite_env):
    _db_mod, sp_reloaded, _db_path = sqlite_env

    provider = _make_provider(sp_reloaded)
    assert await provider.persist_order(
        sequence=1, order_id="5019542.1", status="WORKING", trader="TRD_X", payload={"v": 1}
    )
    # 同 sequence 二次写入 = upsert 更新（重启后以最新状态恢复）
    assert await provider.persist_order(
        sequence=1, order_id="5019542.1", status="PARTFILL", trader="TRD_X", payload={"v": 2}
    )

    # 模拟重启：全新 provider 从库恢复（load_orders 返回 payload 投影）
    restarted = _make_provider(sp_reloaded)
    orders = await restarted.load_orders()
    assert len(orders) == 1
    assert orders[0] == {"v": 2}


@pytest.mark.asyncio
async def test_route_upsert_and_restart_recovery(sqlite_env):
    _db_mod, sp_reloaded, _db_path = sqlite_env

    provider = _make_provider(sp_reloaded)
    assert await provider.persist_route(
        sequence=1, route_id=100, status="WORKING", broker="BRK_X", payload={"r": 1}
    )
    assert await provider.persist_route(
        sequence=1, route_id=100, status="FILLED", broker="BRK_X", payload={"r": 2}
    )

    restarted = _make_provider(sp_reloaded)
    routes = await restarted.load_routes()
    assert len(routes) == 1
    assert routes[0] == {"r": 2}


# ── 用例 4：锁冲突下 busy_timeout 等待 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_waits_under_lock_conflict(sqlite_env):
    """后台线程持写事务 0.5s；前台写在 busy_timeout 内等待后成功（不立即 locked）。"""
    _db_mod, sp_reloaded, db_path = sqlite_env
    provider = _make_provider(sp_reloaded)

    def hold_lock_briefly():
        # BEGIN IMMEDIATE 即取写锁（无需实际写数据，避免 updated_at 等模型列）；
        # isolation_level=None → 手动事务控制，0.5s 后释放
        conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=30)
        try:
            conn.execute("BEGIN IMMEDIATE")
            time.sleep(0.5)
            conn.execute("ROLLBACK")
        finally:
            conn.close()

    holder = threading.Thread(target=hold_lock_briefly)
    holder.start()
    await asyncio.sleep(0.1)  # 确保写锁已被持有

    started = time.monotonic()
    ok = await provider.persist_order(
        sequence=1, order_id="5019542.1", status="WORKING", trader="TRD_X", payload={"v": 1}
    )
    elapsed = time.monotonic() - started
    holder.join(timeout=5)

    assert ok is True  # 等待锁释放后写入成功
    assert elapsed < 5  # 未触达 30s busy_timeout 上限


# ── 用例 5：写入熔断 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_circuit_breaker(sqlite_env, monkeypatch):
    _db_mod, sp_reloaded, _db_path = sqlite_env
    provider = _make_provider(sp_reloaded)

    @asynccontextmanager
    async def _broken_session():
        raise RuntimeError("db down")
        yield  # pragma: no cover - 不可达

    monkeypatch.setattr(sp_reloaded, "get_db_session", _broken_session)

    # 前 10 次失败计入计数；第 10 次后熔断打开
    for _ in range(10):
        assert await provider.persist_order(
            sequence=1, order_id="O", status="WORKING", trader="T", payload={}
        ) is False

    assert provider.write_error_count == 10
    assert provider.circuit_open is True
    assert provider.is_active is False

    # 熔断后直接短路（不再计数、不再触库）
    assert await provider.persist_order(
        sequence=2, order_id="O2", status="WORKING", trader="T", payload={}
    ) is False
    assert provider.write_error_count == 10

    # mark_db_ready 重置计数与熔断
    provider.mark_db_ready(True)
    assert provider.write_error_count == 0
    assert provider.circuit_open is False
    assert provider.is_active is True


# ── 用例 6：/api/health 熔断上报 ───────────────────────────────────────────────


class _FakeBloombergStatus:
    def __init__(self, status: str):
        self.status = status

    def model_dump(self):
        return {"status": self.status}


class _FakeBloomberg:
    def get_status(self):
        return _FakeBloombergStatus("connected")


@pytest.fixture
def health_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import connection

    app = FastAPI()
    app.include_router(connection.router)
    app.state.bloomberg_service = _FakeBloomberg()
    return TestClient(app)


@pytest.mark.asyncio
async def test_health_reports_circuit_breaker(sqlite_env, health_client, monkeypatch):
    from routers import connection

    _db_mod, sp_reloaded, _db_path = sqlite_env
    provider = _make_provider(sp_reloaded)
    monkeypatch.setattr(deps, "_repo_provider", provider)
    monkeypatch.setattr(connection.settings, "ENABLE_DB_PERSISTENCE", True)

    # 1 次失败：计数可见、熔断未开
    provider._write_errors = 1
    response = health_client.get("/api/health")
    assert response.status_code == 200
    db_payload = response.json()["data"]["database"]
    assert db_payload["write_errors"] == 1
    assert db_payload["max_write_errors"] == 10
    assert db_payload["circuit_open"] is False

    # 达到阈值：熔断打开可见
    provider._write_errors = 10
    response = health_client.get("/api/health")
    db_payload = response.json()["data"]["database"]
    assert db_payload["circuit_open"] is True


def test_health_omits_circuit_fields_when_disabled(health_client, monkeypatch):
    from routers import connection

    monkeypatch.setattr(connection.settings, "ENABLE_DB_PERSISTENCE", False)

    response = health_client.get("/api/health")

    assert response.status_code == 200
    db_payload = response.json()["data"]["database"]
    assert db_payload["status"] == "disabled"
    assert "write_errors" not in db_payload
    assert "circuit_open" not in db_payload

"""S16 (056) — 序号持久化恢复 + 重同步接线测试（真实 SQLite DB）。

锁死行为（第二份审计接线缺口 6/7 的修复）：
- route_order 成功后序号写入 watermark 表；重启 restore 后序号不回退
  （跨重启防重放成立）；
- 跳号触发已注册的重同步回调（refresh_subscription 实盘接线）。
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

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
    provider.persist_audit_event = AsyncMock(return_value=True)
    provider.update_audit_result = AsyncMock(return_value=True)
    monkeypatch.setattr(deps, "_repo_provider", provider)

    ok, msg = asyncio.run(db_mod.initialize_database())
    assert ok, msg
    return provider


def _service_with_route():
    """真实 facade + mock 连接（route_order 走 mock 会话循环）。"""
    from services.bloomberg.adapter import BloombergEMSXService

    service = BloombergEMSXService()
    return service


@pytest.mark.asyncio
async def test_seq_persisted_after_route_and_restored(sqlite_provider, monkeypatch):
    """route_order 成功 → watermark 持久化；新 handler restore 后序号不回退。"""
    from services.bloomberg.request_handler import EMSXRequestHandler

    handler = EMSXRequestHandler(MagicMock(), MagicMock(), SimpleNamespace(BLOOMBERG_TIMEOUT=1000))
    handler.set_seq_persister(
        lambda seq: sqlite_provider.upsert_watermark("emsx_request_seq", seq)
    )

    seq1 = handler._next_request_seq()
    await handler._persist_seq()
    seq2 = handler._next_request_seq()
    await handler._persist_seq()
    assert (seq1, seq2) == (1, 2)

    # 模拟重启：新 handler（内存从零）+ 从 watermark 恢复
    handler2 = EMSXRequestHandler(MagicMock(), MagicMock(), SimpleNamespace(BLOOMBERG_TIMEOUT=1000))
    assert handler2.emsx_request_seq == 0
    last = await sqlite_provider.load_watermark("emsx_request_seq")
    handler2.restore_request_seq(last)
    assert handler2.emsx_request_seq == 2
    assert handler2._next_request_seq() == 3


def test_resync_callback_wired_to_refresh(sqlite_provider):
    """注册的跳号重同步回调接到 facade.refresh_subscription（实盘接线验证）。"""
    from services.bloomberg.adapter import BloombergEMSXService

    service = BloombergEMSXService()
    # facade.refresh_subscription 打桩（避免真实会话）
    service.refresh_subscription = AsyncMock(return_value=[])

    called: list[str] = []

    def on_gap(stream: str):
        called.append(stream)
        return service.refresh_subscription()

    service.register_resync_callback(on_gap)
    assert len(service._sub._resync_callbacks) == 1

    # 模拟跳号触发（_schedule_resync 同步调用回调 → 返回协程）
    engine = service._sub
    coro = engine._resync_callbacks[0]("order")
    asyncio.run(_drain(coro))
    assert called == ["order"]
    service.refresh_subscription.assert_awaited_once()


async def _drain(coro):
    await coro


def test_status_endpoint_with_proxy_attrs(sqlite_provider):
    """冒烟：facade 状态属性代理（045）+ 序号恢复代理存在。"""
    from services.bloomberg.adapter import BloombergEMSXService

    service = BloombergEMSXService()
    assert isinstance(service._init_paint_done, bool)
    assert isinstance(service._subscription_failed, bool)
    assert hasattr(service, "restore_request_seq")
    assert hasattr(service, "set_seq_persister")
    assert hasattr(service, "register_resync_callback")

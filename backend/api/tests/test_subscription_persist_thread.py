"""S4 (034) — 订阅线程持久化/推送 dispatch 测试。

锁死行为：订阅线程调用 _schedule_persist_order/_route 时，DB 写与 WebSocket
广播经注入的主 loop 引用执行（修复前 asyncio.get_event_loop() 在回调线程
抛 RuntimeError 被静默吞掉，持久化与推送整体丢失且无日志）。
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# import 链触发 config.settings 校验，须在首次 import 前备好环境变量
import os
os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import services.bloomberg.subscriptions as subs_mod


def _fake_order(order_id: str = "1001") -> SimpleNamespace:
    """_schedule_persist_order 所需的最小 order 协议对象。"""
    return SimpleNamespace(
        id=order_id,
        status="WORKING",
        trader="TRADER1",
        model_dump=lambda: {"id": order_id, "status": "WORKING"},
    )


def _fake_route() -> SimpleNamespace:
    """_schedule_persist_route 所需的最小 route 协议对象。"""
    return SimpleNamespace(
        sequence=1001,
        routeId=9001,
        status="WORKING",
        broker="CSFB",
        model_dump=lambda: {"sequence": 1001, "routeId": 9001},
    )


def _engine() -> subs_mod.EMSXSubscriptionEngine:
    """构造引擎实例（连接管理器/仓库提供方均为 mock）。"""
    engine = subs_mod.EMSXSubscriptionEngine(MagicMock(), MagicMock())
    engine._repo_provider.persist_order = AsyncMock(return_value=None)
    engine._repo_provider.persist_route = AsyncMock(return_value=None)
    return engine


@pytest.mark.asyncio
async def test_persist_dispatched_to_injected_loop(monkeypatch):
    """注入主 loop 后：persist 与 broadcast 均被执行。"""
    broadcast_order = AsyncMock()
    monkeypatch.setattr(subs_mod.realtime_gw, "broadcast_order", broadcast_order)
    engine = _engine()
    engine.set_main_loop(asyncio.get_running_loop())

    engine._schedule_persist_order(_fake_order())
    await asyncio.sleep(0.1)

    engine._repo_provider.persist_order.assert_awaited_once()
    broadcast_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_persist_dispatched_to_injected_loop(monkeypatch):
    """路由持久化/广播同口径。"""
    broadcast_route = AsyncMock()
    monkeypatch.setattr(subs_mod.realtime_gw, "broadcast_route", broadcast_route)
    engine = _engine()
    engine.set_main_loop(asyncio.get_running_loop())

    engine._schedule_persist_route(_fake_route())
    await asyncio.sleep(0.1)

    engine._repo_provider.persist_route.assert_awaited_once()
    broadcast_route.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_from_background_thread(monkeypatch):
    """真实后台线程调用（blpapi 回调线程场景）：协程仍能回到主 loop 执行。"""
    broadcast_order = AsyncMock()
    monkeypatch.setattr(subs_mod.realtime_gw, "broadcast_order", broadcast_order)
    engine = _engine()
    engine.set_main_loop(asyncio.get_running_loop())

    thread = threading.Thread(target=engine._schedule_persist_order, args=(_fake_order("2002"),))
    thread.start()
    thread.join(timeout=2)
    await asyncio.sleep(0.2)

    engine._repo_provider.persist_order.assert_awaited_once()
    broadcast_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_loop_logs_error_and_drops(monkeypatch, caplog):
    """未注入主 loop：记 ERROR（不静默），persist/broadcast 不执行。"""
    broadcast_order = AsyncMock()
    monkeypatch.setattr(subs_mod.realtime_gw, "broadcast_order", broadcast_order)
    engine = _engine()
    # 不调用 set_main_loop —— 保持 None

    with caplog.at_level(logging.ERROR, logger="main"):
        engine._schedule_persist_order(_fake_order())
        await asyncio.sleep(0.1)

    assert any("Main event loop unavailable" in r.message for r in caplog.records)
    engine._repo_provider.persist_order.assert_not_awaited()
    broadcast_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_failure_is_visible(monkeypatch, caplog):
    """协程执行失败可见化：此前 persist 异常完全静默。"""
    broadcast_order = AsyncMock()
    monkeypatch.setattr(subs_mod.realtime_gw, "broadcast_order", broadcast_order)
    engine = _engine()
    engine._repo_provider.persist_order = AsyncMock(side_effect=RuntimeError("db down"))
    engine.set_main_loop(asyncio.get_running_loop())

    with caplog.at_level(logging.ERROR, logger="main"):
        engine._schedule_persist_order(_fake_order())
        await asyncio.sleep(0.2)

    assert any("Async dispatch failed" in r.message for r in caplog.records)

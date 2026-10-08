"""046 — 成交回填累计语义测试（5.4 实测结论的回归锁）。

实测（GIVN SW Equity 5018201.1）：lastShares=最后一笔成交量（增量），
dayFill=累计成交。调度回填的切片 filled_quantity 语义为累计——
_notify_fill_callbacks 必须传 dayFill，否则多次部分成交会低估累计量。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import services.bloomberg.subscriptions as subs_mod


def _engine_with_capture():
    engine = subs_mod.EMSXSubscriptionEngine(MagicMock(), MagicMock())
    engine.set_main_loop(asyncio.get_running_loop())
    received: list[tuple[int, int]] = []

    async def on_fill(route_id: int, cumulative_qty: int):
        received.append((route_id, cumulative_qty))

    engine.register_fill_callback(on_fill)
    return engine, received


def _route(route_id=1, day_fill=9, last_shares=1):
    return SimpleNamespace(routeId=route_id, dayFill=day_fill, lastShares=last_shares)


@pytest.mark.asyncio
async def test_notify_uses_cumulative_dayfill_not_lastshare():
    """回调收到 dayFill（累计），而非 lastShares（最后一笔）。"""
    engine, received = _engine_with_capture()

    engine._notify_fill_callbacks(_route(day_fill=9, last_shares=1))
    await asyncio.sleep(0.1)

    assert received == [(1, 9)], received


@pytest.mark.asyncio
async def test_partial_fills_deliver_monotonic_cumulative():
    """多次部分成交：回调收到递增的累计值（1 → 9 → 55）。"""
    engine, received = _engine_with_capture()

    # 实测序列（GIVN SW Equity）：三笔成交 1/8/46 股
    for cumulative in (1, 9, 55):
        engine._notify_fill_callbacks(_route(day_fill=cumulative, last_shares=None))
    await asyncio.sleep(0.15)

    assert received == [(1, 1), (1, 9), (1, 55)], received


@pytest.mark.asyncio
async def test_zero_cumulative_skips_dispatch():
    """dayFill=0（无成交的路由更新）：不触发回调。"""
    engine, received = _engine_with_capture()

    engine._notify_fill_callbacks(_route(day_fill=0, last_shares=0))
    await asyncio.sleep(0.1)

    assert received == []


@pytest.mark.asyncio
async def test_missing_route_id_skips_dispatch():
    """无 routeId 的消息：不触发回调、不抛异常。"""
    engine, received = _engine_with_capture()

    engine._notify_fill_callbacks(SimpleNamespace(routeId=None, dayFill=9, lastShares=1))
    await asyncio.sleep(0.1)

    assert received == []

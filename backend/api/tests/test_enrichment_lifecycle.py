"""后台线程生命周期的回归测试（行情富化 + EMSX 订阅）。

缺陷背景（2026-11-11）：`MarketDataEnrichmentService.start()` 每次调用都新建
`_mktdata_thread` 与 `ShadowRunner`，`EMSXSubscriptionEngine.start()` 同样每次
新建 `_sub_thread`，而 `connect()` 的重连路径是 reset→start、`reset()` 又不停
线程。每次 Bloomberg 重连就多留一份采样/订阅线程：实测同一份 JSONL 出现 6 组
互不相同的 30s 相位、每分钟 12 轮（设计是 2 轮），上游网关请求量也放大 6 倍。

这里不连 Bloomberg / 不连网关：两个后台循环都换成可阻塞的事件等待，影子采样
在空快照下不会发起 HTTP。
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("JWT_SECRET", "testsecret")

from config import settings  # noqa: E402
from services.bloomberg.enrichment import MarketDataEnrichmentService  # noqa: E402
from services.bloomberg.subscriptions import EMSXSubscriptionEngine  # noqa: E402
from services.bloomberg_adapter import BloombergEMSXService  # noqa: E402

_MKTDATA_THREAD_NAME = "mktdata-subscription"
_SHADOW_THREAD_NAME = "gateway-shadow"
_SUB_THREAD_NAME = "emsx-subscription"


def _alive_named(name: str) -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == name and t.is_alive()]


def _make_enrichment(monkeypatch, tmp_path) -> MarketDataEnrichmentService:
    """构造一个不连 Bloomberg 的行情服务；行情循环阻塞到 stop()。"""
    monkeypatch.setattr(settings, "EMSXVIEW_GATEWAY_MODE", "shadow")
    monkeypatch.setenv("EMSXVIEW_GATEWAY_SHADOW_DIR", str(tmp_path))

    service = MarketDataEnrichmentService(
        connection=SimpleNamespace(mktdata_session=None, mktdata_connected=False),
        subscription_engine=SimpleNamespace(stop_event=threading.Event()),
        _settings=settings,
    )
    # 真实循环依赖 blpapi session；测试只关心线程数量，阻塞等待停止信号即可
    service._mktdata_subscription_loop = lambda: service._mktdata_stop.wait(10)  # type: ignore[method-assign]
    return service


def test_start_twice_leaves_one_mktdata_thread_and_one_shadow_runner(monkeypatch, tmp_path):
    service = _make_enrichment(monkeypatch, tmp_path)
    service.start()
    first_thread = service._mktdata_thread
    first_runner = service._shadow_runner
    try:
        assert first_thread is not None and first_thread.is_alive()
        assert first_runner is not None and first_runner.is_running

        service.start()

        # 旧线程被停掉、旧 runner 被替换，整体只保留一份
        assert service._mktdata_thread is not first_thread
        assert not first_thread.is_alive()
        assert service._shadow_runner is not first_runner
        assert not first_runner.is_running
        assert len(_alive_named(_MKTDATA_THREAD_NAME)) == 1
        assert len(_alive_named(_SHADOW_THREAD_NAME)) == 1
    finally:
        service.stop()

    assert _alive_named(_MKTDATA_THREAD_NAME) == []
    assert _alive_named(_SHADOW_THREAD_NAME) == []
    assert service._shadow_runner is None


def _make_subscription_engine() -> EMSXSubscriptionEngine:
    """构造一个不连 Bloomberg 的订阅引擎；订阅循环阻塞到 stop()。"""
    engine = EMSXSubscriptionEngine(connection=SimpleNamespace(), repo_provider=None)
    engine._subscription_loop = lambda: engine._stop_event.wait(10)  # type: ignore[method-assign]
    return engine


def test_subscription_start_twice_leaves_one_thread():
    engine = _make_subscription_engine()
    engine.start()
    first_thread = engine._sub_thread
    try:
        assert first_thread is not None and first_thread.is_alive()

        engine.start()

        assert engine._sub_thread is not first_thread
        assert not first_thread.is_alive()
        assert len(_alive_named(_SUB_THREAD_NAME)) == 1
    finally:
        engine.stop()

    assert _alive_named(_SUB_THREAD_NAME) == []
    assert engine._sub_thread is None


def test_shadow_starter_is_idempotent(monkeypatch, tmp_path):
    """重复调用启动器不得再建第二个 runner（含直接调用方）。"""
    service = _make_enrichment(monkeypatch, tmp_path)
    try:
        service._start_shadow_if_enabled()
        runner = service._shadow_runner
        assert runner is not None and runner.is_running

        service._start_shadow_if_enabled()

        assert service._shadow_runner is runner
        assert len(_alive_named(_SHADOW_THREAD_NAME)) == 1
    finally:
        service.stop()


def test_reconnect_does_not_stack_sampling_or_mktdata_threads(monkeypatch, tmp_path):
    """connect() 重连路径不得产出第二份订阅/采样/行情线程。"""
    monkeypatch.setattr(settings, "EMSXVIEW_GATEWAY_MODE", "shadow")
    monkeypatch.setenv("EMSXVIEW_GATEWAY_SHADOW_DIR", str(tmp_path))

    service = BloombergEMSXService()
    service._enrich._mktdata_subscription_loop = (  # type: ignore[method-assign]
        lambda: service._enrich._mktdata_stop.wait(10)
    )
    # 不运行真实订阅循环（会尝试连 blpapi），只保留线程生命周期语义
    service._sub._subscription_loop = lambda: service._sub._stop_event.wait(10)  # type: ignore[method-assign]

    async def fake_conn_connect() -> bool:
        service._conn.connected = True
        service._conn.session = object()
        return True

    service._conn.connect = fake_conn_connect  # type: ignore[method-assign]

    async def scenario() -> tuple[threading.Thread, object, threading.Thread]:
        assert await service.connect() is True
        first_sub_thread = service._sub._sub_thread
        first_thread = service._enrich._mktdata_thread
        first_runner = service._enrich._shadow_runner

        # 模拟 Bloomberg 掉线后重连：连接状态清空，connect() 会走 reset→start
        service._conn.connected = False
        service._conn.session = None
        assert await service.connect() is True

        assert first_sub_thread is not None and not first_sub_thread.is_alive()
        assert service._sub._sub_thread is not first_sub_thread
        assert first_thread is not None and not first_thread.is_alive()
        assert service._enrich._mktdata_thread is not first_thread
        assert first_runner is not None and not first_runner.is_running
        assert service._enrich._shadow_runner is not first_runner
        return first_sub_thread, first_thread, first_runner

    try:
        asyncio.run(scenario())
        assert len(_alive_named(_SUB_THREAD_NAME)) == 1
        assert len(_alive_named(_MKTDATA_THREAD_NAME)) == 1
        assert len(_alive_named(_SHADOW_THREAD_NAME)) == 1
    finally:
        service._enrich.stop()
        service._sub.stop()

    assert _alive_named(_SUB_THREAD_NAME) == []

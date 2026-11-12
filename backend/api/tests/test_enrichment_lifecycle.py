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


# ── S1：会话终止后事件泵自行重建（2026-11-12 取证）──────────────────────────


class _FakeSession:
    """最小 blpapi session 替身：`start()` 可被置为失效，`nextEvent` 可阻塞。"""

    def __init__(self, alive: bool = True) -> None:
        self.alive = alive
        self.started = 0

    def start(self) -> bool:
        self.started += 1
        return self.alive

    def nextEvent(self, timeout_ms):  # noqa: N802 - 模拟 blpapi 接口
        raise AssertionError("测试不应真正泵事件")


def _make_service_with_session(monkeypatch, session) -> MarketDataEnrichmentService:
    monkeypatch.setattr(settings, "EMSXVIEW_GATEWAY_MODE", "off")
    connection = SimpleNamespace(mktdata_session=session, mktdata_connected=True)
    return MarketDataEnrichmentService(
        connection=connection,
        subscription_engine=SimpleNamespace(stop_event=threading.Event()),
        _settings=settings,
    )


def test_session_lost_clears_subscribed_state_so_resubscribe_happens(monkeypatch):
    """S1：会话丢失后必须清空「已订阅」集合，否则重建的会话一个标的都不会重订。"""
    service = _make_service_with_session(monkeypatch, _FakeSession())
    service._mktdata_subscribed_tickers = {"AAPL US Equity", "MSFT US Equity"}
    service._mktdata_active_tickers = {"AAPL US Equity"}

    service._on_mktdata_session_lost()

    assert service._mktdata_subscribed_tickers == set()
    assert service._mktdata_active_tickers == set()
    assert service._connection.mktdata_connected is False


def test_loop_rebuilds_dead_session_instead_of_exiting(monkeypatch):
    """S1：`SessionTerminated` 只标记断线，事件泵下一轮重建会话并继续订阅。

    旧实现在终止时 `return`，线程死掉后无人重启——11-12 06:37 起日本开盘
    4.5 小时无样本，直到 11:11 才有别的路径重新 `start()`。
    """
    dead = _FakeSession(alive=False)
    fresh = _FakeSession(alive=True)
    service = _make_service_with_session(monkeypatch, dead)
    service._mktdata_reconnect_interval_s = 0.01
    service._mktdata_subscribed_tickers = {"AAPL US Equity"}

    rebuilt: list[bool] = []
    housekeeping: list[object] = []

    async def fake_reconnect() -> bool:
        rebuilt.append(True)
        service._connection.mktdata_session = fresh
        service._connection.mktdata_connected = True
        return True

    monkeypatch.setattr(service, "_reconnect_for_mktdata", fake_reconnect)
    monkeypatch.setattr(service, "_run_housekeeping", lambda sess: housekeeping.append(sess))

    # 第一次 nextEvent 看到「会话已终止」，第二次开始由测试置位停止信号
    def next_event(timeout_ms):
        service._mktdata_stop.set()
        raise AssertionError("会话重建后不应在旧会话上泵事件")

    fresh.nextEvent = next_event  # type: ignore[assignment]

    service._mktdata_subscription_loop()

    assert rebuilt == [True]
    assert service._mktdata_subscribed_tickers == set()  # 已清空，等重订
    assert housekeeping and housekeeping[0] is fresh


def test_loop_exits_when_stop_requested_during_reconnect(monkeypatch):
    """S1：`stop()` 置位后重连路径立即放弃，不得把线程拖在退避里。"""
    service = _make_service_with_session(monkeypatch, _FakeSession(alive=False))
    service._mktdata_reconnect_interval_s = 30.0
    service._mktdata_stop.set()

    called: list[bool] = []

    async def fake_reconnect() -> bool:
        called.append(True)
        return False

    monkeypatch.setattr(service, "_reconnect_for_mktdata", fake_reconnect)
    service._mktdata_subscription_loop()

    assert called == []


# ── S2：额外订阅标的跨重连保留 ───────────────────────────────────────────────


def test_reset_keeps_extra_mktdata_tickers(monkeypatch):
    """S2：`reset()` 不得清掉调用方显式注册的额外标的。

    旧实现连 `_extra_mktdata_tickers` 一起清，重连后只剩订单自带标的，
    影子采样集随订单陆续到达从 7 爬到 50。
    """
    service = _make_service_with_session(monkeypatch, _FakeSession())
    service._extra_mktdata_tickers = {"BBCA IJ", "APA AU"}
    service._mktdata_subscribed_tickers = {"BBCA IJ"}

    service.reset()

    assert service._extra_mktdata_tickers == {"BBCA IJ", "APA AU"}
    assert service._mktdata_subscribed_tickers == set()

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
from blpapi.exception import InvalidStateException  # noqa: E402
from services.bloomberg import enrichment  # noqa: E402
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
    """最小 blpapi session 替身：`nextEvent` 可被替换，`start()` 恒为 False。

    `start()` 恒 False 是照抄实测行为：blpapi 对**已启动**的会话返回 False
    （只有未启动时才返回 True），所以它不能当健康探针用。
    """

    def __init__(self) -> None:
        self.started = 0

    def start(self) -> bool:
        self.started += 1
        return False

    def nextEvent(self, timeout_ms):  # noqa: N802 - 模拟 blpapi 接口
        raise AssertionError("测试不应真正泵事件")


def _make_service_with_session(monkeypatch, session) -> MarketDataEnrichmentService:
    monkeypatch.setattr(settings, "EMSXVIEW_GATEWAY_MODE", "off")
    # 真实连接管理器把会话存在私有字段 `_mktdata_session` 上，公开属性只读；
    # 替身照此建模，重建路径摘旧会话时才能同时清掉公开视图。
    connection = SimpleNamespace(
        _mktdata_session=session, mktdata_session=session, mktdata_connected=True
    )
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
    dead = _FakeSession()
    fresh = _FakeSession()
    service = _make_service_with_session(monkeypatch, dead)
    service._mktdata_reconnect_interval_s = 0.01
    service._mktdata_subscribed_tickers = {"AAPL US Equity"}

    rebuilt: list[bool] = []
    housekeeping: list[object] = []

    def fake_rebuild():
        rebuilt.append(True)
        service._connection.mktdata_session = fresh
        service._connection.mktdata_connected = True
        return fresh

    monkeypatch.setattr(service, "_rebuild_mktdata_session", fake_rebuild)
    monkeypatch.setattr(service, "_run_housekeeping", lambda sess: housekeeping.append(sess))
    # 首次订阅前的就绪等待（3s）与重连退避都压到 0，测试不必真等
    monkeypatch.setattr(enrichment, "_wait_or_stop", lambda timeout, *events: None)

    # 旧会话取事件时报「会话已终止」，与 blpapi 实测抛的异常一致
    def dead_next_event(timeout_ms):
        raise InvalidStateException("nextEvent cannot be used in the current session state", 0x00010009)

    dead.nextEvent = dead_next_event  # type: ignore[assignment]

    def next_event(timeout_ms):
        service._mktdata_stop.set()
        raise AssertionError("会话重建后不应在旧会话上泵事件")

    fresh.nextEvent = next_event  # type: ignore[assignment]

    service._mktdata_subscription_loop()

    # 旧会话的终止事件已置位断线标记，事件泵不再探活，直接重建
    assert rebuilt == [True]
    assert service._mktdata_subscribed_tickers == set()  # 已清空，等重订
    # 首轮 housekeeping 仍跑在「还被信任」的旧会话上（此时 `mktdata_connected`
    # 尚为真），随后旧会话取事件抛 `InvalidStateException` 才触发重建；重建成功
    # 后下一轮直接泵新会话（housekeeping 周期未到，不会重跑）。
    assert housekeeping == [dead]
    assert service._connection.mktdata_session is fresh


def test_loop_keeps_healthy_session_even_though_start_returns_false(monkeypatch):
    """健康会话不得被误判为已断：`Session.start()` 对已启动的会话返回 False。

    2026-11-12 20:47 实测：事件泵每轮拿 `sess.start()` 当健康探针，健康会话被
    判成已断 → 每轮重建会话、`marketDataConnected` 永远 false、影子采样零样本。
    """
    session = _FakeSession()
    service = _make_service_with_session(monkeypatch, session)
    service._mktdata_reconnect_interval_s = 0.01

    rebuilt: list[bool] = []
    monkeypatch.setattr(
        service, "_rebuild_mktdata_session", lambda: rebuilt.append(True) or session
    )
    monkeypatch.setattr(service, "_run_housekeeping", lambda sess: None)

    pumped: list[object] = []

    def next_event(timeout_ms):
        pumped.append(session)
        service._mktdata_stop.set()
        raise AssertionError("停止信号已置位，循环应退出")

    session.nextEvent = next_event  # type: ignore[assignment]

    service._mktdata_subscription_loop()

    assert rebuilt == []  # 一次都不该重建
    assert pumped == [session]  # 原会话直接被泵事件
    assert service._connection.mktdata_connected is True


def test_ensure_session_retries_after_rebuild_failure_instead_of_exiting(monkeypatch):
    """重建失败必须退避重试，不能返回 None 让事件泵线程退出。

    2026-11-12 20:47 实测：一次重建失败后 `_ensure_mktdata_session` 返回 None，
    事件泵线程直接结束，之后再无人拉起——行情与会话从此永久缺失。
    """
    service = _make_service_with_session(monkeypatch, None)
    service._connection.mktdata_connected = False
    service._mktdata_reconnect_interval_s = 0.01

    attempts: list[int] = []
    fresh = _FakeSession()

    def flaky_rebuild():
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            return None
        service._connection.mktdata_session = fresh
        service._connection.mktdata_connected = True
        return fresh

    monkeypatch.setattr(service, "_rebuild_mktdata_session", flaky_rebuild)
    stop_event = service._subscription_engine.stop_event

    assert service._ensure_mktdata_session(service._mktdata_stop, stop_event) is fresh
    assert attempts == [1, 2, 3]


def test_loop_exits_when_stop_requested_during_reconnect(monkeypatch):
    """S1：`stop()` 置位后重连路径立即放弃，不得把线程拖在退避里。"""
    service = _make_service_with_session(monkeypatch, _FakeSession())
    service._mktdata_reconnect_interval_s = 30.0
    service._mktdata_stop.set()

    called: list[bool] = []

    def fake_rebuild():
        called.append(True)
        return None

    monkeypatch.setattr(service, "_rebuild_mktdata_session", fake_rebuild)
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


def test_rebuild_mktdata_session_does_not_touch_emsx_session(monkeypatch):
    """S1 补充：只补建 mktdata 会话，不得拆掉 EMSX 主会话与请求池。

    实测 2026-11-12 20:47 重启后主会话连着、mktdata 会话打不开；若走整条
    `disconnect()` + `connect()`，订单推送会被一起打断。
    """
    service = _make_service_with_session(monkeypatch, _FakeSession())
    emsx_session = object()
    request_sessions = [object()]
    service._connection.session = emsx_session
    service._connection.connected = True
    service._connection._request_sessions = request_sessions

    class _Rebuilt:
        def start(self):
            return True

        def openService(self, name):  # noqa: N802 - 模拟 blpapi 接口
            return True

        def stop(self):
            raise AssertionError("成功重建的会话不应被停止")

    monkeypatch.setattr(enrichment.blpapi, "Session", lambda opts: _Rebuilt())
    monkeypatch.setattr(enrichment.blpapi, "SessionOptions", lambda: SimpleNamespace(
        setServerAddress=lambda host, port, n: None
    ))

    rebuilt = service._rebuild_mktdata_session()

    assert rebuilt is not None
    assert service._connection.mktdata_session is rebuilt
    assert service._connection.mktdata_connected is True
    assert service._connection.session is emsx_session
    assert service._connection.connected is True
    assert service._connection._request_sessions is request_sessions


def test_rebuild_mktdata_session_returns_none_when_service_unavailable(monkeypatch):
    """S1 补充：`//blp/mktdata` 打不开时返回 None 并清理，不留下半开会话。"""

    class _Broken:
        def start(self):
            return True

        def openService(self, name):  # noqa: N802
            return False

        def stop(self):
            self.stopped = True

    broken = _Broken()
    dead = _FakeSession()
    service = _make_service_with_session(monkeypatch, dead)
    # 模拟「会话已终止」：对象还在，但连接管理器已标记断线
    service._connection.mktdata_connected = False
    monkeypatch.setattr(enrichment.blpapi, "Session", lambda opts: broken)
    monkeypatch.setattr(enrichment.blpapi, "SessionOptions", lambda: SimpleNamespace(
        setServerAddress=lambda host, port, n: None
    ))

    assert service._rebuild_mktdata_session() is None
    # 死会话必须从连接管理器上摘掉：否则 `_ensure_mktdata_session` 下一轮
    # 仍会拿到它，事件泵立刻再抛 `InvalidStateException`，重建空转。
    assert getattr(service._connection, "_mktdata_session", None) is None
    assert service._connection.mktdata_connected is False
    assert getattr(broken, "stopped", False) is True
    assert dead.started == 0  # 死会话只被 stop，不再被 start 探活

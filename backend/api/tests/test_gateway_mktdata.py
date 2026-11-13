"""`on` 模式接线单测（015 §3.2–§3.4 / §10 步骤 2–4）。

覆盖四类风险：

1. **四类帧**：`snapshot` / `tick` / `status` / `heartbeat` 的分派与未知帧忽略；
2. **断链重连**：失败后指数退避，重连后重新拿 snapshot；集合变化立即重开；
3. **写缓存规则**：与直连 `_process_mktdata_message` 逐条对齐（整数、合并、
   报文 `ts`、NaN 跳过）；
4. **refdata 改 HTTP**：`PX_ROUND_LOT_SIZE` 缺席 → `-1`，`degraded` 透出。
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
from services.gateway_client import (  # noqa: E402
    FieldValue,
    GatewayStreamTimeout,
    RefdataResult,
    TickerQuote,
    parse_stream_message,
)
from services.gateway_mktdata import GatewayMktdataFeed  # noqa: E402


# ── 替身 ──────────────────────────────────────────────────────────────────────


class _FakeStream:
    def __init__(self, frames: list, on_frame=None) -> None:
        self._frames = list(frames)
        self._on_frame = on_frame
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc) -> None:
        self.closed = True

    async def __anext__(self):
        if not self._frames:
            raise StopAsyncIteration
        frame = self._frames.pop(0)
        if self._on_frame is not None:
            self._on_frame(frame)
        return parse_stream_message(frame) if isinstance(frame, str) else frame

    async def close(self) -> None:
        self.closed = True


class _FakeClient:
    def __init__(self, streams: list) -> None:
        self._streams = list(streams)
        self.opened: list[tuple[list, list]] = []
        self.closed = False

    def open_stream(self, tickers, fields, recv_timeout=0):
        self.opened.append((list(tickers), list(fields)))
        item = self._streams.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


class _FakeRefdataClient:
    def __init__(self, result: RefdataResult) -> None:
        self.result = result
        self.calls: list[tuple[list, list]] = []

    async def refdata_detailed(self, securities, fields):
        self.calls.append((list(securities), list(fields)))
        return self.result


def _quote(**values) -> TickerQuote:
    return TickerQuote(
        ticker="X",
        fields={
            name: FieldValue(value=value, src_ts=None, recv_ts="2026-11-14T10:00:00")
            for name, value in values.items()
        },
        subscribed=True,
    )


def _service(monkeypatch, *, intraday: bool = True, orders: dict | None = None):
    monkeypatch.setattr(settings, "EMSXVIEW_INTRADAY_STATE_ENABLED", intraday)
    monkeypatch.setattr(settings, "ODD_LOT_MARKETS", ["JP", "US"])
    engine = SimpleNamespace(stop_event=threading.Event(), orders=orders or {})
    return MarketDataEnrichmentService(
        connection=SimpleNamespace(mktdata_session=None, mktdata_connected=False),
        subscription_engine=engine,
        _settings=settings,
    )


# ── 四类帧 ────────────────────────────────────────────────────────────────────


def test_dispatch_covers_four_frame_types_and_ignores_unknown() -> None:
    quotes: list[tuple] = []
    statuses: list[dict] = []
    heartbeats: list[str] = []
    feed = GatewayMktdataFeed(
        _FakeClient([]),
        targets=lambda: [],
        fields=lambda: [],
        on_quotes=lambda data, ts, kind: quotes.append((data, ts, kind)),
        on_status=lambda status: statuses.append(status),
        on_heartbeat=lambda ts: heartbeats.append(ts),
    )

    feed._dispatch(
        parse_stream_message(
            '{"type": "snapshot", "ts": "t1", "data": {"AAPL US Equity": '
            '{"VWAP": {"value": 1.5}}}}'
        )
    )
    feed._dispatch(
        parse_stream_message(
            '{"type": "tick", "ts": "t2", "data": {"AAPL US Equity": '
            '{"VWAP": {"value": 1.6}}}}'
        )
    )
    feed._dispatch(
        parse_stream_message(
            '{"type": "status", "ts": "t3", "data": {"dropped": ["MSFT US Equity"]}}'
        )
    )
    feed._dispatch(parse_stream_message('{"type": "heartbeat", "ts": "t4", "data": null}'))
    feed._dispatch(parse_stream_message('{"type": "mystery", "ts": "t5", "data": {}}'))

    assert [kind for _, _, kind in quotes] == ["snapshot", "tick"]
    assert quotes[1][0]["AAPL US Equity"].fields["VWAP"].value == 1.6
    assert statuses == [{"dropped": ["MSFT US Equity"]}]
    assert feed.dropped_tickers == frozenset({"MSFT US Equity"})
    assert heartbeats == ["t4"]


def test_feed_freezes_and_marks_stale_after_threshold() -> None:
    now = [0.0]
    feed = GatewayMktdataFeed(
        _FakeClient([]),
        targets=lambda: [],
        fields=lambda: [],
        on_quotes=lambda *_: None,
        clock=lambda: now[0],
        stale_after=60.0,
    )

    assert feed.is_stale is True, "从未收到帧即陈旧"
    feed._dispatch(parse_stream_message('{"type": "heartbeat", "ts": "t", "data": null}'))
    now[0] = 59.0
    assert feed.is_stale is False
    now[0] = 60.0
    assert feed.is_stale is True

    feed._connected = True
    assert feed.is_stale is False, "连接存活时不应标记陈旧"


# ── 重连与集合重开 ────────────────────────────────────────────────────────────


def test_disconnect_backs_off_and_reconnects() -> None:
    holder: dict = {}
    stream = _FakeStream(
        ['{"type": "heartbeat", "ts": "t", "data": null}'],
        on_frame=lambda _frame: holder["feed"].stop(),
    )
    client = _FakeClient([OSError("connection refused"), stream])
    feed = GatewayMktdataFeed(
        client,
        targets=lambda: ["AAPL US Equity"],
        fields=lambda: ["VWAP"],
        on_quotes=lambda *_: None,
        backoff_initial=0.01,
        backoff_max=0.02,
        poll_interval=0.01,
    )
    holder["feed"] = feed

    asyncio.run(feed._run())

    assert len(client.opened) == 2, "首次失败后必须重连"
    assert client.opened[0][0] == ["AAPL US Equity"]
    assert client.closed is True
    assert stream.closed is True


def test_stream_timeout_triggers_reconnect_not_hang() -> None:
    """015 §4.1 缺陷 2：WS 静默超时必须进入重连，而不是永久挂住。"""
    holder: dict = {}

    class _TimingOutStream(_FakeStream):
        async def __anext__(self):
            raise GatewayStreamTimeout("45s 无消息")

    second = _FakeStream(
        ['{"type": "heartbeat", "ts": "t", "data": null}'],
        on_frame=lambda _frame: holder["feed"].stop(),
    )
    client = _FakeClient([_TimingOutStream([]), second])
    feed = GatewayMktdataFeed(
        client,
        targets=lambda: ["AAPL US Equity"],
        fields=lambda: ["VWAP"],
        on_quotes=lambda *_: None,
        backoff_initial=0.01,
        backoff_max=0.02,
        poll_interval=0.01,
    )
    holder["feed"] = feed

    asyncio.run(feed._run())

    assert len(client.opened) == 2


def test_subscription_set_change_reopens_without_backoff() -> None:
    targets = ["AAPL US Equity"]
    holder: dict = {}

    def _on_quotes(data, ts, kind):
        targets.append("MSFT US Equity")

    second = _FakeStream(
        ['{"type": "heartbeat", "ts": "t2", "data": null}'],
        on_frame=lambda _frame: holder["feed"].stop(),
    )
    client = _FakeClient(
        [
            _FakeStream(
                ['{"type": "tick", "ts": "t1", "data": {"AAPL US Equity": '
                 '{"VWAP": {"value": 1.0}}}}']
            ),
            second,
        ]
    )
    feed = GatewayMktdataFeed(
        client,
        targets=lambda: list(targets),
        fields=lambda: ["VWAP"],
        on_quotes=_on_quotes,
        backoff_initial=10.0,  # 若进退避，测试会因 10s 等待而暴露
        poll_interval=0.01,
    )
    holder["feed"] = feed

    asyncio.run(feed._run())

    assert client.opened[0][0] == ["AAPL US Equity"]
    assert client.opened[1][0] == ["AAPL US Equity", "MSFT US Equity"]
    assert second.closed is True


# ── 写缓存规则 ────────────────────────────────────────────────────────────────


def test_apply_gateway_quotes_matches_direct_write_rules(monkeypatch) -> None:
    service = _service(monkeypatch, intraday=True)
    ts = "2026-11-14T10:00:00.123+08:00"

    service.apply_gateway_quotes(
        {
            "AAPL US Equity": _quote(
                CHG_PCT_1D=1.5,
                VOLUME_AVG_5D=2_500_000.0,
                VWAP=float("nan"),
                PX_ROUND_LOT_SIZE=100.0,
                BID=10.1,
                ASK=10.2,
                LAST_PRICE=10.15,
                VOLUME=1234.0,
            )
        },
        ts,
        "snapshot",
    )

    assert service.price_changes["AAPL US Equity"] == 1.5
    assert service.adv5d["AAPL US Equity"] == 2_500_000.0
    assert "AAPL US Equity" not in service.mkt_vwap, "NaN 不得写入"
    assert service.round_lot_sizes["AAPL US Equity"] == 100
    assert isinstance(service.round_lot_sizes["AAPL US Equity"], int)
    assert service.intraday_quotes["AAPL US Equity"]["BID"] == 10.1
    assert service.intraday_quotes["AAPL US Equity"]["VOLUME"] == 1234
    assert service.intraday_quotes["AAPL US Equity"]["updated_at"] == ts

    newer_ts = "2026-11-14T10:00:01.456+08:00"
    service.apply_gateway_quotes(
        {"AAPL US Equity": _quote(ASK=10.25)},
        newer_ts,
        "tick",
    )
    merged = service.intraday_quotes["AAPL US Equity"]
    assert merged["BID"] == 10.1, "增量帧必须合并而非覆盖整条"
    assert merged["ASK"] == 10.25
    assert merged["updated_at"] == newer_ts


def test_intraday_disabled_does_not_write_quotes(monkeypatch) -> None:
    service = _service(monkeypatch, intraday=False)
    service.apply_gateway_quotes(
        {"AAPL US Equity": _quote(BID=10.1, LAST_PRICE=10.15)},
        "t",
        "tick",
    )
    assert service.intraday_quotes == {}


# ── 模式派发 ──────────────────────────────────────────────────────────────────


def test_on_mode_starts_gateway_feed_instead_of_direct_loop(monkeypatch) -> None:
    monkeypatch.setattr(settings, "EMSXVIEW_GATEWAY_MODE", "on")
    service = _service(monkeypatch)
    started: list[bool] = []
    monkeypatch.setattr(
        service, "_start_gateway_feed_if_enabled", lambda: started.append(True)
    )

    service.start()
    try:
        assert started == [True]
        assert service._mktdata_thread is None, "on 下不得启动直连事件泵"
    finally:
        service.stop()


def test_off_mode_keeps_direct_loop(monkeypatch) -> None:
    monkeypatch.setattr(settings, "EMSXVIEW_GATEWAY_MODE", "off")
    service = _service(monkeypatch)
    monkeypatch.setattr(service, "_mktdata_subscription_loop", lambda: service._mktdata_stop.wait(10))

    service.start()
    try:
        assert service._gateway_feed is None
        assert service._mktdata_thread is not None and service._mktdata_thread.is_alive()
    finally:
        service.stop()


# ── refdata 四查询改 HTTP ─────────────────────────────────────────────────────


def test_round_lot_missing_field_maps_to_minus_one(monkeypatch) -> None:
    service = _service(monkeypatch)
    service._orders_symbols = {"7203 JP", "6758 JP"}
    service._orders_symbol_exchange = [("7203 JP", "JP"), ("6758 JP", "JP")]
    fake = _FakeRefdataClient(
        RefdataResult({"7203 JP": {"PX_ROUND_LOT_SIZE": 100}}, "cache", False, "t")
    )
    service._gateway_client = fake

    asyncio.run(service._gateway_query_round_lot_sizes())

    assert service.round_lot_sizes["7203 JP"] == 100
    assert service.round_lot_sizes["6758 JP"] == -1, "缺席必须映射为「未知」"
    assert fake.calls == [(["6758 JP", "7203 JP"], ["PX_ROUND_LOT_SIZE"])]
    assert service._round_lot_queried_tickers == {"6758 JP", "7203 JP"}


def test_refdata_degraded_is_exposed(monkeypatch) -> None:
    service = _service(monkeypatch)
    service._gateway_client = _FakeRefdataClient(
        RefdataResult({}, "stale", True, "2026-11-14T10:00:00+08:00")
    )

    asyncio.run(service._gateway_refdata(["AAPL US Equity"], ["PX_LAST"]))
    assert service._gateway_refdata_degraded is True

    service._gateway_client = _FakeRefdataClient(
        RefdataResult({}, "cache", False, "2026-11-14T10:00:01+08:00")
    )
    asyncio.run(service._gateway_refdata(["AAPL US Equity"], ["PX_LAST"]))
    assert service._gateway_refdata_degraded is False


def test_gateway_fx_and_crncy_queries_update_caches(monkeypatch) -> None:
    order = SimpleNamespace(id=1, symbol="AAPL US Equity", exchange="US", currency="EUR")
    service = _service(monkeypatch, orders={"1": order})
    service._orders_symbols = {"AAPL US Equity"}
    service._orders_symbol_exchange = [("AAPL US Equity", "US")]
    service._fx_rates["USD"] = 1.0

    class _Client:
        async def refdata_detailed(self, securities, fields):
            if fields == ["PX_LAST"]:
                return RefdataResult(
                    {
                        "EURUSD Curncy": {"PX_LAST": 1.1},
                        "USDEUR Curncy": {"PX_LAST": 0.91},
                    },
                    "cache",
                    False,
                    "t",
                )
            return RefdataResult({"AAPL US Equity": {"CRNCY": "USD"}}, "cache", False, "t")

    service._gateway_client = _Client()

    asyncio.run(service._gateway_refresh_fx_rates())
    assert abs(service.fx_rates["EUR"] - 1 / 0.91) < 1e-12, "优先采用 inversive 口径"

    asyncio.run(service._gateway_query_ticker_currencies())
    assert service.ticker_currencies["AAPL US Equity"] == "USD"
    assert order.currency == "USD", "网关注册的本币必须覆盖订单货币"
    assert service._crncy_queried_tickers == {"AAPL US Equity"}

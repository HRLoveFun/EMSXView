"""013 网关客户端单测（不连真实网关，不依赖 Bloomberg 终端）。

覆盖四类风险：

1. **解包语义**：`_meta` 剥离、坏字段跳过、部分成功的 gaps 保留；
2. **错误分类**：可回落直连的错误必须映射到 `fallback_direct`，不可回落的不得熔断；
3. **熔断状态机**：阈值打开、half-open 只放行一个探针、成功复位；
4. **前置校验**：未知字段本地拦截，不产生网络往返。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platform_data.contracts import gateway_contracts as gcc  # noqa: E402
from services import gateway_client as gc  # noqa: E402


# ── 夹具 ──────────────────────────────────────────────────────────────────────


def _envelope(data=None, *, code: int = 0, source: str = "cache", degraded: bool = False) -> dict:
    return {
        "code": code,
        "message": "ok" if code == 0 else "error",
        "data": data,
        "source": source,
        "degraded": degraded,
        "ts": "2026-11-02T14:30:05.123+08:00",
    }


def _make_client(handler, **kwargs):
    """注入 MockTransport 的客户端，并返回一个记录请求次数的列表。"""
    calls: list[httpx.Request] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    client = gc.GatewayClient(
        "http://127.0.0.1:8101",
        transport=httpx.MockTransport(_wrapped),
        **kwargs,
    )
    return client, calls


def _quote_payload() -> dict:
    return {
        "AAPL US Equity": {
            "BID": {"value": 231.15, "src_ts": "2026-11-02T14:29:58", "recv_ts": "2026-11-02T14:29:58.412"},
            "LAST_PRICE": {"value": 231.20, "src_ts": None, "recv_ts": "2026-11-02T14:29:58.500"},
            "_meta": {
                "subscribed": True,
                "last_update": "2026-11-02T14:29:58.500",
                "gaps": ["CHG_PCT_1D", "VOLUME_AVG_5D"],
            },
        }
    }


# ── 解包 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quote_decodes_fields_and_strips_meta() -> None:
    """`_meta` 不进 fields；gaps / last_update 正确落到 TickerQuote。"""
    client, _ = _make_client(lambda request: httpx.Response(200, json=_envelope(_quote_payload())))
    async with client:
        quotes = await client.quote(["AAPL US Equity"])

    quote = quotes["AAPL US Equity"]
    assert set(quote.fields) == {"BID", "LAST_PRICE"}
    assert quote.fields["BID"].value == 231.15
    assert quote.fields["LAST_PRICE"].src_ts is None
    assert quote.subscribed is True
    assert quote.gaps == ("CHG_PCT_1D", "VOLUME_AVG_5D")


@pytest.mark.asyncio
async def test_quote_skips_malformed_field_without_dropping_ticker() -> None:
    """单字段结构非法只丢该字段，不丢整条 ticker（与上游「单字段异常不整条丢弃」一致）。"""
    payload = {
        "MSFT US Equity": {
            "BID": {"value": 400.1, "recv_ts": "2026-11-02T14:30:00"},
            "ASK": {"value": 400.2},  # 缺 recv_ts
            "_meta": {"subscribed": True, "last_update": None, "gaps": []},
        }
    }
    client, _ = _make_client(lambda request: httpx.Response(200, json=_envelope(payload)))
    async with client:
        quotes = await client.quote(["MSFT US Equity"])

    assert set(quotes["MSFT US Equity"].fields) == {"BID"}


@pytest.mark.asyncio
async def test_degraded_stale_response_is_not_silently_treated_as_fresh() -> None:
    """source=stale 时 `is_degraded` 必须为真（消费方据此标注数据时点）。"""
    captured: list[dict] = []
    payload = _envelope({"AAPL US Equity": {}}, source="stale", degraded=True)

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(payload)
        return httpx.Response(200, json=payload)

    client, _ = _make_client(_handler)
    async with client:
        await client.quote(["AAPL US Equity"])

    assert gc.is_degraded(captured[0]) is True


# ── 错误分类 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upstream_unavailable_maps_to_fallback_direct() -> None:
    """2001 必须标记为可回落直连 —— 上层据此切回 blpapi。"""
    client, _ = _make_client(
        lambda request: httpx.Response(503, json=_envelope(None, code=2001, source="none"))
    )
    async with client:
        with pytest.raises(gc.GatewayError) as excinfo:
            await client.quote(["AAPL US Equity"])

    assert excinfo.value.code == 2001
    assert excinfo.value.name == "UPSTREAM_UNAVAILABLE"
    assert excinfo.value.should_fallback_direct is True


@pytest.mark.asyncio
async def test_subscription_limit_is_not_retryable_and_does_not_trip_circuit() -> None:
    """2002 是配额问题，重试无意义；也不应把整条链路熔断。"""
    client, calls = _make_client(
        lambda request: httpx.Response(429, json=_envelope(None, code=2002, source="none"))
    )
    async with client:
        for _ in range(5):
            with pytest.raises(gc.GatewayError) as excinfo:
                await client.subscribe(["AAPL US Equity"])

    assert excinfo.value.retryable is False
    assert client.circuit_state == "closed"
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_http_timeout_maps_to_2003() -> None:
    """连接层超时归到 2003（可重试、可用 stale）。"""

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("boom", request=request)

    client, _ = _make_client(_handler)
    async with client:
        with pytest.raises(gc.GatewayError) as excinfo:
            await client.quote(["AAPL US Equity"])

    assert excinfo.value.code == 2003
    assert excinfo.value.retryable is True


@pytest.mark.asyncio
async def test_non_json_response_maps_to_internal_error() -> None:
    """上游返回 HTML（反向代理错误页）时不得把内容当业务数据。"""
    client, _ = _make_client(lambda request: httpx.Response(200, text="<html>oops</html>"))
    async with client:
        with pytest.raises(gc.GatewayError) as excinfo:
            await client.quote(["AAPL US Equity"])

    assert excinfo.value.code == 3001


# ── 熔断 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold_and_stops_sending() -> None:
    """连续 3 次 2001 → 打开；打开期间请求根本不出网。"""
    client, calls = _make_client(
        lambda request: httpx.Response(503, json=_envelope(None, code=2001, source="none"))
    )
    async with client:
        for _ in range(3):
            with pytest.raises(gc.GatewayError):
                await client.quote(["AAPL US Equity"])
        assert client.circuit_state == "open"

        before = len(calls)
        with pytest.raises(gc.GatewayUnavailable):
            await client.quote(["AAPL US Equity"])
        assert len(calls) == before, "熔断打开后不应再发请求"


@pytest.mark.asyncio
async def test_circuit_half_open_allows_single_probe_then_recovers() -> None:
    """过冷却期只放行一个探针；探针成功即复位。"""
    now = [0.0]
    breaker = gc.CircuitBreaker(threshold=1, reset_seconds=60, clock=lambda: now[0])
    client, calls = _make_client(
        lambda request: httpx.Response(503, json=_envelope(None, code=2001, source="none")),
        breaker=breaker,
    )
    async with client:
        with pytest.raises(gc.GatewayError):
            await client.quote(["AAPL US Equity"])
        assert client.circuit_state == "open"

        now[0] = 61.0
        assert client.circuit_state == "half_open"

        # 探针在途时第二个请求被拒（half_open 只放一个）
        assert breaker.allow() is True
        assert breaker.allow() is False

    breaker.record_success()
    assert breaker.state == "closed"


@pytest.mark.asyncio
async def test_circuit_recovers_after_business_error_probe() -> None:
    """half_open 探针收到业务错误码（2xxx）也说明网关存活，必须复位熔断。"""
    now = [0.0]
    breaker = gc.CircuitBreaker(threshold=1, reset_seconds=60, clock=lambda: now[0])
    responses = iter(
        [
            httpx.Response(503, json=_envelope(None, code=2001, source="none")),
            httpx.Response(429, json=_envelope(None, code=2002, source="none")),
        ]
    )
    client, _ = _make_client(lambda request: next(responses), breaker=breaker)
    async with client:
        with pytest.raises(gc.GatewayError):
            await client.quote(["AAPL US Equity"])
        assert client.circuit_state == "open"

        now[0] = 61.0
        with pytest.raises(gc.GatewayError):
            await client.quote(["AAPL US Equity"])

    assert client.circuit_state == "closed"
    assert breaker.allow() is True


@pytest.mark.asyncio
async def test_circuit_success_resets_failure_count() -> None:
    """成功一次后失败计数归零，不会因历史失败过早打开。"""
    responses = iter(
        [
            httpx.Response(503, json=_envelope(None, code=2001, source="none")),
            httpx.Response(503, json=_envelope(None, code=2001, source="none")),
            httpx.Response(200, json=_envelope(_quote_payload())),
            httpx.Response(503, json=_envelope(None, code=2001, source="none")),
            httpx.Response(503, json=_envelope(None, code=2001, source="none")),
        ]
    )
    client, _ = _make_client(lambda request: next(responses))
    async with client:
        for _ in range(2):
            with pytest.raises(gc.GatewayError):
                await client.quote(["AAPL US Equity"])
        await client.quote(["AAPL US Equity"])
        assert client.circuit_state == "closed"
        for _ in range(2):
            with pytest.raises(gc.GatewayError):
                await client.quote(["AAPL US Equity"])

    assert client.circuit_state == "closed", "两次失败不应触发 3 次阈值"


# ── 前置校验 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_mktdata_field_rejected_locally() -> None:
    """未知字段不发请求（省往返，也避免上游各版本解释不同）。"""
    client, calls = _make_client(lambda request: httpx.Response(200, json=_envelope({})))
    async with client:
        with pytest.raises(gc.GatewayError) as excinfo:
            await client.subscribe(["AAPL US Equity"], fields=["NOT_A_FIELD"])

    assert excinfo.value.code == 1001
    assert calls == []


@pytest.mark.asyncio
async def test_unknown_refdata_field_rejected_locally() -> None:
    client, calls = _make_client(lambda request: httpx.Response(200, json=_envelope({})))
    async with client:
        with pytest.raises(gc.GatewayError):
            await client.refdata(["AAPL US Equity"], ["CLOSE"])

    assert calls == []


@pytest.mark.asyncio
async def test_empty_ticker_list_short_circuits() -> None:
    """空输入不产生请求（避免无意义往返与上游 1001）。"""
    client, calls = _make_client(lambda request: httpx.Response(200, json=_envelope({})))
    async with client:
        assert await client.quote([]) == {}
        assert await client.refdata(["AAPL US Equity"], []) == {}
    assert calls == []


# ── 契约版本 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contract_version_match_passes() -> None:
    """版本一致时返回 health 数据，供调用方读取会话状态。"""
    health = {
        "contract_version": gcc.CONTRACT_VERSION,
        "connected": True,
        "mktdata_session": "up",
        "refdata_session": "up",
        "subscriptions": 0,
        "clients": 0,
        "cache_hit_rate": 0.0,
        "uptime_seconds": 1.0,
    }
    client, _ = _make_client(lambda request: httpx.Response(200, json=_envelope(health)))
    async with client:
        data = await client.ensure_compatible()

    assert data["connected"] is True


@pytest.mark.asyncio
async def test_contract_version_mismatch_refuses_to_enable() -> None:
    """版本不一致必须硬失败，不能按旧结构解析新报文。"""
    health = {"contract_version": "gateway-v2", "connected": True}
    client, _ = _make_client(lambda request: httpx.Response(200, json=_envelope(health)))
    async with client:
        with pytest.raises(gc.GatewayContractMismatch):
            await client.ensure_compatible()


# ── WS 流 ─────────────────────────────────────────────────────────────────────


class _FakeWS:
    """最小 WebSocket 替身：按序吐出预置帧，可记录关闭。"""

    def __init__(self, frames: list[str], hang_after: bool = False) -> None:
        self._frames = list(frames)
        self._hang_after = hang_after
        self.closed = False

    async def recv(self) -> str:
        if self._frames:
            return self._frames.pop(0)
        if self._hang_after:
            await asyncio.sleep(30)
        raise RuntimeError("no more frames")

    async def close(self) -> None:
        self.closed = True


def test_parse_stream_message_covers_all_four_types() -> None:
    """契约声明的 4 类消息都必须可解析。"""
    for kind in ("snapshot", "tick", "status", "heartbeat"):
        msg = gc.parse_stream_message(f'{{"type": "{kind}", "ts": "t", "data": {{}}}}')
        assert msg.type == kind


def test_stream_timeout_is_a_gateway_error() -> None:
    """015 §4.1 缺陷 2：WS 静默超时必须能被 GatewayError / Unavailable 接住。"""
    assert issubclass(gc.GatewayStreamTimeout, gc.GatewayUnavailable)
    assert issubclass(gc.GatewayStreamTimeout, gc.GatewayError)
    exc = gc.GatewayStreamTimeout("silent")
    assert exc.code == gc.ErrorCode.UPSTREAM_UNAVAILABLE
    assert exc.should_fallback_direct is True


def test_snapshot_and_tick_frames_decode_to_ticker_quotes() -> None:
    """015 §4.1 缺陷 3：WS 帧必须与 /quote 一样按 TickerQuote 可读。"""
    frame = (
        '{"type": "tick", "ts": "2026-11-14T10:00:00.123+08:00", '
        '"data": {"AAPL US Equity": {'
        '"VWAP": {"value": 231.5, "src_ts": null},'
        '"_meta": {"subscribed": true, "last_update": "t", "gaps": []}}}}'
    )
    msg = gc.parse_stream_message(frame)

    quote = msg.data["AAPL US Equity"]
    assert quote.fields["VWAP"].value == 231.5
    # 帧内缺 recv_ts：用报文顶层 ts 补齐，否则 _decode_field 会整字段丢弃
    assert quote.fields["VWAP"].recv_ts == "2026-11-14T10:00:00.123+08:00"
    assert quote.gaps == ()


def test_status_frame_keeps_raw_dict() -> None:
    """`status` / `heartbeat` 不做字段解码，保持网关原始结构。"""
    msg = gc.parse_stream_message(
        '{"type": "status", "ts": "t", "data": {"dropped": ["AAPL US Equity"]}}'
    )
    assert msg.data == {"dropped": ["AAPL US Equity"]}


def test_circuit_open_window_is_not_extended_by_repeated_failures() -> None:
    """015 §4.2 缺陷 4：open 期间 record_failure 不得重打打开时刻。"""
    now = [0.0]
    breaker = gc.CircuitBreaker(threshold=1, reset_seconds=60, clock=lambda: now[0])
    breaker.record_failure()
    assert breaker.state == "open"

    now[0] = 30.0
    breaker.record_failure()
    now[0] = 61.0
    assert breaker.state == "half_open", "打开时刻被重打会导致熔断永不复位"


def test_half_open_probe_failure_restarts_cooldown() -> None:
    """half_open 探针失败才允许重新计时。"""
    now = [0.0]
    breaker = gc.CircuitBreaker(threshold=1, reset_seconds=60, clock=lambda: now[0])
    breaker.record_failure()

    now[0] = 61.0
    assert breaker.allow() is True
    now[0] = 62.0
    breaker.record_failure()
    now[0] = 100.0
    assert breaker.state == "open"
    now[0] = 123.0
    assert breaker.state == "half_open"


def test_parse_stream_message_rejects_non_json() -> None:
    """非 JSON 帧不能静默吞掉 —— 上层需要知道链路已坏。"""
    with pytest.raises(ValueError):
        gc.parse_stream_message("not-json")


@pytest.mark.asyncio
async def test_stream_yields_frames_in_order() -> None:
    """帧按到达顺序产出，且关闭时释放连接。"""
    frames = [
        '{"type": "snapshot", "ts": "t1", "data": {"AAPL US Equity": {}}}',
        '{"type": "tick", "ts": "t2", "data": {"AAPL US Equity": {"BID": {}}}}',
    ]
    fake = _FakeWS(frames)

    async def _connect(url: str):
        return fake

    client, _ = _make_client(lambda request: httpx.Response(200, json=_envelope({})))
    async with client:
        stream = client.open_stream(["AAPL US Equity"], connect=_connect)
        async with stream:
            first = await stream.__anext__()
            second = await stream.__anext__()

    assert (first.type, second.type) == ("snapshot", "tick")
    assert fake.closed is True


@pytest.mark.asyncio
async def test_stream_times_out_when_no_frames() -> None:
    """连续 N 个心跳周期无消息（含 heartbeat）判定断链。"""
    fake = _FakeWS([], hang_after=True)

    async def _connect(url: str):
        return fake

    client, _ = _make_client(lambda request: httpx.Response(200, json=_envelope({})))
    async with client:
        stream = client.open_stream(["AAPL US Equity"], connect=_connect, recv_timeout=0.05)
        async with stream:
            with pytest.raises(gc.GatewayStreamTimeout):
                await stream.__anext__()


@pytest.mark.asyncio
async def test_refdata_detailed_exposes_degraded_metadata() -> None:
    """015 §3.3：`degraded` / `source=stale` 必须透出，不能只返回 data。"""
    payload = _envelope(
        {"AAPL US Equity": {"PX_LAST": 231.2}},
        source="stale",
        degraded=True,
    )
    client, _ = _make_client(lambda request: httpx.Response(200, json=payload))
    async with client:
        result = await client.refdata_detailed(["AAPL US Equity"], ["PX_LAST"])

    assert result.data == {"AAPL US Equity": {"PX_LAST": 231.2}}
    assert result.degraded is True
    assert result.source == "stale"
    assert result.ts == payload["ts"]

    # 兼容旧调用方：refdata() 仍只返回 data
    client, _ = _make_client(lambda request: httpx.Response(200, json=payload))
    async with client:
        assert await client.refdata(["AAPL US Equity"], ["PX_LAST"]) == result.data


def test_ws_base_url_can_be_configured_separately() -> None:
    """015 §4.3 缺陷 8：`EMSXVIEW_GATEWAY_WS_URL` 不能被忽略。"""
    client = gc.GatewayClient(
        "http://127.0.0.1:8101",
        ws_base_url="ws://gateway.internal:9000",
        transport=httpx.MockTransport(lambda r: None),
    )
    stream = client.open_stream(["AAPL US Equity"])
    assert stream._url.startswith("ws://gateway.internal:9000/ws/gw/v1/marketdata?")


def test_stream_url_carries_tickers_and_default_fields() -> None:
    """URL 必须显式带齐字段（ADR-0010：订阅字段必须显式进入订阅列表）。

    同时验证空格已编码 —— 未编码的 URI 会被 websockets 以 InvalidURI 拒绝，
    表现为「连不上但看不出原因」。
    """
    client = gc.GatewayClient("http://127.0.0.1:8101", transport=httpx.MockTransport(lambda r: None))
    stream = client.open_stream(["AAPL US Equity", "AAPL US Equity"])
    url = stream._url  # noqa: SLF001 - 契约断言需要检查构造结果

    assert " " not in url, "URL 不得含未编码空格"
    query = parse_qs(urlparse(url).query)
    assert query["tickers"] == ["AAPL US Equity"], "重复 ticker 必须去重"
    assert query["fields"][0].split(",") == list(gcc.MKTDATA_FIELDS)

"""行情/参考数据网关客户端（013 M0 契约的下游实现）。

定位：EMSXView 侧**唯一**与 `emsx-gateway`（`:8101`）通信的出口。只做传输、
解包与降级判定，不做业务映射——后者仍留在 `enrichment.py` 与
`market_state_service.py`，切换时上层方法签名不变。

三条纪律：

1. **契约前置校验**：未知字段、未知错误码在本地拦截，不发请求也不猜语义；
2. **降级显式化**：`source=stale` / `degraded=true` 必须原样回传，不吞不补；
3. **熔断后回落直连**：触发熔断抛 `GatewayUnavailable`，由上层切回 blpapi 直连，
   绝不在网关故障时静默返回空数据。

字段可用性与错误码语义见 `platform_data.contracts.gateway_contracts`（上游
`tests/contracts/gateway_schema.json` 的镜像）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Iterable, Optional
from urllib.parse import quote, urlencode

import httpx

from platform_data.contracts.gateway_contracts import (
    CIRCUIT_FAILURE_THRESHOLD,
    CIRCUIT_OPENING_CODES,
    CIRCUIT_RESET_SECONDS,
    CONTRACT_VERSION,
    ERROR_SPECS,
    HEARTBEAT_SECONDS,
    HTTP_PREFIX,
    MKTDATA_FIELDS,
    REQUEST_TIMEOUT_SECONDS,
    SOURCE_STALE,
    WS_MARKETDATA_PATH,
    ErrorCode,
    ErrorSpec,
    is_known_mktdata_field,
    is_known_refdata_field,
)

logger = logging.getLogger("main")


# ── 异常 ──────────────────────────────────────────────────────────────────────


class GatewayError(Exception):
    """网关返回的业务错误（envelope.code != 0）。"""

    def __init__(self, code: int, message: str = "") -> None:
        spec: Optional[ErrorSpec] = ERROR_SPECS.get(int(code))
        self.code = int(code)
        self.spec = spec
        self.name = spec.name if spec else "UNKNOWN_CODE"
        self.retryable = spec.retryable if spec else False
        self.client_action = spec.client_action if spec else "none"
        super().__init__(f"[{self.code} {self.name}] {message}")

    @property
    def should_fallback_direct(self) -> bool:
        """该错误是否要求上层回落直连（而非重试或忽略）。"""
        return self.client_action == "fallback_direct"


class GatewayUnavailable(GatewayError):
    """网关不可达或熔断打开 —— 上层应切回 blpapi 直连。"""

    def __init__(self, message: str = "gateway unavailable") -> None:
        super().__init__(ErrorCode.UPSTREAM_UNAVAILABLE, message)


class GatewayContractMismatch(Exception):
    """契约版本不一致：配置错误，不重试，必须人工对齐后重启。"""


class GatewayStreamTimeout(Exception):
    """WS 连续多个心跳周期无消息，判定断链。"""


# ── 熔断 ──────────────────────────────────────────────────────────────────────


class CircuitBreaker:
    """三态熔断（CLOSED → OPEN → HALF_OPEN）。

    与上游管道侧的 `circuit_breaker` 同构但独立实现：跨越进程，不共享状态。
    """

    def __init__(
        self,
        threshold: int = CIRCUIT_FAILURE_THRESHOLD,
        reset_seconds: float = CIRCUIT_RESET_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = max(1, int(threshold))
        self._reset_seconds = max(1.0, float(reset_seconds))
        self._clock = clock
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._half_open_in_flight = False

    @property
    def state(self) -> str:
        """当前状态：closed / open / half_open。"""
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self._reset_seconds:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        """是否放行本次请求（half_open 只放行一个）。"""
        state = self.state
        if state == "closed":
            return True
        if state == "open":
            return False
        if self._half_open_in_flight:
            return False
        self._half_open_in_flight = True
        return True

    def record_success(self) -> None:
        """成功后回到 closed（half_open 试探成功即恢复）。"""
        self._failures = 0
        self._opened_at = None
        self._half_open_in_flight = False

    def record_failure(self) -> None:
        """失败后累计；达到阈值或 half_open 失败即打开。"""
        self._half_open_in_flight = False
        self._failures += 1
        if self._opened_at is not None or self._failures >= self._threshold:
            self._opened_at = self._clock()


# ── 报文结构 ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FieldValue:
    """单字段取值与时间戳。`src_ts` 可为空，`recv_ts` 必有。"""

    value: Any
    src_ts: Optional[str]
    recv_ts: str


@dataclass(frozen=True)
class TickerQuote:
    """单个标的的快照。gaps = 已订阅但上游未推送的字段。"""

    ticker: str
    fields: dict[str, FieldValue] = field(default_factory=dict)
    subscribed: bool = False
    last_update: Optional[str] = None
    gaps: tuple[str, ...] = ()

    def get(self, name: str) -> Optional[FieldValue]:
        """取字段；缺失返回 None（调用方按契约 fallback 回落，不得填 0）。"""
        return self.fields.get(name)


@dataclass(frozen=True)
class SubscribeResult:
    accepted: tuple[str, ...]
    rejected: int
    total: int


@dataclass(frozen=True)
class UnsubscribeResult:
    removed: tuple[str, ...]
    remaining: int


@dataclass(frozen=True)
class StreamMessage:
    """WS 推送消息。type ∈ snapshot / tick / status / heartbeat。"""

    type: str
    ts: str
    data: dict


# ── 解包（纯函数，单测覆盖） ─────────────────────────────────────────────────


def _split_meta(payload: dict) -> tuple[dict, dict]:
    """把 `_meta` 从 ticker 载荷中摘出。"""
    meta = payload.get("_meta") or {}
    return {k: v for k, v in payload.items() if k != "_meta"}, meta


def _decode_field(raw: Any) -> Optional[FieldValue]:
    """单字段解码；结构不符返回 None（不猜、不补默认值）。"""
    if not isinstance(raw, dict) or "value" not in raw or "recv_ts" not in raw:
        return None
    return FieldValue(value=raw["value"], src_ts=raw.get("src_ts"), recv_ts=str(raw["recv_ts"]))


def decode_quote(data: dict) -> dict[str, TickerQuote]:
    """`/quote` 的 data → ticker → TickerQuote。"""
    quotes: dict[str, TickerQuote] = {}
    for ticker, payload in (data or {}).items():
        if not isinstance(payload, dict):
            continue
        body, meta = _split_meta(payload)
        fields = {name: decoded for name, raw in body.items() if (decoded := _decode_field(raw))}
        quotes[ticker] = TickerQuote(
            ticker=ticker,
            fields=fields,
            subscribed=bool(meta.get("subscribed", False)),
            last_update=meta.get("last_update"),
            gaps=tuple(meta.get("gaps") or ()),
        )
    return quotes


def parse_stream_message(raw: str | bytes) -> StreamMessage:
    """WS 文本帧 → StreamMessage；结构非法抛 ValueError。"""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"WS 帧不是合法 JSON: {exc}") from exc
    if not isinstance(payload, dict) or "type" not in payload:
        raise ValueError("WS 帧缺少 type 字段")
    return StreamMessage(
        type=str(payload["type"]),
        ts=str(payload.get("ts", "")),
        data=payload.get("data") or {},
    )


# ── 客户端 ────────────────────────────────────────────────────────────────────


class GatewayClient:
    """HTTP 客户端。生命周期由调用方管理（`async with` 或显式 `close()`）。"""

    def __init__(
        self,
        base_url: str,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._breaker = breaker or CircuitBreaker()
        self._client = httpx.AsyncClient(
            base_url=self._base_url + HTTP_PREFIX,
            timeout=timeout,
            transport=transport,
        )

    # ── 生命周期 ──

    async def __aenter__(self) -> "GatewayClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def circuit_state(self) -> str:
        return self._breaker.state

    # ── 底层调用 ──

    async def _call(self, method: str, path: str, **kwargs: Any) -> dict:
        """发一次请求并解包 envelope；错误按契约分类抛出。"""
        self._ensure_circuit()
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            self._breaker.record_failure()
            raise GatewayError(ErrorCode.UPSTREAM_TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            self._breaker.record_failure()
            raise GatewayUnavailable(str(exc)) from exc
        return self._unwrap(response)

    def _ensure_circuit(self) -> None:
        """熔断打开时直接拒绝，不发请求。"""
        if not self._breaker.allow():
            raise GatewayUnavailable(f"circuit open ({self._breaker.state})")

    def _unwrap(self, response: httpx.Response) -> dict:
        """解析 envelope：code=0 且非 stale 才计为成功。"""
        try:
            payload = response.json()
        except ValueError as exc:
            self._breaker.record_failure()
            raise GatewayError(ErrorCode.INTERNAL_ERROR, "响应不是合法 JSON") from exc
        if not isinstance(payload, dict) or "code" not in payload:
            self._breaker.record_failure()
            raise GatewayError(ErrorCode.INTERNAL_ERROR, "响应缺少 envelope")
        code = int(payload["code"])
        if code == ErrorCode.OK:
            self._record_ok(payload)
            return payload
        if code in CIRCUIT_OPENING_CODES:
            self._breaker.record_failure()
        raise GatewayError(code, str(payload.get("message", "")))

    def _record_ok(self, payload: dict) -> None:
        self._breaker.record_success()
        if payload.get("degraded"):
            logger.warning(
                "gateway degraded response (source=%s, ts=%s)：数据可能陈旧",
                payload.get("source"),
                payload.get("ts"),
            )

    # ── 端点 ──

    async def health(self) -> dict:
        """健康检查；不发熔断计数（探活失败不应影响业务熔断状态）。"""
        response = await self._client.get("/health")
        payload = response.json()
        return payload.get("data") or {}

    async def ensure_compatible(self) -> dict:
        """启动期契约校验：版本不一致即拒绝启用网关通道。"""
        data = await self.health()
        actual = data.get("contract_version")
        if actual != CONTRACT_VERSION:
            raise GatewayContractMismatch(
                f"网关契约版本 {actual!r} 与本仓镜像 {CONTRACT_VERSION!r} 不一致，"
                f"请先对齐 platform_data/contracts/gateway_schema.json"
            )
        return data

    async def quote(
        self, tickers: Iterable[str], fields: Optional[Iterable[str]] = None
    ) -> dict[str, TickerQuote]:
        """读订阅缓存快照（不回源）。"""
        ticker_list = _normalize(tickers)
        if not ticker_list:
            return {}
        params: dict[str, str] = {"tickers": ",".join(ticker_list)}
        if fields:
            _validate_mktdata_fields(fields)
            params["fields"] = ",".join(_normalize(fields))
        payload = await self._call("GET", "/quote", params=params)
        return decode_quote(payload.get("data") or {})

    async def subscribe(
        self, tickers: Iterable[str], fields: Optional[Iterable[str]] = None
    ) -> SubscribeResult:
        """增加订阅（引用计数由网关维护）。"""
        ticker_list = _normalize(tickers)
        if not ticker_list:
            return SubscribeResult((), 0, 0)
        body: dict[str, Any] = {"tickers": ticker_list}
        if fields:
            _validate_mktdata_fields(fields)
            body["fields"] = _normalize(fields)
        payload = await self._call("POST", "/subscriptions", json=body)
        data = payload.get("data") or {}
        return SubscribeResult(
            accepted=tuple(data.get("accepted") or ()),
            rejected=int(data.get("rejected") or 0),
            total=int(data.get("total") or 0),
        )

    async def unsubscribe(
        self, tickers: Optional[Iterable[str]] = None, *, all: bool = False
    ) -> UnsubscribeResult:
        """减少订阅；`all=True` 清空本客户端全部订阅。"""
        body: dict[str, Any] = {"all": True} if all else {"tickers": _normalize(tickers or ())}
        payload = await self._call("DELETE", "/subscriptions", json=body)
        data = payload.get("data") or {}
        return UnsubscribeResult(
            removed=tuple(data.get("removed") or ()),
            remaining=int(data.get("remaining") or 0),
        )

    async def refdata(self, securities: Iterable[str], fields: Iterable[str]) -> dict[str, dict]:
        """参考数据（FX / 本币 / 整手 / 短名）。"""
        security_list = _normalize(securities)
        field_list = _normalize(fields)
        if not security_list or not field_list:
            return {}
        _validate_refdata_fields(field_list)
        params = {"securities": ",".join(security_list), "fields": ",".join(field_list)}
        payload = await self._call("GET", "/refdata", params=params)
        return payload.get("data") or {}

    def open_stream(
        self,
        tickers: Iterable[str],
        fields: Optional[Iterable[str]] = None,
        *,
        connect: Optional[Callable[[str], Any]] = None,
        recv_timeout: float = HEARTBEAT_SECONDS * 3,
    ) -> "GatewayStream":
        """打开 WS 订阅流（返回异步迭代器，需 `async with`）。"""
        ticker_list = _normalize(tickers)
        if fields:
            _validate_mktdata_fields(fields)
            field_list = _normalize(fields)
        else:
            field_list = list(MKTDATA_FIELDS)
        # 必须编码：Bloomberg 复合代码含空格，未编码的 URI 会被 websockets 拒绝（InvalidURI）
        query = "?" + urlencode(
            {"tickers": ",".join(ticker_list), "fields": ",".join(field_list)},
            quote_via=quote,
        )
        return GatewayStream(
            self._base_url + WS_MARKETDATA_PATH + query,
            connect=connect,
            recv_timeout=recv_timeout,
        )


# ── WS 流 ─────────────────────────────────────────────────────────────────────


class GatewayStream:
    """WS 订阅流的异步迭代器。

    `connect` 可注入（默认 `websockets.connect`），便于在无网关环境下测试。
    """

    def __init__(
        self,
        url: str,
        *,
        connect: Optional[Callable[[str], Any]] = None,
        recv_timeout: float = HEARTBEAT_SECONDS * 3,
    ) -> None:
        self._url = url
        self._connect = connect or _default_connect
        # 下限只防 0/负数；生产用 HEARTBEAT_SECONDS * 3，测试可注入极小值
        self._recv_timeout = max(0.05, float(recv_timeout))
        self._ws: Any = None

    async def __aenter__(self) -> "GatewayStream":
        self._ws = await self._connect(self._url)
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    def __aiter__(self) -> AsyncIterator[StreamMessage]:
        return self

    async def __anext__(self) -> StreamMessage:
        """取下一帧；超过 3 个心跳周期无消息判定断链。"""
        if self._ws is None:
            raise StopAsyncIteration
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=self._recv_timeout)
        except asyncio.TimeoutError as exc:
            raise GatewayStreamTimeout(
                f"{self._recv_timeout:.0f}s 内无任何消息（含 heartbeat），判定断链"
            ) from exc
        return parse_stream_message(raw)


async def _default_connect(url: str) -> Any:
    """默认 WS 连接：延迟导入，避免无网关环境强依赖 websockets。"""
    import websockets

    return await websockets.connect(url)


# ── 工具 ──────────────────────────────────────────────────────────────────────


def _normalize(values: Iterable[str]) -> list[str]:
    """去空白、保序去重。Bloomberg 代码区分大小写，故不做大小写归一。"""
    seen: dict[str, None] = {}
    for item in values or ():
        cleaned = str(item or "").strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def _validate_mktdata_fields(fields: Iterable[str]) -> None:
    """前置校验：未知字段不发请求（省一次往返，也避免上游各自解释）。"""
    unknown = [name for name in fields if not is_known_mktdata_field(name)]
    if unknown:
        raise GatewayError(ErrorCode.INVALID_ARGUMENT, f"未知 mktdata 字段: {unknown}")


def _validate_refdata_fields(fields: Iterable[str]) -> None:
    unknown = [name for name in fields if not is_known_refdata_field(name)]
    if unknown:
        raise GatewayError(ErrorCode.INVALID_ARGUMENT, f"未知 refdata 字段: {unknown}")


def is_degraded(payload: dict) -> bool:
    """响应是否为陈旧数据（消费方据此标注时点）。"""
    return bool(payload.get("degraded")) or payload.get("source") == SOURCE_STALE

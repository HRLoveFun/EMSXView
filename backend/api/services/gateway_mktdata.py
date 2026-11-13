"""`on` 模式的网关行情推送消费方（015 §3.2 / §10 步骤 3）。

定位：`EMSXVIEW_GATEWAY_MODE=on` 时替代 `_mktdata_subscription_loop` 独占
`//blp/mktdata` 的消费端。一个守护线程里跑常驻 asyncio 循环：

```
GatewayMktdataFeed
  └─ asyncio.run(_run())
       stream loop:
         async with client.open_stream(tickers, fields) as stream:
             snapshot → 全量写缓存
             tick     → 增量写缓存
             status   → 记录 dropped（网关宽限期到期退订）
             heartbeat→ 只刷新存活时刻
         断链 → 指数退避 1s→2s→…→30s → 重连后重新拿 snapshot
```

纪律：

1. **断链冻结，不清缓存**：最后一次成功的值仍可读；超过 `stale_after`
   只置陈旧标记，由消费方决定是否采用（015 §3.4）。
2. **重连不写熔断器**：WS 断链由本模块自己的退避处理，避免在熔断 open
   期间反复刷新打开时刻（015 §4.2 缺陷 4）。
3. **集合变化重开 WS**：网关 WS 的 ticker 集合在连接建立时固定，不支持
   中途增删；`targets()` 返回值变化时主动关闭并重连。
4. **不猜报文语义**：未知 `type` 只记 debug，不写缓存、不当心跳。

模块只依赖 `gateway_client` 的公开结构（`TickerQuote` / `StreamMessage`），
不导入 `enrichment`——缓存写入通过回调注入，便于单测与后续复用。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import time
from typing import Any, Awaitable, Callable, Iterable, Optional

from platform_data.contracts.gateway_contracts import HEARTBEAT_SECONDS
from services.gateway_client import (
    GatewayClient,
    GatewayError,
    GatewayStreamTimeout,
    StreamMessage,
)

logger = logging.getLogger("main")

#: 断链重连退避上下限（秒）。
BACKOFF_INITIAL_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 30.0

#: 消费循环检查「订阅集合是否变化」与停止信号的间隔（秒）。
POLL_INTERVAL_SECONDS = 1.0

#: 断链后缓存冻结多久标记为陈旧（秒）；与网关退订宽限期对齐。
STALE_AFTER_SECONDS = 60.0

QuotesCallback = Callable[[dict, str, str], None]
StatusCallback = Callable[[dict], None]
HeartbeatCallback = Callable[[str], None]
HousekeepingCallback = Callable[[], Optional[Awaitable[None]]]


def _normalize(values: Iterable[str]) -> list[str]:
    """去空白、保序去重（Bloomberg 代码区分大小写）。"""
    seen: dict[str, None] = {}
    for item in values or ():
        cleaned = str(item or "").strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


class GatewayMktdataFeed:
    """网关 WS 行情推送守护线程。

    参数全部以回调注入：

    - `targets`：返回当前订阅集合（订单标的 ∪ 额外标的）；
    - `fields`：返回订阅字段，必须与直连侧 `mktdata_fields()` 同源；
    - `on_quotes(quotes, ts, kind)`：`snapshot` / `tick` 的已解码载荷；
    - `on_status(status)`：订阅态变更（`dropped` 等）；
    - `on_heartbeat(ts)`：存活信号；
    - `housekeeping()`：可选，按 `housekeeping_interval` 周期执行的维护协程
      （`on` 下用 HTTP refdata 替代直连 refdata）。
    """

    def __init__(
        self,
        client: GatewayClient,
        *,
        targets: Callable[[], Iterable[str]],
        fields: Callable[[], Iterable[str]],
        on_quotes: QuotesCallback,
        on_status: Optional[StatusCallback] = None,
        on_heartbeat: Optional[HeartbeatCallback] = None,
        housekeeping: Optional[HousekeepingCallback] = None,
        backoff_initial: float = BACKOFF_INITIAL_SECONDS,
        backoff_max: float = BACKOFF_MAX_SECONDS,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        housekeeping_interval: float = POLL_INTERVAL_SECONDS,
        stale_after: float = STALE_AFTER_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._targets = targets
        self._fields = fields
        self._on_quotes = on_quotes
        self._on_status = on_status
        self._on_heartbeat = on_heartbeat
        self._housekeeping = housekeeping
        self._backoff_initial = max(0.01, float(backoff_initial))
        self._backoff_max = max(self._backoff_initial, float(backoff_max))
        self._poll_interval = max(0.01, float(poll_interval))
        self._housekeeping_interval = max(0.01, float(housekeeping_interval))
        self._stale_after = max(0.0, float(stale_after))
        self._clock = clock

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # 观测状态（供 enrichment/健康检查读取）
        self._connected = False
        self._last_alive_at: Optional[float] = None
        self._last_disconnect_at: Optional[float] = None
        self._reconnect_attempts = 0
        self._dropped: set[str] = set()

    # ── 生命周期 ──────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """启动守护线程（幂等：先停旧的）。"""
        self.stop()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._thread_main, daemon=True, name="gateway-mktdata"
        )
        self._thread.start()
        logger.info("GatewayMktdataFeed started")

    def stop(self) -> None:
        """置停止信号；线程不在当前线程时等待其退出。"""
        self._stop.set()
        thread = self._thread
        if thread is None:
            return
        if thread is threading.current_thread():
            # 从回调/循环内部调用：只置信号，不能 join 自己
            return
        if thread.is_alive():
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning("GatewayMktdataFeed did not stop within timeout")
        if not thread.is_alive():
            self._thread = None

    # ── 观测状态 ──────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_alive_at(self) -> Optional[float]:
        return self._last_alive_at

    @property
    def reconnect_attempts(self) -> int:
        return self._reconnect_attempts

    @property
    def dropped_tickers(self) -> frozenset[str]:
        return frozenset(self._dropped)

    @property
    def is_stale(self) -> bool:
        """断链且超过 `stale_after` 未收到任何帧（含心跳）即为陈旧。"""
        if self._connected:
            return False
        if self._last_alive_at is None:
            return True
        return (self._clock() - self._last_alive_at) >= self._stale_after

    def status_snapshot(self) -> dict:
        """供 `/health` 或日志使用的只读快照。"""
        return {
            "running": self.is_running,
            "connected": self._connected,
            "stale": self.is_stale,
            "reconnect_attempts": self._reconnect_attempts,
            "dropped": sorted(self._dropped),
            "last_alive_at": self._last_alive_at,
        }

    # ── 线程与事件循环 ────────────────────────────────────────────────

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # noqa: BLE001 - 守护线程异常不能悄悄消失
            if not self._stop.is_set():
                logger.exception("GatewayMktdataFeed 异常退出: %s", exc)
        finally:
            self._connected = False
            logger.info("GatewayMktdataFeed stopped")

    async def _run(self) -> None:
        housekeeping_task: Optional[asyncio.Task] = None
        if self._housekeeping is not None:
            housekeeping_task = asyncio.create_task(self._housekeeping_loop())
        try:
            await self._stream_loop()
        finally:
            if housekeeping_task is not None:
                housekeeping_task.cancel()
                await asyncio.gather(housekeeping_task, return_exceptions=True)
            await self._client.close()
            self._connected = False

    async def _stream_loop(self) -> None:
        """按订阅集合打开 WS；断链后指数退避重连，直到 stop()。"""
        backoff = self._backoff_initial
        while not self._stop.is_set():
            tickers = _normalize(self._targets())
            if not tickers:
                # 没有标的就不建连接：空订阅会让网关拒绝并放大日志
                self._connected = False
                await self._sleep(self._poll_interval)
                continue
            fields = _normalize(self._fields())
            try:
                async with self._client.open_stream(
                    tickers,
                    fields,
                    recv_timeout=max(HEARTBEAT_SECONDS * 3, 1.0),
                ) as stream:
                    self._connected = True
                    self._last_alive_at = self._clock()
                    self._last_disconnect_at = None
                    self._reconnect_attempts = 0
                    backoff = self._backoff_initial
                    logger.info(
                        "GatewayMktdataFeed connected: %d tickers, %d fields",
                        len(tickers),
                        len(fields),
                    )
                    reopen_now = await self._consume(stream, tickers)
                    if reopen_now:
                        # 集合变化：立即用新集合重开，不进退避
                        continue
            except asyncio.CancelledError:
                raise
            except (GatewayStreamTimeout, GatewayError, OSError, ValueError) as exc:
                # 不调用 client/circuit 的 record_failure：WS 断链由本模块退避处理
                self._connected = False
                self._last_disconnect_at = self._clock()
                self._reconnect_attempts += 1
                if not self._stop.is_set():
                    logger.warning(
                        "GatewayMktdataFeed 断链（%s: %s）— %.1fs 后重连（第 %d 次）",
                        type(exc).__name__,
                        exc,
                        backoff,
                        self._reconnect_attempts,
                    )
            except Exception as exc:  # noqa: BLE001 - 未知异常同样退避重连
                self._connected = False
                self._last_disconnect_at = self._clock()
                self._reconnect_attempts += 1
                if not self._stop.is_set():
                    logger.exception(
                        "GatewayMktdataFeed 未预期异常（%s）— %.1fs 后重连",
                        exc,
                        backoff,
                    )
            if self._stop.is_set():
                break
            await self._sleep(backoff)
            backoff = min(backoff * 2, self._backoff_max)

    async def _consume(self, stream: Any, tickers: list[str]) -> bool:
        """消费一条连接上的帧；返回 True 表示订阅集合变化、需立即重开。"""
        expected = set(tickers)
        while not self._stop.is_set():
            # 网关 WS 的 ticker 集合在连接建立时固定：变化即重开
            if set(_normalize(self._targets())) != expected:
                logger.info("GatewayMktdataFeed 订阅集合变化 — 重开 WS")
                return True
            try:
                message = await asyncio.wait_for(
                    stream.__anext__(), timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                continue
            except StopAsyncIteration:
                return False
            self._last_alive_at = self._clock()
            self._dispatch(message)
        return False

    def _dispatch(self, message: StreamMessage) -> None:
        """四类帧分派；未知类型只记 debug。"""
        # 任何帧（含 heartbeat/未知类型）都证明链路活着
        self._last_alive_at = self._clock()
        if message.type in ("snapshot", "tick"):
            if message.data:
                self._on_quotes(message.data, message.ts, message.type)
            return
        if message.type == "status":
            dropped = message.data.get("dropped") if isinstance(message.data, dict) else None
            if dropped:
                self._dropped.update(str(t) for t in dropped)
            if self._on_status is not None:
                self._on_status(message.data if isinstance(message.data, dict) else {})
            return
        if message.type == "heartbeat":
            if self._on_heartbeat is not None:
                self._on_heartbeat(message.ts)
            return
        logger.debug("GatewayMktdataFeed 忽略未知帧类型: %s", message.type)

    async def _housekeeping_loop(self) -> None:
        """周期执行注入的维护协程；异常只告警，不中断行情消费。"""
        while not self._stop.is_set():
            try:
                result = self._housekeeping() if self._housekeeping else None
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 维护失败不影响行情
                logger.warning("GatewayMktdataFeed housekeeping 失败: %s", exc)
            await self._sleep(self._housekeeping_interval)

    async def _sleep(self, seconds: float) -> None:
        """可被 stop() 打断的睡眠（退避最长 30s，不能整段阻塞退出）。

        用真实 monotonic 而非注入的 `clock`：`clock` 只服务观测时间戳，
        测试注入假时钟时不应把休眠循环变成死循环。
        """
        deadline = time.monotonic() + seconds
        while not self._stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.1, remaining))

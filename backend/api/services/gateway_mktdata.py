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

#: 单条 WS 连接的最大标的数。网关 URL 带 ticker 列表，超过约 8KB 会被
#: uvicorn 以 HTTP 400 拒绝（2026-11-16 实测：300 标的/6.4KB 可连，
#: 500 标的/10.5KB 失败）；按 150 个一块，URL 约 2–3KB，留足余量。
MAX_TICKERS_PER_STREAM = 150

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


def _chunk(items: list[str], size: int) -> list[list[str]]:
    """按固定大小切块；`size <= 0` 视为不切。"""
    if size <= 0 or not items:
        return [list(items)] if items else []
    return [items[i : i + size] for i in range(0, len(items), size)]


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
        max_tickers_per_stream: int = MAX_TICKERS_PER_STREAM,
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
        self._max_tickers_per_stream = max(1, int(max_tickers_per_stream))
        self._clock = clock

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # 观测状态（供 enrichment/健康检查读取）
        #: 已连上的分块下标；全部连上才算整体 connected。
        self._connected_chunks: set[int] = set()
        self._chunk_count = 0
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
        return bool(self._connected_chunks)

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
        if self.connected:
            return False
        if self._last_alive_at is None:
            return True
        return (self._clock() - self._last_alive_at) >= self._stale_after

    def status_snapshot(self) -> dict:
        """供 `/health` 或日志使用的只读快照。"""
        return {
            "running": self.is_running,
            "connected": self.connected,
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
                logger.exception("GatewayMktdataFeed exited unexpectedly: %s", exc)
        finally:
            self._connected_chunks.clear()
            logger.info("GatewayMktdataFeed stopped")

    async def _run(self) -> None:
        housekeeping_task: Optional[asyncio.Task] = None
        if self._housekeeping is not None:
            housekeeping_task = asyncio.create_task(self._housekeeping_loop())
        try:
            await self._supervise()
        finally:
            if housekeeping_task is not None:
                housekeeping_task.cancel()
                await asyncio.gather(housekeeping_task, return_exceptions=True)
            await self._client.close()
            self._connected_chunks.clear()

    async def _supervise(self) -> None:
        """按需分块并监督每条连接；订阅集合变化时整体重开。

        单条 WS 的 ticker 列表写在 URL 里，过大会被 uvicorn 以 HTTP 400
        拒绝（2026-11-16 实测：300 标的 / 6.4KB 可连，500 标的 / 10.5KB
        失败）。按 `max_tickers_per_stream` 切块后每条约 2–3KB。
        """
        tasks: dict[int, asyncio.Task] = {}
        current_key: Optional[tuple] = None
        try:
            while not self._stop.is_set():
                tickers = _normalize(self._targets())
                fields = _normalize(self._fields())
                chunks = _chunk(tickers, self._max_tickers_per_stream)
                key = (tuple(tickers), tuple(fields))
                if key != current_key:
                    for task in tasks.values():
                        task.cancel()
                    if tasks:
                        await asyncio.gather(*tasks.values(), return_exceptions=True)
                    tasks = {}
                    self._connected_chunks.clear()
                    self._chunk_count = len(chunks)
                    current_key = key
                    if chunks:
                        logger.info(
                            "GatewayMktdataFeed opening %d stream(s): %d tickers, %d fields",
                            len(chunks),
                            len(tickers),
                            len(fields),
                        )
                        for index, chunk in enumerate(chunks):
                            tasks[index] = asyncio.create_task(
                                self._stream_loop(index, chunk, fields)
                            )
                await self._sleep(self._poll_interval)
        finally:
            for task in tasks.values():
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks.values(), return_exceptions=True)

    async def _stream_loop(
        self, index: int, tickers: list[str], fields: list[str]
    ) -> None:
        """单条分块的连接循环；断链指数退避重连，直到 stop()。"""
        backoff = self._backoff_initial
        while not self._stop.is_set():
            try:
                async with self._client.open_stream(
                    tickers,
                    fields,
                    recv_timeout=max(HEARTBEAT_SECONDS * 3, 1.0),
                ) as stream:
                    self._connected_chunks.add(index)
                    self._last_alive_at = self._clock()
                    self._last_disconnect_at = None
                    if len(self._connected_chunks) == self._chunk_count:
                        self._reconnect_attempts = 0
                    backoff = self._backoff_initial
                    logger.info(
                        "GatewayMktdataFeed connected: chunk %d/%d, %d tickers",
                        index + 1,
                        self._chunk_count,
                        len(tickers),
                    )
                    await self._consume(stream)
            except asyncio.CancelledError:
                raise
            except (GatewayStreamTimeout, GatewayError, OSError, ValueError) as exc:
                # 不调用 client/circuit 的 record_failure：WS 断链由本模块退避处理
                self._last_disconnect_at = self._clock()
                self._reconnect_attempts += 1
                if not self._stop.is_set():
                    logger.warning(
                        "GatewayMktdataFeed disconnected (chunk %d/%d, %s: %s) - "
                        "reconnect in %.1fs (attempt %d)",
                        index + 1,
                        self._chunk_count,
                        type(exc).__name__,
                        exc,
                        backoff,
                        self._reconnect_attempts,
                    )
            except Exception as exc:  # noqa: BLE001 - 未知异常同样退避重连
                self._last_disconnect_at = self._clock()
                self._reconnect_attempts += 1
                if not self._stop.is_set():
                    logger.exception(
                        "GatewayMktdataFeed unexpected error (chunk %d/%d, %s) - "
                        "reconnect in %.1fs",
                        index + 1,
                        self._chunk_count,
                        exc,
                        backoff,
                    )
            finally:
                self._connected_chunks.discard(index)
            if self._stop.is_set():
                break
            await self._sleep(backoff)
            backoff = min(backoff * 2, self._backoff_max)

    async def _consume(self, stream: Any) -> None:
        """消费一条连接上的帧；订阅集合变化由 supervisor 统一处理。"""
        while not self._stop.is_set():
            try:
                message = await asyncio.wait_for(
                    stream.__anext__(), timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                continue
            except StopAsyncIteration:
                return
            self._last_alive_at = self._clock()
            self._dispatch(message)

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
        logger.debug("GatewayMktdataFeed ignoring unknown frame type: %s", message.type)

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
                logger.warning("GatewayMktdataFeed housekeeping failed: %s", exc)
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

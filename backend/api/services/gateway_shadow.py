"""网关影子比对（`EMSXVIEW_GATEWAY_MODE=shadow`）。

定位：直连 Bloomberg 仍是唯一数据来源，本模块只**旁路采样**——同一标的、同一字段，
直连缓存已有时，向网关再取一次，把两侧取值与一致与否落一条 JSONL。它不改变任何
业务返回值，网关出错也不影响请求，因此可以安全地常开。

三条纪律：

1. **不阻塞主链路**：采样在独立守护线程里跑，直连侧只做一次 `snapshot()` 拷贝；
2. **不改变行为**：本模块不写任何业务缓存，只读；
3. **失败也要留痕**：网关不可达 / 熔断 / 契约不符都记成 `gw_error`，不算「不一致」，
   但必须能在报表里与「取值不同」区分开——否则网关全挂会显示成 100% 不一致。

落盘格式（每行一条）：

    {"ts": "...", "ticker": "...", "field": "...", "direct": 1.23,
     "gateway": 1.23, "match": true, "rel_diff": 0.0,
     "gateway_recv_ts": "2026-11-11T20:23:56.250+08:00"}

`gateway_recv_ts` 是网关收到该值的时刻（网关字段缺失时为 null），用于区分
「网关值旧（缓存滞后）」与「两侧值本身不同」；`gateway_src_ts` 仍保留原义。

一致判据：双方都是数值时按相对误差 `<= tolerance`（默认 1e-6，即「同一 tick」级别）；
其余情况按严格相等。网关侧 `None`（未推送 / 未订阅）记为不一致，并在 `reason` 里
写明 `gateway_missing`，便于报表拆分「缺数据」与「值不同」。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from services.gateway_client import GatewayError

logger = logging.getLogger("main")

#: 契约错误码 2004「请求字段均无推送值」：`client_action=mark_gap`，
#: 属正常结果而非网关故障（见 `platform_data/contracts/gateway_contracts.py`）。
FIELD_UNAVAILABLE_CODE = 2004

#: 一致判据的默认相对误差。1e-6 远小于任何报价的最小变动单位，
#: 又能吸收 float32/float64 往返带来的末位差异。
DEFAULT_TOLERANCE = 1e-6

#: 单轮采样的默认间隔（秒）。影子模式只用于观测，不需要跟满 tick 频率。
DEFAULT_INTERVAL_SECONDS = 30.0

#: 单轮最多比对多少个标的。每标的一次 HTTP 往返，太大反而拖慢采样周期。
DEFAULT_MAX_TICKERS = 50


def compare_value(direct: Any, gateway: Any, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """比较两侧取值，返回 `{match, rel_diff, reason}`（纯函数，单测覆盖）。

    `reason` 只在不一致时出现：`gateway_missing`（网关没这个字段）、
    `direct_missing`（直连没这个字段）、`type_mismatch`、`value_diff`。
    """
    if gateway is None and direct is None:
        return {"match": True, "rel_diff": 0.0, "reason": None}
    if gateway is None:
        return {"match": False, "rel_diff": None, "reason": "gateway_missing"}
    if direct is None:
        return {"match": False, "rel_diff": None, "reason": "direct_missing"}

    both_numeric = (
        isinstance(direct, (int, float))
        and isinstance(gateway, (int, float))
        and not isinstance(direct, bool)
        and not isinstance(gateway, bool)
    )
    if both_numeric:
        direct_f, gateway_f = float(direct), float(gateway)
        # NaN 不等于任何值（含自身）：两侧都 NaN 视为一致，单侧 NaN 视为不一致
        if direct_f != direct_f or gateway_f != gateway_f:
            same = direct_f != direct_f and gateway_f != gateway_f
            return {"match": same, "rel_diff": None, "reason": None if same else "value_diff"}
        scale = max(abs(direct_f), abs(gateway_f), 1e-12)
        rel_diff = abs(direct_f - gateway_f) / scale
        match = rel_diff <= tolerance
        return {"match": match, "rel_diff": rel_diff, "reason": None if match else "value_diff"}

    if isinstance(direct, str) and isinstance(gateway, str):
        match = direct.strip() == gateway.strip()
        return {"match": match, "rel_diff": None, "reason": None if match else "value_diff"}

    if type(direct) is not type(gateway) and not both_numeric:
        return {"match": False, "rel_diff": None, "reason": "type_mismatch"}
    match = direct == gateway
    return {"match": match, "rel_diff": None, "reason": None if match else "value_diff"}


def _json_default(value: Any) -> Any:
    """JSONL 兜底序列化：不可序列化的类型降级为字符串，不丢整行。"""
    return str(value)


class ShadowRecorder:
    """把影子比对结果按天追加到 `<dir>/gateway_shadow_YYYYMMDD.jsonl`。

    写失败只记日志、不抛：影子比对是观测手段，不能反过来影响主链路。
    """

    def __init__(self, directory: Path, clock: Callable[[], datetime] = datetime.now) -> None:
        self._dir = Path(directory)
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path:
        return self._dir

    def path_for(self, moment: datetime) -> Path:
        return self._dir / f"gateway_shadow_{moment.strftime('%Y%m%d')}.jsonl"

    def record(self, rows: Iterable[dict]) -> int:
        """追加一批记录；返回写入条数（写失败返回 0）。"""
        rows = list(rows)
        if not rows:
            return 0
        path = self.path_for(self._clock())
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with self._lock, path.open("a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")
        except OSError as exc:
            logger.warning("gateway shadow: 写入 %s 失败: %s", path, exc)
            return 0
        return len(rows)


class ShadowSampler:
    """单轮采样器：拿直连快照 → 向网关取同批字段 → 比对 → 落盘。

    `direct_snapshot` 返回 `{ticker: {field: value}}`；`gateway_quote` 是
    `GatewayClient.quote` 的异步方法。两者都可注入，便于离线测试。
    """

    def __init__(
        self,
        direct_snapshot: Callable[[], dict[str, dict[str, Any]]],
        gateway_quote: Callable[[list[str], list[str]], Any],
        recorder: ShadowRecorder,
        *,
        fields: Iterable[str],
        gateway_subscribe: Optional[Callable[[list[str], list[str]], Any]] = None,
        gateway_unsubscribe: Optional[Callable[[list[str]], Any]] = None,
        gateway_close: Optional[Callable[[], Any]] = None,
        tolerance: float = DEFAULT_TOLERANCE,
        max_tickers: int = DEFAULT_MAX_TICKERS,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._direct_snapshot = direct_snapshot
        self._gateway_quote = gateway_quote
        self._recorder = recorder
        self._fields = tuple(fields)
        self._gateway_subscribe = gateway_subscribe
        self._gateway_unsubscribe = gateway_unsubscribe
        self._gateway_close = gateway_close
        self._subscribed: set[str] = set()
        self._tolerance = float(tolerance)
        self._max_tickers = max(1, int(max_tickers))
        self._clock = clock

    async def sample_once(self) -> dict[str, Any]:
        """采一轮；返回统计 `{tickers, compared, matched, mismatched, gw_error}`。

        时点对齐（S3）：直连快照与网关快照各记一个取数时刻。行上的 `ts` 仍是
        「网关快照取完」的时刻（口径不变），新增 `direct_ts` = 取直连快照的时刻。
        旧实现只在「取完 50 个 `/quote`」之后打 `ts`，直连值却是在这之前取的，
        于是每一行都自带一个请求周期（0.25–1s）的时点错配，`recv_lag` 也被系统性抬高；
        现在 `ts - direct_ts` 就是本轮真实的取数跨度，报表（`sampling_span`）
        可以据此判断时点差里有多少是采样放大。
        """
        direct_ts = self._clock().isoformat(timespec="milliseconds")
        snapshot = self._direct_snapshot() or {}
        tickers = sorted(snapshot)[: self._max_tickers]
        stats: dict[str, Any] = {
            "tickers": len(tickers),
            "compared": 0,
            "matched": 0,
            "mismatched": 0,
            "gw_error": None,
        }
        if not tickers:
            return stats

        try:
            await self._sync_subscriptions(tickers)
        except Exception as exc:  # noqa: BLE001 - 网关任何失败都只记一笔，不影响直连
            stats["gw_error"] = f"{type(exc).__name__}: {exc}"
            logger.debug("gateway shadow: 本轮订阅失败: %s", stats["gw_error"])
            self._emit_error(tickers, stats["gw_error"])
            return stats

        try:
            quotes = await self._quote_per_ticker(tickers)
        except Exception as exc:  # noqa: BLE001 - 网关任何失败都只记一笔，不影响直连
            stats["gw_error"] = f"{type(exc).__name__}: {exc}"
            logger.debug("gateway shadow: 本轮采样失败: %s", stats["gw_error"])
            self._emit_error(tickers, stats["gw_error"])
            return stats
        gateway_ts = self._clock().isoformat(timespec="milliseconds")

        # 网关重启 / 订阅过期后本地缓存会失真：以服务端 `_meta.subscribed` 为准，
        # 掉线的标的从本地集合移除，下一轮自动补订。
        for ticker, quote in quotes.items():
            if getattr(quote, "subscribed", True) is False:
                self._subscribed.discard(ticker)

        rows: list[dict] = []
        for ticker in tickers:
            direct_fields = snapshot.get(ticker) or {}
            quote = quotes.get(ticker)
            for field in self._fields:
                direct_value = direct_fields.get(field)
                gateway_field = quote.get(field) if quote is not None else None
                gateway_value = gateway_field.value if gateway_field is not None else None
                verdict = compare_value(direct_value, gateway_value, self._tolerance)
                stats["compared"] += 1
                if verdict["match"]:
                    stats["matched"] += 1
                else:
                    stats["mismatched"] += 1
                rows.append(
                    {
                        "ts": gateway_ts,
                        "direct_ts": direct_ts,
                        "ticker": ticker,
                        "field": field,
                        "direct": direct_value,
                        "gateway": gateway_value,
                        "match": verdict["match"],
                        "rel_diff": verdict["rel_diff"],
                        "reason": verdict["reason"],
                        "gateway_src_ts": gateway_field.src_ts if gateway_field else None,
                        # 网关收到该值的时刻（必有）：排查「网关值旧」还是「两侧值本身不同」
                        "gateway_recv_ts": gateway_field.recv_ts if gateway_field else None,
                    }
                )
        self._recorder.record(rows)
        return stats

    async def _quote_per_ticker(self, tickers: list[str]) -> dict[str, Any]:
        """按标的逐个取 `/quote`，把 2004 还原成「该标的无值」。

        网关的 2004 是**整批**语义（`quote_code`：这批 ticker 上一个值都没有才返回），
        而 `build_quote` 的 `data` 里其实带着每个 ticker 的 gaps。客户端按契约把非 0
        一律抛 `GatewayError`，于是「50 个标的里 49 个没值」也会把有值的那一个一起
        丢掉——实测 2026-11-10 20:48–20:49 的 6 条 `gateway_missing` 就是这么来的：
        采样集轮换到新标的时，整批里只有新标的没值，整批被判 2004，老标的的值全丢。

        逐标的请求后，2004 只可能意味着「这个标的确实没值」，与直连缺值同义，
        记 `gateway_missing` 即可；其余错误码照常上抛，由调用方记 `gw_error`。
        """
        quotes: dict[str, Any] = {}
        for ticker in tickers:
            try:
                batch = await self._gateway_quote([ticker], list(self._fields))
            except GatewayError as exc:
                if exc.code != FIELD_UNAVAILABLE_CODE:
                    raise
                continue
            quotes.update(batch or {})
        return quotes

    async def _sync_subscriptions(self, tickers: list[str]) -> None:
        """让网关订阅面与直连采样集合同步。

        网关 `/quote` 只读订阅缓存、不回源、也不隐式订阅；不先 `subscribe`，
        影子报表会全是 `gateway_missing`。订阅引用计数由网关维护，因此这里只对
        「新进入采样集」的标的订阅一次，离开采样集时退订，避免常开运行把计数堆高。
        """
        if self._gateway_subscribe is None:
            return
        current = set(tickers)
        # 先退订离开的标的，释放网关配额，避免「订阅上限」把轮换永久卡死
        dropped = sorted(self._subscribed - current)
        if dropped and self._gateway_unsubscribe is not None:
            await self._gateway_unsubscribe(dropped)
            self._subscribed.difference_update(dropped)
        added = sorted(current - self._subscribed)
        if added:
            result = await self._gateway_subscribe(added, list(self._fields))
            # 只记网关真正接受的标的：被拒（配额 / 非法 ticker）下轮重试，
            # 且退订时不会误减从未增加的引用计数
            accepted = getattr(result, "accepted", None)
            self._subscribed.update(accepted if accepted is not None else added)

    async def close(self) -> None:
        """退订本采样器持有的网关订阅并关闭客户端；失败只记日志。"""
        try:
            if self._gateway_unsubscribe is not None and self._subscribed:
                try:
                    await self._gateway_unsubscribe(sorted(self._subscribed))
                    self._subscribed.clear()
                except Exception as exc:  # noqa: BLE001 - 退订失败不能挡住关客户端
                    logger.debug("gateway shadow: 退订失败: %s", exc)
        finally:
            if self._gateway_close is not None:
                try:
                    await self._gateway_close()
                except Exception as exc:  # noqa: BLE001 - 收尾失败不影响退出
                    logger.debug("gateway shadow: 关闭网关客户端失败: %s", exc)

    def _emit_error(self, tickers: list[str], message: str) -> None:
        """网关侧失败也落一行，让报表能区分「网关挂了」与「数据不一致」。"""
        ts = self._clock().isoformat(timespec="milliseconds")
        self._recorder.record(
            [
                {
                    "ts": ts,
                    "direct_ts": ts,
                    "ticker": ticker,
                    "field": None,
                    "direct": None,
                    "gateway": None,
                    "match": None,
                    "rel_diff": None,
                    "reason": "gw_error",
                    "error": message,
                }
                for ticker in tickers
            ]
        )


def _lag_seconds(row: dict) -> Optional[float]:
    """行 `ts` 与 `gateway_recv_ts` 的墙钟差（秒）；任一缺失或解析失败返回 None。

    `gateway_recv_ts` 带时区偏移（如 `+08:00`），行 `ts` 是 naive local ISO；这里
    直接比较墙钟时间（丢弃偏移），即假定网关与本机处于同一时区。跨时区部署时
    该值只能当相对参考，不能当绝对延迟。旧格式行没有 `gateway_recv_ts`，返回 None。

    S3 之后 `ts` 是「网关快照取完」的时刻，而网关值是在这之前一批批取回的；
    这条滞后因此含了本轮取数耗时。`sampling_span_seconds` 给出该耗时，两者相减
    才是「网关值相对取回时刻有多旧」。
    """
    recv = row.get("gateway_recv_ts")
    ts = row.get("ts")
    if not isinstance(recv, str) or not isinstance(ts, str):
        return None
    try:
        recv_dt = datetime.fromisoformat(recv)
        ts_dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if recv_dt.tzinfo is not None:
        recv_dt = recv_dt.replace(tzinfo=None)
    if ts_dt.tzinfo is not None:
        ts_dt = ts_dt.replace(tzinfo=None)
    return (ts_dt - recv_dt).total_seconds()


def _sampling_span_seconds(row: dict) -> Optional[float]:
    """行 `ts` 与 `direct_ts` 的差（秒）= 本轮从取直连快照到取完网关快照的耗时。

    旧格式行没有 `direct_ts`，返回 None。
    """
    direct = row.get("direct_ts")
    ts = row.get("ts")
    if not isinstance(direct, str) or not isinstance(ts, str):
        return None
    try:
        direct_dt = datetime.fromisoformat(direct)
        ts_dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if direct_dt.tzinfo is not None:
        direct_dt = direct_dt.replace(tzinfo=None)
    if ts_dt.tzinfo is not None:
        ts_dt = ts_dt.replace(tzinfo=None)
    return (ts_dt - direct_dt).total_seconds()


# 陈旧度分层：同一时点级别（≤5s 足够覆盖 30s 采样周期内的正常投递差异）
LAG_BUCKETS = ("le_5s", "5s_to_30s", "gt_30s", "unknown")


def _lag_bucket_name(lag: Optional[float]) -> str:
    """把滞后秒数映射到分层名；`None`（旧格式行 / 网关侧无值）归 `unknown`。"""
    if lag is None:
        return "unknown"
    if lag <= 5:
        return "le_5s"
    if lag <= 30:
        return "5s_to_30s"
    return "gt_30s"


def _percentile(sorted_values: list[float], q: float) -> Optional[float]:
    """线性插值分位数；空列表返回 None。调用方保证入参已升序。"""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    low = math.floor(pos)
    high = min(low + 1, len(sorted_values) - 1)
    frac = pos - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac


def summarize(rows: Iterable[dict]) -> dict[str, Any]:
    """把 JSONL 行汇总成一致率报表（纯函数，供 CLI 与测试复用）。

    一致率只在「双方都有值」的样本上计算：`gateway_missing` / `direct_missing`
    单独计数，不和「值不同」混在一个分母里——否则网关某字段没推送会把一致率
    压到 0，看起来像数据错，实际是覆盖度问题。

    **两侧都无值的样本不算进一致率**。它记在 `both_missing` 里，`match_rate`
    的分母 `both_present` 不含它。否则像 `CHG_PCT_1D` 这种本机根本不推送的字段，
    每一轮都记一条「两侧都无 → 一致」，一致率会被抬到 100%，掩盖真实覆盖度
    （2026-11-10 实测踩到：5400 样本里 3700 条是两侧都无值）。

    **「容差内一致」与「精确相等」分开计数**（`near_match`）。`matched` 含两者，
    但若只报 `matched`，读者会把「落在 1e-6 内」读成「数值一模一样」——实测
    2026-11-10 有 2 条 VWAP 差在末位（237.5155 vs 237.5153）被判一致，单看
    一致率看不出这层差别。

    **按「网关值陈旧度」分层统计**（`by_lag`）。两侧值不同有两个完全不同的成因：
    网关算错了，还是网关给的是几十秒前的缓存快照。`gateway_recv_ts` 能区分它们，
    所以一致率按 `le_5s` / `5s_to_30s` / `gt_30s` / `unknown`（旧格式行或网关无值）
    分开报：同一时点级别内的样本才说明网关「同一 tick 上是否算对」，跨时点的差异
    只能说明网关投递滞后。2026-11-11 实测：静态时段两侧精确相等，但 `recv_ts`
    落后采样时刻最多 116 秒，网关只重复投递缓存快照，未带事件时间戳。

    **取数跨度**（`sampling_span`）：`ts` 是网关快照取完的时刻，`direct_ts` 是本轮
    开始取直连快照的时刻，两者之差就是这一轮串行取数花了多久。旧实现只在全部
    `/quote` 返回后才打 `ts`，跨度被整个算进 `gateway_lag`，读者会把采样耗时
    误读成网关投递延迟；现在单独给出 p50/p90/max，`gateway_lag` 里含多少采样
    开销一目了然。

    **不一致样本的误差分布**（`value_diff`）。只报条数，读者无法判断「差一点」还是
    「差一个量级」；给出 `|rel_diff|` 的 p50/p90/p99/max 与 `lt_1e_2` 占比，就能直接
    看出分歧的量级。
    """
    total = 0
    matched = 0
    exact = 0
    near = 0
    both_present = 0
    both_missing = 0
    reasons: dict[str, int] = {}
    errors = 0
    lag_samples = 0
    max_lag: Optional[float] = None
    stale_gt_5s = 0
    stale_gt_30s = 0
    by_lag = {
        name: {"samples": 0, "both_present": 0, "matched": 0, "exact": 0, "near_match": 0}
        for name in LAG_BUCKETS
    }
    diff_abs: list[float] = []
    diff_lt_1e_2 = 0
    span_samples: list[float] = []
    by_field: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("field") is None:
            errors += 1
            continue
        total += 1
        field = str(row.get("field"))
        bucket = by_field.setdefault(
            field,
            {
                "total": 0,
                "both_present": 0,
                "both_missing": 0,
                "matched": 0,
                "exact": 0,
                "near_match": 0,
                "max_lag_seconds": None,
            },
        )
        bucket["total"] += 1
        span = _sampling_span_seconds(row)
        if span is not None:
            span_samples.append(span)
        # 网关值陈旧度：recv_ts 距离本轮采样时刻有多久（旧格式行无此字段，跳过）
        lag = _lag_seconds(row)
        if lag is not None:
            lag_samples += 1
            if max_lag is None or lag > max_lag:
                max_lag = lag
            if lag > 5:
                stale_gt_5s += 1
            if lag > 30:
                stale_gt_30s += 1
            field_max = bucket["max_lag_seconds"]
            if field_max is None or lag > field_max:
                bucket["max_lag_seconds"] = lag
        lag_bucket = by_lag[_lag_bucket_name(lag)]
        lag_bucket["samples"] += 1
        reason = row.get("reason")
        if row.get("match"):
            if row.get("direct") is None and row.get("gateway") is None:
                both_missing += 1
                bucket["both_missing"] += 1
                continue
            matched += 1
            both_present += 1
            bucket["matched"] += 1
            bucket["both_present"] += 1
            lag_bucket["matched"] += 1
            lag_bucket["both_present"] += 1
            if row.get("direct") == row.get("gateway"):
                exact += 1
                bucket["exact"] += 1
                lag_bucket["exact"] += 1
            else:
                near += 1
                bucket["near_match"] += 1
                lag_bucket["near_match"] += 1
            continue
        if reason in ("gateway_missing", "direct_missing"):
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        both_present += 1
        bucket["both_present"] += 1
        lag_bucket["both_present"] += 1
        reasons[str(reason or "value_diff")] = reasons.get(str(reason or "value_diff"), 0) + 1
        # 分歧量级：只对「两侧都有值但不同」的样本统计（缺失类不进）
        rel_diff = row.get("rel_diff")
        if isinstance(rel_diff, (int, float)):
            value = abs(float(rel_diff))
            diff_abs.append(value)
            if value < 1e-2:
                diff_lt_1e_2 += 1
    return {
        "samples": total,
        "matched": matched,
        "exact": exact,
        "near_match": near,
        "both_present": both_present,
        "both_missing": both_missing,
        "match_rate": (matched / both_present) if both_present else None,
        "exact_rate": (exact / both_present) if both_present else None,
        "reasons": reasons,
        "errors": errors,
        "gateway_lag": {
            "samples": lag_samples,
            "max_seconds": max_lag,
            "stale_gt_5s": stale_gt_5s,
            "stale_gt_30s": stale_gt_30s,
        },
        # 本轮取数跨度（直连快照 → 网关快照取完），用于判断时点差是否被采样放大
        "sampling_span": {
            "samples": len(span_samples),
            "p50_seconds": _percentile(sorted(span_samples), 0.5) if span_samples else None,
            "p90_seconds": _percentile(sorted(span_samples), 0.9) if span_samples else None,
            "max_seconds": max(span_samples) if span_samples else None,
        },
        "by_lag": {
            name: {
                **lag_bucket,
                "match_rate": (lag_bucket["matched"] / lag_bucket["both_present"])
                if lag_bucket["both_present"]
                else None,
                "exact_rate": (lag_bucket["exact"] / lag_bucket["both_present"])
                if lag_bucket["both_present"]
                else None,
            }
            for name, lag_bucket in by_lag.items()
        },
        "value_diff": {
            "samples": len(diff_abs),
            "abs_rel_diff_p50": _percentile(sorted(diff_abs), 0.5) if diff_abs else None,
            "abs_rel_diff_p90": _percentile(sorted(diff_abs), 0.9) if diff_abs else None,
            "abs_rel_diff_p99": _percentile(sorted(diff_abs), 0.99) if diff_abs else None,
            "abs_rel_diff_max": max(diff_abs) if diff_abs else None,
            "lt_1e_2": diff_lt_1e_2,
        },
        "by_field": {
            name: {
                **bucket,
                "match_rate": (bucket["matched"] / bucket["both_present"]) if bucket["both_present"] else None,
                "exact_rate": (bucket["exact"] / bucket["both_present"]) if bucket["both_present"] else None,
            }
            for name, bucket in sorted(by_field.items())
        },
    }


class ShadowRunner:
    """守护线程：按固定间隔调用 `sample_once()`，直到 `stop()`。"""

    def __init__(
        self,
        sampler: ShadowSampler,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._sampler = sampler
        self._interval = max(1.0, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_stats: Optional[dict[str, Any]] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="gateway-shadow")
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    @property
    def last_stats(self) -> Optional[dict[str, Any]]:
        return self._last_stats

    @property
    def is_running(self) -> bool:
        """采样线程是否仍在运行（供上层做幂等启动判断）。"""
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception:  # noqa: BLE001 - 线程入口兜底，避免未处理异常打印
            logger.exception("gateway shadow: 采样线程异常退出")

    async def _run(self) -> None:
        """整个线程只建一个事件循环。

        `httpx.AsyncClient` 的连接池绑定在创建它的循环上；若每轮 `asyncio.run`
        新建循环而客户端跨轮复用，第二轮起会抛 `Event loop is closed`，把一半
        样本记成 `gw_error`。因此循环常驻，轮间只做可中断等待。
        """
        try:
            while not self._stop.is_set():
                try:
                    self._last_stats = await self._sampler.sample_once()
                except Exception:  # noqa: BLE001 - 影子线程不能因单轮异常退出
                    logger.exception("gateway shadow: 采样轮次异常")
                await asyncio.to_thread(self._stop.wait, self._interval)
        finally:
            try:
                await self._sampler.close()
            except Exception:  # noqa: BLE001 - 收尾失败不影响线程退出
                logger.exception("gateway shadow: 采样器收尾异常")


# ── CLI：把 JSONL 汇总成一致率报表 ────────────────────────────────────────────


def _iter_rows(paths: Iterable[Path]) -> Iterable[dict]:
    for path in paths:
        with Path(path).open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def main(argv: Optional[list[str]] = None) -> int:
    """`python -m services.gateway_shadow <jsonl...>` → 一致率报表（JSON）。"""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("用法: python -m services.gateway_shadow <gateway_shadow_*.jsonl> ...")
        return 2
    report = summarize(_iter_rows(Path(arg) for arg in args))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - 手工运维入口
    raise SystemExit(main())

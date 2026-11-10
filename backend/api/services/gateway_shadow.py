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
     "gateway": 1.23, "match": true, "rel_diff": 0.0}

一致判据：双方都是数值时按相对误差 `<= tolerance`（默认 1e-6，即「同一 tick」级别）；
其余情况按严格相等。网关侧 `None`（未推送 / 未订阅）记为不一致，并在 `reason` 里
写明 `gateway_missing`，便于报表拆分「缺数据」与「值不同」。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger("main")

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
        tolerance: float = DEFAULT_TOLERANCE,
        max_tickers: int = DEFAULT_MAX_TICKERS,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._direct_snapshot = direct_snapshot
        self._gateway_quote = gateway_quote
        self._recorder = recorder
        self._fields = tuple(fields)
        self._tolerance = float(tolerance)
        self._max_tickers = max(1, int(max_tickers))
        self._clock = clock

    async def sample_once(self) -> dict[str, Any]:
        """采一轮；返回统计 `{tickers, compared, matched, mismatched, gw_error}`。"""
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
            quotes = await self._gateway_quote(tickers, list(self._fields))
        except Exception as exc:  # noqa: BLE001 - 网关任何失败都只记一笔，不影响直连
            stats["gw_error"] = f"{type(exc).__name__}: {exc}"
            logger.debug("gateway shadow: 本轮采样失败: %s", stats["gw_error"])
            self._emit_error(tickers, stats["gw_error"])
            return stats

        ts = self._clock().isoformat(timespec="milliseconds")
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
                        "ts": ts,
                        "ticker": ticker,
                        "field": field,
                        "direct": direct_value,
                        "gateway": gateway_value,
                        "match": verdict["match"],
                        "rel_diff": verdict["rel_diff"],
                        "reason": verdict["reason"],
                        "gateway_src_ts": gateway_field.src_ts if gateway_field else None,
                    }
                )
        self._recorder.record(rows)
        return stats

    def _emit_error(self, tickers: list[str], message: str) -> None:
        """网关侧失败也落一行，让报表能区分「网关挂了」与「数据不一致」。"""
        ts = self._clock().isoformat(timespec="milliseconds")
        self._recorder.record(
            [
                {
                    "ts": ts,
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


def summarize(rows: Iterable[dict]) -> dict[str, Any]:
    """把 JSONL 行汇总成一致率报表（纯函数，供 CLI 与测试复用）。

    一致率只在「双方都有值」的样本上计算：`gateway_missing` / `direct_missing`
    单独计数，不和「值不同」混在一个分母里——否则网关某字段没推送会把一致率
    压到 0，看起来像数据错，实际是覆盖度问题。
    """
    total = 0
    matched = 0
    both_present = 0
    reasons: dict[str, int] = {}
    errors = 0
    by_field: dict[str, dict[str, int]] = {}
    for row in rows:
        if row.get("field") is None:
            errors += 1
            continue
        total += 1
        field = str(row.get("field"))
        bucket = by_field.setdefault(field, {"total": 0, "matched": 0})
        bucket["total"] += 1
        reason = row.get("reason")
        if row.get("match"):
            matched += 1
            both_present += 1
            bucket["matched"] += 1
            continue
        if reason in ("gateway_missing", "direct_missing"):
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        both_present += 1
        reasons[str(reason or "value_diff")] = reasons.get(str(reason or "value_diff"), 0) + 1
    return {
        "samples": total,
        "matched": matched,
        "both_present": both_present,
        "match_rate": (matched / both_present) if both_present else None,
        "reasons": reasons,
        "errors": errors,
        "by_field": {
            name: {
                **bucket,
                "match_rate": (bucket["matched"] / bucket["total"]) if bucket["total"] else None,
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

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._last_stats = asyncio.run(self._sampler.sample_once())
            except Exception:  # noqa: BLE001 - 影子线程不能因单轮异常退出
                logger.exception("gateway shadow: 采样轮次异常")
            self._stop.wait(self._interval)


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

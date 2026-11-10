"""013 P4 影子比对单测（不连真实网关，不依赖 Bloomberg 终端）。

覆盖四类风险：

1. **一致判据**：数值按相对误差、字符串按去空白、单侧缺失单独归因；
2. **不改变行为**：网关失败只记 `gw_error`，不抛、不写业务缓存；
3. **落盘格式**：按天分文件、每行一条 JSON、写失败不抛；
4. **报表口径**：一致率只在「双方都有值」上算，缺失单独计数。
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import gateway_shadow as gs  # noqa: E402
from services.gateway_client import FieldValue, GatewayUnavailable, TickerQuote  # noqa: E402

FIELDS = ("CHG_PCT_1D", "VOLUME_AVG_5D", "VWAP")


def _quote(**values) -> TickerQuote:
    return TickerQuote(
        ticker="X",
        fields={name: FieldValue(value=v, src_ts=None, recv_ts="2026-11-10T10:00:00+08:00")
                for name, v in values.items()},
        subscribed=True,
    )


def _read_rows(directory: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(directory.glob("gateway_shadow_*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return rows


# ── 一致判据 ──────────────────────────────────────────────────────────────────


def test_numeric_match_within_tolerance() -> None:
    assert gs.compare_value(1.234567, 1.2345670001)["match"] is True
    assert gs.compare_value(1.0, 1.0 + 1e-9)["match"] is True


def test_numeric_mismatch_reports_relative_difference() -> None:
    verdict = gs.compare_value(100.0, 101.0)
    assert verdict["match"] is False
    assert verdict["reason"] == "value_diff"
    assert abs(verdict["rel_diff"] - 1 / 101) < 1e-12


def test_nan_on_both_sides_counts_as_match() -> None:
    nan = float("nan")
    assert gs.compare_value(nan, nan)["match"] is True
    assert gs.compare_value(nan, 1.0)["match"] is False


def test_missing_side_is_attributed_not_mixed_with_value_diff() -> None:
    assert gs.compare_value(1.0, None)["reason"] == "gateway_missing"
    assert gs.compare_value(None, 1.0)["reason"] == "direct_missing"
    assert gs.compare_value(None, None)["match"] is True


def test_strings_compare_after_strip_and_never_raise_on_type_mismatch() -> None:
    assert gs.compare_value("USD ", "USD")["match"] is True
    assert gs.compare_value("USD", "EUR")["reason"] == "value_diff"
    assert gs.compare_value(1, "1")["reason"] == "type_mismatch"


# ── 采样与落盘 ────────────────────────────────────────────────────────────────


def test_sample_once_writes_one_row_per_ticker_field(tmp_path) -> None:
    direct = {"AAPL US Equity": {"CHG_PCT_1D": 1.5, "VWAP": 200.0}}

    async def gateway_quote(tickers, fields):
        assert tickers == ["AAPL US Equity"]
        assert fields == list(FIELDS)
        return {"AAPL US Equity": _quote(CHG_PCT_1D=1.5, VWAP=200.0)}

    sampler = gs.ShadowSampler(
        lambda: direct, gateway_quote, gs.ShadowRecorder(tmp_path), fields=FIELDS
    )
    stats = asyncio.run(sampler.sample_once())

    assert stats["tickers"] == 1
    assert stats["compared"] == len(FIELDS)
    # CHG_PCT_1D + VWAP 一致；VOLUME_AVG_5D 两侧都无 → 也算一致（都缺比「缺 vs 有」更安全）
    assert stats["matched"] == 3
    assert stats["mismatched"] == 0
    assert stats["gw_error"] is None
    rows = _read_rows(tmp_path)
    assert len(rows) == len(FIELDS)
    assert {row["field"] for row in rows} == set(FIELDS)


def test_gateway_failure_is_recorded_but_never_raised(tmp_path) -> None:
    async def gateway_quote(tickers, fields):
        raise GatewayUnavailable("circuit open")

    sampler = gs.ShadowSampler(
        lambda: {"AAPL US Equity": {"VWAP": 1.0}},
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=FIELDS,
    )
    stats = asyncio.run(sampler.sample_once())

    assert stats["gw_error"].startswith("GatewayUnavailable")
    assert stats["compared"] == 0
    rows = _read_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["reason"] == "gw_error"
    assert rows[0]["ticker"] == "AAPL US Equity"


def test_empty_direct_snapshot_does_not_call_gateway(tmp_path) -> None:
    calls: list[list[str]] = []

    async def gateway_quote(tickers, fields):
        calls.append(tickers)
        return {}

    sampler = gs.ShadowSampler(lambda: {}, gateway_quote, gs.ShadowRecorder(tmp_path), fields=FIELDS)
    stats = asyncio.run(sampler.sample_once())

    assert calls == []
    assert stats["compared"] == 0
    assert _read_rows(tmp_path) == []


def test_recorder_partitions_by_day(tmp_path) -> None:
    moments = iter([datetime(2026, 11, 10, 9, 0), datetime(2026, 11, 11, 9, 0)])
    recorder = gs.ShadowRecorder(tmp_path, clock=lambda: next(moments))
    recorder.record([{"field": "VWAP"}])
    recorder.record([{"field": "VWAP"}])

    assert (tmp_path / "gateway_shadow_20261110.jsonl").exists()
    assert (tmp_path / "gateway_shadow_20261111.jsonl").exists()


def test_recorder_swallows_write_errors(tmp_path) -> None:
    # 用文件占住目录名，mkdir 必然失败
    blocker = tmp_path / "blocked"
    blocker.write_text("x", encoding="utf-8")
    recorder = gs.ShadowRecorder(blocker)

    assert recorder.record([{"field": "VWAP"}]) == 0


# ── 报表口径 ──────────────────────────────────────────────────────────────────


def test_summarize_excludes_missing_from_match_rate() -> None:
    rows = [
        {"field": "VWAP", "match": True, "reason": None},
        {"field": "VWAP", "match": False, "reason": "value_diff"},
        {"field": "VWAP", "match": False, "reason": "gateway_missing"},
        {"field": "CHG_PCT_1D", "match": True, "reason": None},
        {"field": None, "match": None, "reason": "gw_error"},
    ]
    report = gs.summarize(rows)

    assert report["samples"] == 4
    assert report["errors"] == 1
    assert report["both_present"] == 3
    assert report["matched"] == 2
    assert abs(report["match_rate"] - 2 / 3) < 1e-12
    assert report["reasons"] == {"value_diff": 1, "gateway_missing": 1}
    assert report["by_field"]["VWAP"]["total"] == 3
    assert report["by_field"]["CHG_PCT_1D"]["match_rate"] == 1.0


def test_summarize_without_samples_reports_none_rate() -> None:
    report = gs.summarize([])
    assert report["samples"] == 0
    assert report["match_rate"] is None


# ── 线程 ──────────────────────────────────────────────────────────────────────


def test_sampler_mirrors_subscriptions_for_new_and_dropped_tickers(tmp_path) -> None:
    subscribed: list[tuple[list[str], list[str]]] = []
    unsubscribed: list[list[str]] = []
    closed: list[bool] = []
    snapshot: dict[str, dict[str, float]] = {"AAA US Equity": {"VWAP": 1.0}}

    async def gateway_subscribe(tickers, fields):
        subscribed.append((tickers, fields))

    async def gateway_unsubscribe(tickers):
        unsubscribed.append(tickers)

    async def gateway_close():
        closed.append(True)

    async def gateway_quote(tickers, fields):
        return {}

    sampler = gs.ShadowSampler(
        lambda: snapshot,
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=("VWAP",),
        gateway_subscribe=gateway_subscribe,
        gateway_unsubscribe=gateway_unsubscribe,
        gateway_close=gateway_close,
    )

    asyncio.run(sampler.sample_once())
    assert subscribed == [(["AAA US Equity"], ["VWAP"])]

    # 重复采同一批标的不重复订阅：网关按引用计数累积，重复订阅会泄漏计数
    asyncio.run(sampler.sample_once())
    assert subscribed == [(["AAA US Equity"], ["VWAP"])]

    # 标的轮换：先补订新标的，再退订离开的
    snapshot.clear()
    snapshot["BBB US Equity"] = {"VWAP": 2.0}
    asyncio.run(sampler.sample_once())
    assert subscribed[-1] == (["BBB US Equity"], ["VWAP"])
    assert unsubscribed == [["AAA US Equity"]]

    asyncio.run(sampler.close())
    assert unsubscribed[-1] == ["BBB US Equity"]
    assert closed == [True]


def test_subscribe_failure_degrades_to_gw_error(tmp_path) -> None:
    async def gateway_subscribe(tickers, fields):
        raise GatewayUnavailable("circuit open")

    async def gateway_quote(tickers, fields):
        raise AssertionError("订阅失败时不应再请求 quote")

    sampler = gs.ShadowSampler(
        lambda: {"AAPL US Equity": {"VWAP": 1.0}},
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=FIELDS,
        gateway_subscribe=gateway_subscribe,
    )
    stats = asyncio.run(sampler.sample_once())

    assert stats["gw_error"].startswith("GatewayUnavailable")
    assert _read_rows(tmp_path)[0]["reason"] == "gw_error"


def test_runner_reuses_one_event_loop_and_closes_sampler() -> None:
    loop_ids: list[int] = []
    closed: list[bool] = []

    class _Sampler:
        async def sample_once(self):
            loop_ids.append(id(asyncio.get_running_loop()))
            if len(loop_ids) >= 3:
                runner._stop.set()
            return {"matched": 1}

        async def close(self):
            closed.append(True)

    runner = gs.ShadowRunner(_Sampler(), interval_seconds=1.0)
    runner._interval = 0.0  # 测试不需要真实等待
    runner.start()
    try:
        for _ in range(200):
            if closed:
                break
            asyncio.run(asyncio.sleep(0.01))
    finally:
        runner.stop()

    assert len(loop_ids) == 3
    assert len(set(loop_ids)) == 1
    assert closed == [True]


def test_runner_stops_promptly_and_records_last_stats(tmp_path) -> None:
    async def gateway_quote(tickers, fields):
        return {ticker: _quote(VWAP=1.0) for ticker in tickers}

    sampler = gs.ShadowSampler(
        lambda: {"AAPL US Equity": {"VWAP": 1.0}},
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=("VWAP",),
    )
    runner = gs.ShadowRunner(sampler, interval_seconds=1.0)
    runner.start()
    try:
        for _ in range(100):
            if runner.last_stats is not None:
                break
            asyncio.run(asyncio.sleep(0.05))
    finally:
        runner.stop()

    assert runner.last_stats is not None
    assert runner.last_stats["matched"] == 1

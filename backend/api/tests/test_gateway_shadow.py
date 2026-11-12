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
from services.gateway_client import (  # noqa: E402
    FieldValue,
    GatewayError,
    GatewayUnavailable,
    SubscribeResult,
    TickerQuote,
)

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


def test_sample_once_records_gateway_recv_ts_when_field_present(tmp_path) -> None:
    """有网关字段值时行里必须带 recv_ts：事后才能判断「网关值旧」还是「值不同」。"""

    async def gateway_quote(tickers, fields):
        return {
            ticker: TickerQuote(
                ticker=ticker,
                fields={
                    "VWAP": FieldValue(
                        value=200.0,
                        src_ts=None,
                        recv_ts="2026-11-11T20:23:56.250+08:00",
                    )
                },
                subscribed=True,
            )
            for ticker in tickers
        }

    sampler = gs.ShadowSampler(
        lambda: {"AAPL US Equity": {"VWAP": 200.0}},
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=("VWAP",),
    )
    asyncio.run(sampler.sample_once())

    row = _read_rows(tmp_path)[0]
    assert row["gateway_recv_ts"] == "2026-11-11T20:23:56.250+08:00"
    # 原有字段保持不变
    assert row["gateway_src_ts"] is None
    assert row["match"] is True


def test_sample_once_records_null_gateway_recv_ts_without_field(tmp_path) -> None:
    """网关没这个字段时 recv_ts 记 null，不伪造时间戳。"""

    async def gateway_quote(tickers, fields):
        return {}  # 逐字段都走 gateway_missing

    sampler = gs.ShadowSampler(
        lambda: {"AAPL US Equity": {"VWAP": 200.0}},
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=("VWAP",),
    )
    asyncio.run(sampler.sample_once())

    row = _read_rows(tmp_path)[0]
    assert row["gateway_recv_ts"] is None
    assert row["reason"] == "gateway_missing"


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
        {"field": "VWAP", "direct": 1.0, "gateway": 1.0, "match": True, "reason": None},
        {"field": "VWAP", "direct": 1.0, "gateway": 2.0, "match": False, "reason": "value_diff"},
        {"field": "VWAP", "direct": 1.0, "gateway": None, "match": False, "reason": "gateway_missing"},
        {"field": "CHG_PCT_1D", "direct": 1.5, "gateway": 1.5, "match": True, "reason": None},
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


def test_summarize_does_not_count_both_missing_as_match() -> None:
    """两侧都无值不能算一致：否则本机不推送的字段会把一致率抬到 100%。"""
    rows = [
        {"field": "CHG_PCT_1D", "direct": None, "gateway": None, "match": True, "reason": None},
        {"field": "CHG_PCT_1D", "direct": None, "gateway": None, "match": True, "reason": None},
        {"field": "VWAP", "direct": 200.0, "gateway": 200.0, "match": True, "reason": None},
        {"field": "VWAP", "direct": 200.0, "gateway": 201.0, "match": False, "reason": "value_diff"},
    ]
    report = gs.summarize(rows)

    assert report["samples"] == 4
    assert report["both_missing"] == 2
    assert report["both_present"] == 2
    assert report["matched"] == 1
    assert report["match_rate"] == 0.5
    assert report["by_field"]["CHG_PCT_1D"]["both_missing"] == 2
    assert report["by_field"]["CHG_PCT_1D"]["match_rate"] is None


def test_summarize_separates_exact_from_within_tolerance() -> None:
    """容差内一致不能冒充精确相等：否则报表看不出「数值其实不一样」。"""
    rows = [
        {"field": "VWAP", "direct": 237.5155, "gateway": 237.5155, "match": True, "reason": None},
        {"field": "VWAP", "direct": 237.5155, "gateway": 237.5153, "match": True, "reason": None},
        {"field": "VWAP", "direct": 34.71, "gateway": 34.7104, "match": False, "reason": "value_diff"},
    ]
    report = gs.summarize(rows)

    assert report["both_present"] == 3
    assert report["matched"] == 2
    assert report["exact"] == 1
    assert report["near_match"] == 1
    assert abs(report["match_rate"] - 2 / 3) < 1e-12
    assert abs(report["exact_rate"] - 1 / 3) < 1e-12
    vwap = report["by_field"]["VWAP"]
    assert vwap["exact"] == 1
    assert vwap["near_match"] == 1
    assert abs(vwap["exact_rate"] - 1 / 3) < 1e-12


def test_summarize_exact_and_near_are_zero_when_no_samples() -> None:
    report = gs.summarize([])
    assert report["exact"] == 0
    assert report["near_match"] == 0
    assert report["exact_rate"] is None


def test_summarize_tolerates_old_rows_without_gateway_recv_ts() -> None:
    """旧 JSONL 没有 gateway_recv_ts，汇总不能因此报错或改变既有口径。"""
    rows = [
        {"ts": "2026-11-10T10:00:00.000", "field": "VWAP", "direct": 1.0, "gateway": 1.0,
         "match": True, "reason": None},
        {"ts": "2026-11-10T10:00:00.000", "field": "VWAP", "direct": 1.0, "gateway": 2.0,
         "match": False, "reason": "value_diff"},
    ]
    report = gs.summarize(rows)

    assert report["samples"] == 2
    assert report["matched"] == 1
    assert report["gateway_lag"]["samples"] == 0
    assert report["gateway_lag"]["max_seconds"] is None
    assert report["gateway_lag"]["stale_gt_5s"] == 0
    assert report["by_field"]["VWAP"]["max_lag_seconds"] is None


def test_summarize_reports_gateway_lag_and_stale_counts() -> None:
    """按 recv_ts 与行 ts 的墙钟差统计网关值陈旧度（+08:00 偏移直接丢弃）。"""
    base = {"field": "VWAP", "direct": 1.0, "gateway": 1.0, "match": True, "reason": None}
    rows = [
        # 早 2 秒
        {**base, "ts": "2026-11-11T20:24:00.000", "gateway_recv_ts": "2026-11-11T20:23:58.000+08:00"},
        # 早 7 秒 → 超 5 秒
        {**base, "ts": "2026-11-11T20:24:00.000", "gateway_recv_ts": "2026-11-11T20:23:53.000+08:00"},
        # 早 40 秒 → 同时超 30 秒
        {**base, "ts": "2026-11-11T20:24:00.000", "gateway_recv_ts": "2026-11-11T20:23:20.000+08:00"},
        # 旧格式行：不参与陈旧度统计
        {**base, "ts": "2026-11-11T20:24:00.000"},
    ]
    report = gs.summarize(rows)

    assert report["samples"] == 4
    lag = report["gateway_lag"]
    assert lag["samples"] == 3
    assert lag["max_seconds"] == 40.0
    assert lag["stale_gt_5s"] == 2
    assert lag["stale_gt_30s"] == 1
    assert report["by_field"]["VWAP"]["max_lag_seconds"] == 40.0


def test_field_unavailable_2004_is_not_recorded_as_gateway_error(tmp_path) -> None:
    """2004「请求字段均无推送值」是契约内结果，应逐字段记账而非整轮 gw_error。"""

    async def gateway_quote(tickers, fields):
        raise GatewayError(2004, "请求字段均无推送值")

    sampler = gs.ShadowSampler(
        lambda: {"AAPL US Equity": {"VWAP": 1.0}},
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=("VWAP",),
    )
    stats = asyncio.run(sampler.sample_once())

    assert stats["gw_error"] is None
    assert stats["compared"] == 1
    assert stats["mismatched"] == 1
    rows = _read_rows(tmp_path)
    assert [row["reason"] for row in rows] == ["gateway_missing"]


def test_2004_on_one_ticker_does_not_discard_other_tickers(tmp_path) -> None:
    """整批 2004 不得吞掉同批里有值的标的（实测 2026-11-10 6 条 gateway_missing 的成因）。"""

    async def gateway_quote(tickers, fields):
        assert len(tickers) == 1, "必须逐标的请求，否则整批 2004 会吞掉有值标的"
        if tickers[0] == "NEW US Equity":
            raise GatewayError(2004, "请求字段均无推送值")
        return {tickers[0]: _quote(VWAP=200.0)}

    sampler = gs.ShadowSampler(
        lambda: {"OLD US Equity": {"VWAP": 200.0}, "NEW US Equity": {"VWAP": 10.0}},
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=("VWAP",),
    )
    stats = asyncio.run(sampler.sample_once())

    assert stats["gw_error"] is None
    rows = {row["ticker"]: row for row in _read_rows(tmp_path)}
    assert rows["OLD US Equity"]["match"] is True
    assert rows["NEW US Equity"]["reason"] == "gateway_missing"


def test_summarize_without_samples_reports_none_rate() -> None:
    report = gs.summarize([])
    assert report["samples"] == 0
    assert report["match_rate"] is None
    assert report["value_diff"]["samples"] == 0
    assert report["value_diff"]["abs_rel_diff_p50"] is None


def test_summarize_stratifies_match_rate_by_lag() -> None:
    """同一时点级别（≤5s）才说明「网关同一 tick 是否算对」，跨时点差异另计。"""
    base = {"field": "VWAP", "direct": 1.0, "gateway": 1.0, "match": True, "reason": None}
    rows = [
        # ≤5s：一致
        {**base, "ts": "2026-11-11T20:24:00.000", "gateway_recv_ts": "2026-11-11T20:23:58.000+08:00"},
        # 5–30s：一致
        {**base, "ts": "2026-11-11T20:24:00.000", "gateway_recv_ts": "2026-11-11T20:23:53.000+08:00"},
        # >30s：值不同
        {**base, "ts": "2026-11-11T20:24:00.000", "direct": 1.0, "gateway": 1.01, "match": False,
         "rel_diff": 0.01, "reason": "value_diff",
         "gateway_recv_ts": "2026-11-11T20:23:20.000+08:00"},
        # 旧格式行：归 unknown
        {**base, "ts": "2026-11-11T20:24:00.000", "direct": 2.0, "gateway": 1.0, "match": False,
         "rel_diff": 1.0, "reason": "value_diff"},
    ]
    report = gs.summarize(rows)

    by_lag = report["by_lag"]
    assert set(by_lag) == {"le_5s", "5s_to_30s", "gt_30s", "unknown"}
    assert by_lag["le_5s"]["both_present"] == 1
    assert by_lag["le_5s"]["match_rate"] == 1.0
    assert by_lag["5s_to_30s"]["matched"] == 1
    assert by_lag["5s_to_30s"]["match_rate"] == 1.0
    assert by_lag["gt_30s"]["both_present"] == 1
    assert by_lag["gt_30s"]["matched"] == 0
    assert by_lag["gt_30s"]["match_rate"] == 0.0
    assert by_lag["unknown"]["both_present"] == 1
    assert by_lag["unknown"]["match_rate"] == 0.0
    # 分层不改变总口径
    assert report["both_present"] == 4
    assert report["matched"] == 2


def test_summarize_reports_value_diff_magnitude() -> None:
    """分歧只报条数看不出量级；给出 |rel_diff| 分位与「小于 1e-2」的占比。"""
    rows = [
        {"ts": "2026-11-11T20:24:00.000", "field": "VWAP", "direct": 1.0, "gateway": 0.99999,
         "match": False, "rel_diff": 1e-5, "reason": "value_diff"},
        {"ts": "2026-11-11T20:24:00.000", "field": "VWAP", "direct": 1.0, "gateway": 0.999,
         "match": False, "rel_diff": 1e-3, "reason": "value_diff"},
        {"ts": "2026-11-11T20:24:00.000", "field": "VWAP", "direct": 1.0, "gateway": 0.5,
         "match": False, "rel_diff": 0.5, "reason": "value_diff"},
        # 缺失类不参与量级统计
        {"ts": "2026-11-11T20:24:00.000", "field": "VWAP", "direct": 1.0, "gateway": None,
         "match": False, "rel_diff": None, "reason": "gateway_missing"},
    ]
    stats = gs.summarize(rows)["value_diff"]

    assert stats["samples"] == 3
    assert stats["lt_1e_2"] == 2
    assert stats["abs_rel_diff_max"] == 0.5
    assert stats["abs_rel_diff_p50"] == 1e-3
    assert stats["abs_rel_diff_p99"] is not None


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


def test_sampler_unsubscribes_before_subscribing_on_rotation(tmp_path) -> None:
    events: list[tuple[str, list[str]]] = []
    snapshot: dict[str, dict[str, float]] = {"AAA US Equity": {"VWAP": 1.0}}

    async def gateway_subscribe(tickers, fields):
        events.append(("subscribe", list(tickers)))
        return SubscribeResult(accepted=tuple(tickers), rejected=0, total=len(tickers))

    async def gateway_unsubscribe(tickers):
        events.append(("unsubscribe", list(tickers)))

    async def gateway_quote(tickers, fields):
        return {}

    sampler = gs.ShadowSampler(
        lambda: snapshot,
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=("VWAP",),
        gateway_subscribe=gateway_subscribe,
        gateway_unsubscribe=gateway_unsubscribe,
    )
    asyncio.run(sampler.sample_once())

    snapshot.clear()
    snapshot["BBB US Equity"] = {"VWAP": 2.0}
    asyncio.run(sampler.sample_once())

    # 先退订释放配额，再订阅新标的；反序会在配额打满时把轮换卡死
    assert events == [
        ("subscribe", ["AAA US Equity"]),
        ("unsubscribe", ["AAA US Equity"]),
        ("subscribe", ["BBB US Equity"]),
    ]


def test_sampler_tracks_only_accepted_subscriptions(tmp_path) -> None:
    subscribed: list[list[str]] = []
    snapshot = {"AAA US Equity": {"VWAP": 1.0}, "BBB US Equity": {"VWAP": 2.0}}

    async def gateway_subscribe(tickers, fields):
        subscribed.append(list(tickers))
        # 配额只放行 AAA；BBB 被拒
        return SubscribeResult(accepted=("AAA US Equity",), rejected=1, total=2)

    async def gateway_quote(tickers, fields):
        return {}

    sampler = gs.ShadowSampler(
        lambda: snapshot,
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=("VWAP",),
        gateway_subscribe=gateway_subscribe,
    )
    asyncio.run(sampler.sample_once())
    asyncio.run(sampler.sample_once())

    # 被拒的 BBB 不能被记成已订阅，否则永远不再重试
    assert subscribed == [["AAA US Equity", "BBB US Equity"], ["BBB US Equity"]]


def test_sampler_resubscribes_when_gateway_reports_not_subscribed(tmp_path) -> None:
    subscribed: list[list[str]] = []
    calls = 0

    async def gateway_subscribe(tickers, fields):
        subscribed.append(list(tickers))

    async def gateway_quote(tickers, fields):
        nonlocal calls
        calls += 1
        return {
            ticker: TickerQuote(ticker=ticker, subscribed=(calls == 1))
            for ticker in tickers
        }

    sampler = gs.ShadowSampler(
        lambda: {"AAPL US Equity": {"VWAP": 1.0}},
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=("VWAP",),
        gateway_subscribe=gateway_subscribe,
    )
    asyncio.run(sampler.sample_once())
    asyncio.run(sampler.sample_once())  # 网关报 subscribed=False → 本地缓存失效
    asyncio.run(sampler.sample_once())  # 下一轮重新订阅

    assert subscribed == [["AAPL US Equity"], ["AAPL US Equity"]]


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


# ── S3：取数时点对齐 ──────────────────────────────────────────────────────────


def test_sample_once_stamps_direct_ts_before_fetch_and_gateway_ts_after(tmp_path) -> None:
    """S3：`direct_ts` 在取直连快照前打，`ts` 在网关快照取完后打。

    旧实现只在全部 `/quote` 返回后打 `ts`，直连值却更早取，于是每行都自带
    一个请求周期的时点错配；现在两段时间戳分开落盘，差值 = 本轮取数跨度。
    """
    moments = iter(
        [
            datetime(2026, 11, 12, 11, 0, 0, 100000),  # direct_ts
            datetime(2026, 11, 12, 11, 0, 0, 900000),  # gateway_ts
        ]
    )

    async def gateway_quote(tickers, fields):
        # 取网关快照期间时钟不应被推进（第二次取时钟发生在返回之后）
        return {ticker: _quote(VWAP=200.0) for ticker in tickers}

    sampler = gs.ShadowSampler(
        lambda: {"AAPL US Equity": {"VWAP": 200.0}},
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=("VWAP",),
        clock=lambda: next(moments),
    )
    asyncio.run(sampler.sample_once())

    row = _read_rows(tmp_path)[0]
    assert row["direct_ts"] == "2026-11-12T11:00:00.100"
    assert row["ts"] == "2026-11-12T11:00:00.900"


def test_summarize_reports_sampling_span_separately_from_gateway_lag() -> None:
    """S3：取数跨度单列统计，`gateway_lag` 不再被采样耗时单方面抬高。"""
    base = {"field": "VWAP", "direct": 1.0, "gateway": 1.0, "match": True, "reason": None}
    rows = [
        {
            **base,
            "direct_ts": "2026-11-12T11:00:00.000",
            "ts": "2026-11-12T11:00:00.800",
            "gateway_recv_ts": "2026-11-12T10:59:58.000+08:00",
        },
        {
            **base,
            "direct_ts": "2026-11-12T11:00:30.000",
            "ts": "2026-11-12T11:00:31.200",
            "gateway_recv_ts": "2026-11-12T11:00:29.000+08:00",
        },
        # 旧格式行：无 direct_ts，不进跨度统计
        {**base, "ts": "2026-11-12T11:01:00.000", "gateway_recv_ts": "2026-11-12T11:00:59.000+08:00"},
    ]
    report = gs.summarize(rows)

    span = report["sampling_span"]
    assert span["samples"] == 2
    assert span["p50_seconds"] == 1.0
    assert span["max_seconds"] == 1.2
    # gateway_lag 仍按 ts - recv_ts 计（含采样耗时），口径未变：2.8s > 2.2s > 1.0s
    assert report["gateway_lag"]["samples"] == 3
    assert report["gateway_lag"]["max_seconds"] == 2.8


def test_gw_error_rows_carry_direct_ts(tmp_path) -> None:
    """网关失败行也带 `direct_ts`，报表按行统计跨度时不会因缺列报错。"""

    async def gateway_quote(tickers, fields):
        raise GatewayUnavailable("circuit open")

    sampler = gs.ShadowSampler(
        lambda: {"AAPL US Equity": {"VWAP": 200.0}},
        gateway_quote,
        gs.ShadowRecorder(tmp_path),
        fields=("VWAP",),
    )
    asyncio.run(sampler.sample_once())

    row = _read_rows(tmp_path)[0]
    assert row["reason"] == "gw_error"
    assert isinstance(row["direct_ts"], str)

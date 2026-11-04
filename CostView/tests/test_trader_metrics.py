"""trader_metrics 纯函数单测（PR-1）：符号方向 / 分桶 / 徽章 / KPI / 探针。"""

from __future__ import annotations

import pytest

from CostView.src import trader_metrics as tm


class TestAdverseBps:
    """F3：成本符号统一 —— 上游负 = 劣，adverse = -value（正 = 差）。"""

    def test_direction(self) -> None:
        assert tm.adverse_bps(-4.2) == 4.2
        assert tm.adverse_bps(3.0) == -3.0
        assert tm.adverse_bps(0.0) == 0.0

    def test_none_passthrough(self) -> None:
        assert tm.adverse_bps(None) is None


class TestCompletionBucket:
    def test_boundaries(self) -> None:
        assert tm.completion_bucket(None) is None
        assert tm.completion_bucket(0.0) == "lt50"
        assert tm.completion_bucket(0.499) == "lt50"
        assert tm.completion_bucket(0.5) == "50to80"
        assert tm.completion_bucket(0.8) == "80to100"
        assert tm.completion_bucket(0.999) == "80to100"
        assert tm.completion_bucket(1.0) == "eq100"
        assert tm.completion_bucket(1.2) == "gt100"


class TestAmountQtyMismatch:
    """§4.12：|Amount − ΣRouteShares| / max(Amount,1) > 0.5% 视为口径矛盾。"""

    def test_tolerance(self) -> None:
        assert tm.amount_qty_mismatch(1000.0, 1004.0) is False
        assert tm.amount_qty_mismatch(1000.0, 1006.0) is True
        assert tm.amount_qty_mismatch(0.5, 1.0) is True

    def test_missing_is_not_mismatch(self) -> None:
        assert tm.amount_qty_mismatch(None, 100.0) is False
        assert tm.amount_qty_mismatch(100.0, None) is False


def _row(**overrides) -> dict:
    base = {
        "fill": 900.0, "route_shares": 1000.0, "fill_count": 5,
        "arrival_cost_bps": -4.0, "wagner_is_bps": -9.0, "opportunity_cost": -1.0,
        "max_par_rate": 0.1, "flag_overfill": 0, "flag_amount_mismatch": 0,
        "flag_cost_missing": 0, "flag_single_fill": 0,
    }
    base.update(overrides)
    return base


class TestQualityFlags:
    def test_clean(self) -> None:
        level, flags = tm.quality_flags(_row())
        assert level == "clean"
        assert flags == []

    def test_overfill_is_bad(self) -> None:
        level, flags = tm.quality_flags(_row(flag_overfill=1))
        assert level == "bad"
        assert "overfill" in flags

    def test_par_suspect_tiers(self) -> None:
        level, flags = tm.quality_flags(_row(max_par_rate=1.5))
        assert level == "warn"
        assert "par_suspect" in flags
        level, flags = tm.quality_flags(_row(max_par_rate=15.0))
        assert level == "bad"
        assert "par_suspect" in flags

    def test_cost_missing_and_single_fill(self) -> None:
        level, flags = tm.quality_flags(_row(flag_cost_missing=1, flag_single_fill=1))
        assert level == "warn"
        assert "cost_missing" in flags
        assert "single_fill" in flags
        level, flags = tm.quality_flags(_row(flag_single_fill=1))
        assert level == "info"


class TestComputeKpi:
    def test_ratios_and_denominators(self) -> None:
        rows = [
            _row(completion=0.5, arrival_cost_bps=-2.0, opportunity_cost=-100.0,
                 route_shares=1000.0, p_decision=10.0),
            _row(completion=1.0, arrival_cost_bps=-5.0, opportunity_cost=0.0,
                 route_shares=1000.0, p_decision=10.0),
        ]
        kpi = tm.compute_kpi(rows)

        assert kpi["orders"]["value"] == 2.0
        assert kpi["low_completion_ratio"]["value"] == 0.5
        assert kpi["low_completion_ratio"]["denominator"] == 2
        # opp_bps = -100/(1000×10)×1e4 = -100 → adverse 100 > adverse(arrival=-2)→2
        assert kpi["opp_dominant_ratio"]["value"] == 0.5

    def test_empty_gives_none_not_zero(self) -> None:
        kpi = tm.compute_kpi([])
        assert kpi["orders"]["value"] == 0.0
        assert kpi["low_completion_ratio"]["value"] is None
        assert kpi["opp_dominant_ratio"]["value"] is None
        assert kpi["passive_ratio"]["value"] is None
        assert kpi["release_delay_p90"]["value"] is None

    def test_anomaly_orders_union(self) -> None:
        rows = [
            _row(flag_overfill=1),                                  # 仅 overfill
            _row(flag_cost_missing=1),                              # 仅 cost_missing
            _row(flag_overfill=1, flag_cost_missing=1),             # 两者都中
            _row(),                                                 # 干净
        ]
        kpi = tm.compute_kpi(rows)
        # 并集 = 3 单（both 只计一次）；critical/warning 为各自命中数
        assert kpi["anomaly_orders"]["value"] == 3.0
        assert kpi["anomaly_orders"]["critical"] == 2
        assert kpi["anomaly_orders"]["warning"] == 2


class TestComputeProbes:
    def test_four_checks_always_returned(self) -> None:
        probes = tm.compute_probes([_row(), _row(flag_overfill=1, flag_amount_mismatch=1)])
        assert [p["id"] for p in probes] == [
            "quantity", "participation", "cost_missing", "fill_quality",
        ]
        assert probes[0]["triggered"] == 1
        assert probes[3]["checked"] is False
        assert probes[3]["triggered"] is None

    def test_participation_counts_par_suspect(self) -> None:
        probes = tm.compute_probes([_row(max_par_rate=1.2), _row(max_par_rate=0.2)])
        assert probes[1]["triggered"] == 1

    def test_fill_quality_context_applied(self) -> None:
        probes = tm.compute_probes([], {"checked": True, "triggered": 2, "note": None})
        assert probes[3]["checked"] is True
        assert probes[3]["triggered"] == 2


# ── PR-2：FIX 851 映射 / 主被动拆分 / 成本分解 ──────────────────────────────


class TestLiquidityMapping:
    """§4.6 验收：FIX 851 全部取值映射单测（1/2/3/4/0/5/6/Z/空 + 扩展）。"""

    def test_strict_mapping_all_values(self) -> None:
        assert tm.liquidity_class("1") == "passive"
        assert tm.liquidity_class("2") == "aggressive"
        assert tm.liquidity_class("4") == "auction"
        assert tm.liquidity_class("Maker") == "passive"
        assert tm.liquidity_class("Taker") == "aggressive"
        assert tm.liquidity_class("Auction") == "auction"
        for raw in ("3", "0", "5", "6", "Z", "P", "A", "Routed", "", None):
            assert tm.liquidity_class(raw) == "unknown", raw


class TestLiquiditySplit:
    def test_shares_sum_invariant_and_costs(self) -> None:
        fills = [
            {"shares": 100.0, "price": 10.0, "liquidity_raw": "1"},   # passive
            {"shares": 200.0, "price": 11.0, "liquidity_raw": "2"},   # aggressive
            {"shares": 50.0, "price": 12.0, "liquidity_raw": "4"},    # auction
            {"shares": 50.0, "price": 9.0, "liquidity_raw": "Z"},     # unknown
        ]
        split = tm.liquidity_split(fills, p_arrival=10.0, side="BUY")

        assert split["total_shares"] == 400.0
        assert split["passive_share_strict"] == 0.25
        assert split["aggressive_share_strict"] == 0.5
        assert split["auction_share"] == 0.125
        assert split["unknown_share"] == 0.125
        # BUY：成交价高于 p_arrival 为不利 → 负 bps
        assert split["passive_cost_bps"] == 0.0
        assert split["aggressive_cost_bps"] == pytest.approx(-1000.0)
        assert split["recognized_share"] == 0.875

    def test_missing_p_arrival_gives_none_costs(self) -> None:
        split = tm.liquidity_split([{"shares": 1.0, "price": 1.0, "liquidity_raw": "1"}], None, "BUY")
        assert split["passive_cost_bps"] is None


class TestCostDecomposition:
    def test_residual_zero_when_components_close(self) -> None:
        cost = tm.cost_decomposition(
            delay_cost=-100.0, trading_cost=-200.0, opportunity_cost=-50.0,
            wagner_is_bps=-35.0, route_shares=1000.0, p_decision=100.0,
            arrival_cost_bps=-4.0, completion=0.9,
        )
        assert cost["denominator"] == 100_000.0
        assert cost["delay_bps"] == pytest.approx(-10.0)
        assert cost["trading_bps"] == pytest.approx(-20.0)
        assert cost["opportunity_bps"] == pytest.approx(-5.0)
        assert cost["residual_bps"] == pytest.approx(0.0)
        assert cost["residual_flag"] is None
        assert cost["opportunity_dominant"] is True
        assert cost["opportunity_highlight"] is True

    def test_residual_flagged_at_tolerance(self) -> None:
        cost = tm.cost_decomposition(
            delay_cost=-100.0, trading_cost=-200.0, opportunity_cost=-50.0,
            wagner_is_bps=-30.0, route_shares=1000.0, p_decision=100.0,
        )
        assert cost["residual_bps"] == pytest.approx(5.0)
        assert cost["residual_flag"] == "对账异常"

    def test_missing_p_decision_no_nan(self) -> None:
        cost = tm.cost_decomposition(
            delay_cost=-100.0, trading_cost=-200.0, opportunity_cost=-50.0,
            wagner_is_bps=-35.0, route_shares=1000.0, p_decision=None,
        )
        assert cost["denominator"] is None
        # 货币成本原值随 payload 下发（UI 在无 p_decision 时只能展示这三项）
        assert cost["opportunity_cost"] == -50.0
        assert cost["delay_bps"] is None
        assert cost["residual_bps"] is None
        assert cost["delay_bps"] is None
        assert cost["note"] == "IS 分解不可用（无 BDIB/决策价）"


class TestLatencyBlock:
    def test_scheduled_and_clamp(self) -> None:
        block = tm.latency_block(
            order_to_route_sec=10.0, route_to_first_fill_sec=20.0,
            first_continuous_fill_sec=-0.5, algo="close", first_fill_is_auction=False,
        )
        assert block["scheduled"] is True
        assert block["first_continuous_fill_sec"] == 0.0      # <1s 负值钳 0
        assert block["latency_anomaly"] is False
        assert block["order_to_first_fill_sec"] == 30.0

    def test_negative_over_1s_flags_anomaly(self) -> None:
        block = tm.latency_block(
            order_to_route_sec=None, route_to_first_fill_sec=None,
            first_continuous_fill_sec=-5.0, algo="vwap", first_fill_is_auction=False,
        )
        assert block["latency_anomaly"] is True
        assert block["scheduled"] is False


class TestPercentileMadZ:
    def test_percentile_rank(self) -> None:
        assert tm.percentile_rank(5.0, [1.0, 3.0, 5.0, 7.0]) == 0.625
        assert tm.percentile_rank(None, [1.0]) is None
        assert tm.percentile_rank(1.0, []) is None

    def test_mad_z_and_zero_mad_fallback(self) -> None:
        # 中位 2、MAD 1 → z = (6 − 2) / 1
        assert tm.mad_z(6.0, [1.0, 2.0, 3.0]) == pytest.approx(4.0)
        assert tm.mad_z(2.0, [2.0, 2.0, 2.0]) is None


# ── PR-2：时间线分桶 / 完成轨迹 / 填充分布 ─────────────────────────────────


def _fill(ts: float, shares: float, price: float = 10.0, auction: int = 0) -> dict:
    return {"ts_sec": ts, "shares": shares, "price": price, "is_closing_auction": auction}


class TestBucketFills:
    def test_sums_cum_completion_and_participation(self) -> None:
        fills = [_fill(33660, 300.0), _fill(33960, 300.0), _fill(34260, 400.0)]
        bars = [
            {"ts_sec": 33670, "volume": 3000.0},
            {"ts_sec": 33970, "volume": 3000.0},
            {"ts_sec": 34270, "volume": 4000.0},
        ]
        timeline = tm.bucket_fills(fills, 5, 1000.0, bars)

        buckets = timeline["buckets"]
        assert len(buckets) == 3
        assert sum(b["fill"] for b in buckets) == 1000.0          # 桶和 = 总成交
        assert buckets[-1]["cum_completion"] == 1.0               # 末桶 = completion
        assert buckets[0]["participation"] == pytest.approx(0.1)
        assert buckets[0]["accel"] is None
        assert all(b["participation_status"] == "ok" for b in buckets)

    def test_auction_bucket_unavailable(self) -> None:
        fills = [_fill(57300, 300.0), _fill(57600, 700.0, auction=1)]
        bars = [{"ts_sec": 57310, "volume": 1000.0}]
        buckets = tm.bucket_fills(fills, 5, 1000.0, bars)["buckets"]

        assert len(buckets) == 2
        assert buckets[1]["participation"] is None
        assert buckets[1]["participation_status"] == "unavailable"

    def test_auto_widen_disclosed(self) -> None:
        fills = [_fill(0.0, 100.0), _fill(30 * 3600, 100.0)]
        timeline = tm.bucket_fills(fills, 5, 200.0, [])

        assert timeline["auto_widened"] is True
        assert timeline["bucket_min"] > 5

    def test_empty_fills(self) -> None:
        assert tm.bucket_fills([], 5, None, [])["buckets"] == []


class TestFillSpanStats:
    def test_single_fill_returns_none_not_zero(self) -> None:
        fills = [_fill(100.0, 300.0)]
        buckets = tm.bucket_fills(fills, 5, 300.0, [])["buckets"]
        stats = tm.fill_span_stats(fills, buckets, 300.0)

        assert stats["fill_span_sec"] is None
        assert stats["speed_shares_per_min"] is None
        assert stats["speed_cv"] is None

    def test_multi_fill_speed_and_zero_buckets(self) -> None:
        fills = [_fill(0.0, 300.0), _fill(600.0, 300.0), _fill(1200.0, 400.0)]
        buckets = tm.bucket_fills(fills, 5, 1000.0, [])["buckets"]
        stats = tm.fill_span_stats(fills, buckets, 1000.0)

        assert stats["fill_span_sec"] == 1200.0
        assert stats["speed_shares_per_min"] == pytest.approx(50.0)
        assert stats["speed_cv_basis"] == "non_zero_buckets"


class TestFillDistribution:
    def test_stats_and_top3(self) -> None:
        fills = [_fill(0.0, 100.0), _fill(300.0, 200.0), _fill(600.0, 300.0)]
        stats = tm.fill_distribution(fills, 1000.0)

        assert stats["median"] == 200.0
        assert stats["p90"] == pytest.approx(280.0)
        assert stats["top3_share"] == 1.0
        assert stats["max_fill_ratio"] == pytest.approx(0.3)
        assert stats["fills_per_min"] == pytest.approx(0.3)

    def test_single_fill_skips_cv_and_top3(self) -> None:
        stats = tm.fill_distribution([_fill(0.0, 100.0)], 1000.0)
        assert stats["cv"] is None
        assert stats["top3_share"] is None

    def test_top3_na_below_three_fills(self) -> None:
        stats = tm.fill_distribution([_fill(0.0, 100.0), _fill(60.0, 100.0)], 1000.0)
        assert stats["top3_share"] is None

# ── 210 §4.11：订单级异常摘要 ─────────────────────────────────────────────


def _order_row(order_id: str, **overrides):
    """订单聚合行（SQL 形态：OrderId / completion / flag_*）。"""
    row = {
        "OrderId": order_id, "order_as_of_date": "20261022",
        "equ_ticker": "ABCD US Equity", "side": "BUY",
        "completion": 1.0, "pnl_vwap": 0.0, "max_par_rate": 0.1,
        "flag_overfill": 0, "flag_cost_missing": 0,
    }
    row.update(overrides)
    return row


def _hit(key: str, severity: str = "warning"):
    return {"key": key, "label": key.upper(), "value": 1.0, "unit": "percent",
            "severity": severity}


class TestAnomalySummary:
    """订单级异常摘要：并集口径 / 分档 / 按规则计数 / Top N 排序。"""

    def test_counts_by_rule_and_severity(self) -> None:
        rows = [_order_row("A"), _order_row("B"), _order_row("C")]
        hits = {
            "A": [_hit("fill_pct", "critical"), _hit("pnl_vwap_bps")],
            "B": [_hit("pnl_vwap_bps")],
            "C": [],
        }
        summary = tm.compute_anomaly_summary(
            rows, lambda row: hits[str(row.get("OrderId"))],
        )

        assert summary["orders_total"] == 2
        assert summary["rule_orders"] == 2
        assert summary["quality_orders"] == 0
        assert summary["critical"] == 1
        assert summary["warning"] == 1
        # 按命中数降序：pnl_vwap_bps 2 条 > fill_pct 1 条
        assert [item["key"] for item in summary["by_rule"]] == ["pnl_vwap_bps", "fill_pct"]
        assert summary["by_rule"][1]["critical"] == 1
        assert summary["scope"] == "order-level"

    def test_quality_flags_join_union(self) -> None:
        """overfill / cost_missing 即使不命中规则也计入并集；overfill 记 critical。"""
        rows = [
            _order_row("A", flag_overfill=1),
            _order_row("B", flag_cost_missing=1),
            _order_row("C", flag_overfill=1, flag_cost_missing=1),
        ]
        summary = tm.compute_anomaly_summary(rows, lambda row: [])

        assert summary["orders_total"] == 3          # 并集去重，不是 4
        assert summary["quality_orders"] == 3
        assert summary["rule_orders"] == 0
        assert summary["critical"] == 2              # A、C 含 overfill
        assert summary["warning"] == 1               # B 仅 cost_missing
        assert summary["by_rule"] == []

    def test_top_orders_sorted_by_severity_then_hits(self) -> None:
        rows = [_order_row(f"O{index}") for index in range(8)]
        hits = {f"O{index}": [_hit("pnl_vwap_bps")] for index in range(8)}
        hits["O5"] = [_hit("pnl_vwap_bps", "critical")]
        hits["O6"] = [_hit("fill_pct"), _hit("pnl_vwap_bps")]
        summary = tm.compute_anomaly_summary(
            rows, lambda row: hits[str(row.get("OrderId"))],
        )

        top = summary["top_orders"]
        assert len(top) == tm.ANOMALY_TOP_N
        assert top[0]["order_id"] == "O5"            # critical 优先
        assert top[1]["order_id"] == "O6"            # 同为 warning，命中项多的在前
        assert top[0]["reasons"][0]["severity"] == "critical"

    def test_kpi_uses_summary_union(self) -> None:
        rows = [_order_row("A", flag_overfill=1), _order_row("B")]
        summary = tm.compute_anomaly_summary(rows, lambda row: [])
        kpi = tm.compute_kpi(rows, summary)

        assert kpi["anomaly_orders"]["value"] == 1
        assert kpi["anomaly_orders"]["critical"] == 1
        assert kpi["anomaly_orders"]["warning"] == 0
        assert "订单级口径" in (kpi["anomaly_orders"]["note"] or "")

    def test_kpi_falls_back_without_summary(self) -> None:
        """未注入摘要时退回质量旗标口径（向后兼容，不静默变 0）。"""
        rows = [_order_row("A", flag_overfill=1), _order_row("B", flag_cost_missing=1)]
        kpi = tm.compute_kpi(rows)

        assert kpi["anomaly_orders"]["value"] == 2
        assert "未接入阈值规则" in (kpi["anomaly_orders"]["note"] or "")


# ── 210 §4.7：peer 分位与指纹 ─────────────────────────────────────────────


class TestPeerMetrics:
    """8 维指纹：分位公式 / 不可得维度 / 偏离计数 / 延迟 p90。"""

    def test_percentile_and_median(self) -> None:
        current = {"completion": 0.9}
        peers = [{"completion": value} for value in (0.8, 0.85, 0.95, 1.0)]
        metrics = tm.compute_peer_metrics(current, peers)
        completion = next(item for item in metrics if item["key"] == "completion")

        # 0.9 落在 0.85 与 0.95 之间：below=2, equal=0 → 2/4
        assert completion["percentile"] == pytest.approx(0.5)
        assert completion["median"] == pytest.approx(0.9)
        assert completion["n"] == 4
        assert completion["available"] is True
        assert completion["direction"] == "higher_better"

    def test_unavailable_dimensions_are_explicit(self) -> None:
        metrics = tm.compute_peer_metrics({"completion": 1.0}, [{"completion": 1.0}])
        by_key = {item["key"]: item for item in metrics}

        assert len(metrics) == 8
        for key in ("fill_cv", "passive_ratio"):
            assert by_key[key]["available"] is False
            assert by_key[key]["percentile"] is None
            assert by_key[key]["note"]  # 必须写明为什么不可得
        # 有 loader 但当前值缺失 → 也不伪造分位
        assert by_key["arrival_cost_bps"]["available"] is False
        assert by_key["arrival_cost_bps"]["note"] is None

    def test_null_values_not_counted_as_zero(self) -> None:
        current = {"opportunity_cost": None, "route_shares": 1000, "p_decision": 100}
        peers = [{"opportunity_cost": None, "route_shares": 1000, "p_decision": 100}]
        metrics = tm.compute_peer_metrics(current, peers)
        opp = next(item for item in metrics if item["key"] == "opportunity_cost_bps")

        assert opp["value"] is None
        assert opp["n"] == 0
        assert opp["available"] is False

    def test_deviation_count(self) -> None:
        metrics = [
            {"available": True, "percentile": 0.95},   # |0.45| > 0.4 → 偏离
            {"available": True, "percentile": 0.5},
            {"available": True, "percentile": 0.05},   # |0.45| > 0.4 → 偏离
            {"available": True, "percentile": 0.9},    # 恰为 0.4 边界，不算偏离
            {"available": False, "percentile": None},
        ]
        assert tm.fingerprint_deviation(metrics) == 2

    def test_peer_latency_p90_ignores_negative_and_missing(self) -> None:
        rows = [
            {"route_first": "09:30:00", "first_continuous": "09:30:30"},   # 30s
            {"route_first": "09:30:00", "first_continuous": "09:31:00"},   # 60s
            {"route_first": "09:30:10", "first_continuous": "09:30:00"},   # 负值丢弃
            {"route_first": None, "first_continuous": "09:31:00"},         # 缺时刻丢弃
        ]
        assert tm.peer_latency_p90(rows) == pytest.approx(57.0)  # p90 线性插值
        assert tm.peer_latency_p90([]) is None


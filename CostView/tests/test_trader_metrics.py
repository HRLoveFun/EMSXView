"""trader_metrics 纯函数单测（PR-1）：符号方向 / 分桶 / 徽章 / KPI / 探针。"""

from __future__ import annotations

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

"""DL-26/221 信号与规则月度回检 —— 口径与统计性质测试。

锁死：
1. 已知 lift 可被回收（合成数据）；
2. 规模混杂下，分层差归零、整体差仍偏大（控制规模确实生效）；
3. 成本缺失不补 0，覆盖率披露；
4. 自指规则（成本派生）标记，且不进入 any_actionable_signal；
5. 规则指纹稳定、改阈值后变化；
6. 订单级规则在路由层明确标 available=false。
"""

from __future__ import annotations

import pytest

from CostView.src.evaluation.signal_lift import (
    ANY_ACTIONABLE_SIGNAL,
    monthly_signal_lift,
    prepare_routes,
)


def _row(
    *,
    order: str = "O1",
    exchange: str = "US",
    cost: float | None = 10.0,
    shares: float = 1000.0,
    price: float = 100.0,
    day: str = "20261103",
    par_rate: float = 0.01,
    fill: float | None = None,
    **overrides,
) -> dict:
    """最小可用路由行（USD、汇率 1.0、默认满成交以避开 fill_pct 告警）。"""
    row = {
        "OrderId": order,
        "RouteId": "1",
        "Exchange": exchange,
        "Currency": "USD",
        "order_as_of_date": day,
        "RouteShares": shares,
        "Amount": shares,
        "p_avg": price,
        "fx_rate": 1.0,
        "fill": shares if fill is None else fill,
        "arrival_cost_bps": cost,
        "pnl_vwap": cost if cost is not None else 0.0,
        "par_rate": par_rate,
        "par_rate_continuous": par_rate,
        "pnl_vwap_continuous": 0.0,
        "RPM": 0.0,
    }
    row.update(overrides)
    return row


def _cost(cost: float, index: int) -> float:
    """轻微交替扰动，保证当日标准差 > 0（否则不做 z 标准化）。"""
    return cost + (0.1 if index % 2 == 0 else -0.1)


def _lift(report: dict, key: str) -> dict:
    return report["signals"][key]


class TestKnownLift:
    def test_recovers_known_five_bps_lift(self):
        rows = []
        for index in range(60):
            for shares in (1000.0, 10000.0):
                hit = index % 2 == 0
                rows.append(_row(
                    order=f"O{index}-{int(shares)}",
                    shares=shares,
                    cost=_cost(15.0 if hit else 10.0, index),
                    par_rate=0.10 if hit else 0.01,
                ))
        report = monthly_signal_lift(rows, size_buckets=2, bootstrap=200)
        item = _lift(report, "volume_pct_adv20")
        assert item["n_hit"] == 60 and item["n_miss"] == 60
        assert item["raw_stratified_delta_bps"] == pytest.approx(5.0, abs=0.3)
        assert item["std_delta"]["stratified"] is True
        assert item["std_delta"]["difference"] > 0
        ci = item["std_delta_ci95"]
        assert ci is not None and ci[0] > 0 and ci[1] > 0
        assert item["significant_at_95"] is True

    def test_coverage_fields_present(self):
        report = monthly_signal_lift(
            [_row(order=f"O{i}", cost=_cost(10.0, i), par_rate=0.01) for i in range(40)],
            size_buckets=2,
            bootstrap=50,
        )
        assert report["version"] == "signal-lift-v1"
        assert report["standardization"]["method"] == "per-day z-score"
        assert report["size"]["buckets"] == 2
        assert report["sample"]["usable"] == 40
        assert len(report["rules"]["fingerprint"]) == 16


class TestSizeConfounding:
    def test_stratification_removes_size_confound(self):
        rows = []
        # 小单：成本 10，命中率 10%；大单：成本 30，命中率 90%。
        # 整体看命中组成本高，但层内命中/未命中完全相同 → 分层差应为 0。
        for index in range(50):
            rows.append(_row(
                order=f"S{index}", shares=1000.0, cost=_cost(10.0, index),
                par_rate=0.10 if index < 5 else 0.01,
            ))
            rows.append(_row(
                order=f"L{index}", shares=10000.0, cost=_cost(30.0, index),
                par_rate=0.10 if index < 45 else 0.01,
            ))
        report = monthly_signal_lift(rows, size_buckets=2, bootstrap=50)
        item = _lift(report, "volume_pct_adv20")
        assert abs(item["raw_stratified_delta_bps"]) < 0.5
        assert abs(item["raw_cost_bps"]["pooled_delta"]) > 10
        assert item["std_delta"]["stratified"] is True
        assert abs(item["std_delta"]["difference"]) < 0.3

    def test_no_common_strata_discloses_fallback(self):
        # 命中全部在大单层、未命中全部在小单层 → 无共同层，退化并披露。
        rows = [
            _row(order=f"L{i}", shares=10000.0, cost=30.0, par_rate=0.10)
            for i in range(10)
        ] + [
            _row(order=f"S{i}", shares=1000.0, cost=10.0, par_rate=0.01)
            for i in range(10)
        ]
        report = monthly_signal_lift(rows, size_buckets=2, bootstrap=20)
        item = _lift(report, "volume_pct_adv20")
        assert item["std_delta"]["stratified"] is False
        assert item["std_delta"]["coverage"] == 0.0


class TestMissingData:
    def test_missing_cost_excluded_not_zero_filled(self):
        rows = [_row(order=f"O{i}", cost=_cost(10.0, i)) for i in range(30)]
        rows += [_row(order=f"M{i}", cost=None) for i in range(10)]
        report = monthly_signal_lift(rows, bootstrap=20)
        assert report["sample"]["routes"] == 40
        assert report["sample"]["cost_missing"] == 10
        assert report["sample"]["usable"] == 30
        assert _lift(report, "fill_pct")["n_hit"] + _lift(report, "fill_pct")["n_miss"] == 30

    def test_missing_size_excluded(self):
        rows = [_row(order=f"O{i}") for i in range(10)]
        rows += [
            _row(order=f"X{i}", price=0.0, fx_rate=None)
            for i in range(5)
        ]
        report = monthly_signal_lift(rows, bootstrap=10)
        assert report["sample"]["size_missing"] == 5
        assert report["sample"]["usable"] == 10

    def test_rule_availability(self):
        rows = [_row(order=f"O{i}") for i in range(20)]
        report = monthly_signal_lift(rows, bootstrap=10)
        assert _lift(report, "volume_pct_adv20")["available"] is True
        # 订单级规则需要订单组聚合，路由层不伪造
        assert _lift(report, "order_par_single_gt100")["available"] is False
        assert _lift(report, "route_par_extreme")["available"] is False


class TestSelfReferentialRules:
    def test_cost_derived_flagged_and_excluded_from_summary(self):
        rows = [
            _row(order=f"O{i}", cost=10.0, pnl_vwap=50.0, par_rate=0.001)
            for i in range(20)
        ]
        report = monthly_signal_lift(rows, bootstrap=20)
        assert _lift(report, "pnl_vwap_bps")["cost_derived"] is True
        assert _lift(report, "intraday_volatility")["cost_derived"] is True
        assert _lift(report, "fill_pct")["cost_derived"] is False
        assert _lift(report, ANY_ACTIONABLE_SIGNAL)["n_hit"] == 0
        assert "pnl_vwap_bps" in _lift(report, ANY_ACTIONABLE_SIGNAL)["excludes"]


class TestRuleFingerprint:
    def test_fingerprint_stable_and_versioned(self):
        rows = [_row(order=f"O{i}") for i in range(10)]
        first = monthly_signal_lift(rows, bootstrap=10)
        second = monthly_signal_lift(rows, bootstrap=10)
        assert first["rules"]["fingerprint"] == second["rules"]["fingerprint"]

        changed = monthly_signal_lift(
            rows,
            rules_payload={"fill_pct": {"warning": 95}},
            bootstrap=10,
        )
        assert changed["rules"]["fingerprint"] != first["rules"]["fingerprint"]
        assert changed["rules"]["resolved"]["fill_pct"]["warning"] == 95.0


class TestPrepareRoutes:
    def test_does_not_mutate_input_and_injects_completion(self):
        raw = _row(order="O1", fill=500.0, shares=1000.0)
        before = dict(raw)
        prepared, meta = prepare_routes([raw], size_buckets=2)
        assert raw == before
        assert prepared[0]["_raw"]["completion_rate"] == pytest.approx(0.5)
        assert prepared[0]["_raw"]["rpm"] == 0.0
        assert meta["sample"]["usable"] == 1

"""026 阶段三：评估层回归测试（可比性 / 检验 / 功效 / 冲击模型 / 治理）。

覆盖 plan §5.10 的检验项：数值对照、可信区间、可比性拒绝、基准强制、
多重比较、功效正确性、冲击模型参数恢复、导出护栏。
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any, Optional

import pytest

import CostView.src.evaluation as evaluation
from CostView.src.evaluation import (
    BENCHMARK_METRICS,
    METHODS,
    PRIMARY_BENCHMARK,
    STRATA_DIMENSIONS,
    ImpactModel,
    adjust_pvalues,
    clean_values,
    compare_groups,
    describe_strata,
    dimension_label,
    evaluate_dimension,
    evaluation_metadata,
    fit_impact_model,
    minimum_detectable_effect,
    missing_metadata_keys,
    power_summary,
    required_sample_per_group,
    strata_key_of,
    stratified_difference,
    total_variation_distance,
    worst_pairwise_tvd,
)
from CostView.src.tca_query_service import TcaQueryService
from platform_data.contracts import SCORECARD_COHORTS, ScorecardFilters

#: 正态近似闭式解的理论值（z_{0.975}=1.959964, z_{0.8}=0.841621）
_Z_ALPHA = 1.959963984540054
_Z_BETA = 0.8416212335729143


def _route(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "OrderId": "O1", "RouteId": "R1", "order_as_of_date": "20260418",
        "Exchange": "US", "equ_ticker": "AAPL US Equity",
        # cohort_key_and_label 会读取 Broker / algo（即使只取 asset_class 分支）
        "Broker": "BROKERA", "algo": "VWAP",
        "par_rate": None, "pnl_vwap": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestExportContract:
    """对齐 monitoring 包的导出护栏：``__all__`` 每个符号可解析。"""

    def test_all_symbols_resolvable(self) -> None:
        for name in evaluation.__all__:
            assert hasattr(evaluation, name), f"__all__ 中的 {name} 无法解析"

    def test_new_package_has_no_monitoring_dependency_cycle(self) -> None:
        """评估层只消费 tca_utils / env_context，不反向被 import（无环）。"""
        import CostView.src.monitoring as monitoring

        assert not hasattr(monitoring, "stratified_difference")
        assert not hasattr(monitoring, "build_evaluation_report")


class TestStrataDescription:
    """控制维度描述（027：门禁 → 描述；TVD 不再是阻断条件）。"""

    def test_total_variation_distance_bounds(self) -> None:
        identical = {"a": 0.5, "b": 0.5}
        disjoint = {"a": 1.0}
        assert total_variation_distance(identical, dict(identical)) == 0.0
        assert total_variation_distance(disjoint, {"b": 1.0}) == 1.0
        assert total_variation_distance({"a": 0.5, "b": 0.5}, {"a": 1.0}) == 0.5
        assert worst_pairwise_tvd([disjoint, {"b": 1.0}]) == 1.0

    def test_dimension_label_reuses_bucketing_single_source(self) -> None:
        """环境维度复用 tca_utils 分桶单点（缺失一律 unknown，不臆造桶）。"""
        assert dimension_label(_route(), "Exchange") == "US"
        assert dimension_label(_route(Exchange=None), "Exchange") == "unknown"
        assert dimension_label(_route(), "asset_class") == "equity"
        assert dimension_label(_route(), "time_of_day") == "unknown"
        assert dimension_label(_route(), "unknown_dim") == "unknown"

    def test_control_dimensions_exclude_asset_class(self) -> None:
        """控制维度 = Exchange + 环境三维；**不含** asset_class（与 Exchange 共线）。"""
        assert STRATA_DIMENSIONS == (
            "Exchange", "time_of_day", "liquidity_adv20", "volatility",
        )

    def test_imbalance_is_descriptive_not_blocking(self) -> None:
        """**027 关键回归**：Exchange 分布完全分离时不再判「不可比」，而是产出描述 + 告警。

        026 在同一组数据上会拒绝输出一切比较数值（真实库实测 Exchange TVD 恒为 1.0），
        本用例锁住「描述而非门禁」的语义。
        """
        groups = {
            "A": [_route(Exchange="US") for _ in range(30)],
            "B": [_route(Exchange="LN") for _ in range(30)],
        }
        described = describe_strata(groups)

        assert described["imbalance"]["Exchange"] == pytest.approx(1.0)
        assert described["group_sizes"] == {"A": 30, "B": 30}
        assert any("Exchange" in alert for alert in described["alerts"])
        assert "comparable" not in described          # 不再有判定字段

    def test_strata_key_can_exclude_a_dimension(self) -> None:
        """分层键必须能与分组维度正交（按 time_of_day 分组时排除它）。"""
        route = _route()
        assert len(strata_key_of()(route)) == len(STRATA_DIMENSIONS)
        assert strata_key_of(dimensions=("Exchange",))(route) == ("US",)


class TestStratified:
    """分层内比较与加权合并（027 替代 026 的可比性门禁）。"""

    @staticmethod
    def _mk(exchange: str, value: Optional[float]) -> Any:
        return _route(Exchange=exchange, pnl_vwap=value)

    @staticmethod
    def _key():
        return strata_key_of(dimensions=("Exchange",))

    def test_weighted_merge_matches_hand_computation(self) -> None:
        """合并值 = 各层效应按层样本量加权（手算对照）。"""
        left = [self._mk("US", 10.0)] * 4 + [self._mk("LN", 20.0)] * 6
        right = [self._mk("US", 0.0)] * 6 + [self._mk("LN", 0.0)] * 4
        result = stratified_difference(
            left, right, value_of=lambda r: r.pnl_vwap, key_of=self._key(),
            min_stratum_sample=3,
        )
        # US 层：10 − 0 = 10，权重 10；LN 层：20 − 0 = 20，权重 10
        assert result.stratified is True
        assert result.strata_used == 2
        assert result.difference == pytest.approx((10 * 10 + 20 * 10) / 20)
        assert result.coverage == pytest.approx(1.0)

    def test_undersized_stratum_is_skipped_and_disclosed(self) -> None:
        left = [self._mk("US", 10.0)] * 5 + [self._mk("LN", 20.0)] * 2
        right = [self._mk("US", 0.0)] * 5 + [self._mk("LN", 0.0)] * 2
        result = stratified_difference(
            left, right, value_of=lambda r: r.pnl_vwap, key_of=self._key(),
            min_stratum_sample=3,
        )
        assert result.strata_skipped == 1              # LN 层两侧样本不足
        assert result.stratified is False              # 仅 1 层可用 → 退化
        assert result.reason                          # 退化原因必须可见

    def test_single_stratum_degrades_to_pooled_with_reason(self) -> None:
        """层数 < 2 → 退化为整体比较，但**仍输出数值**（不拒绝结论）。"""
        left = [self._mk("US", 10.0)] * 5
        right = [self._mk("US", 0.0)] * 5
        result = stratified_difference(
            left, right, value_of=lambda r: r.pnl_vwap, key_of=self._key(),
            min_stratum_sample=3,
        )
        assert result.stratified is False
        assert result.difference == pytest.approx(10.0)
        assert result.coverage == 0.0
        assert result.confidence == "low"

    def test_coverage_and_heterogeneity_reported(self) -> None:
        left = [self._mk("US", 10.0)] * 5 + [self._mk("LN", 30.0)] * 5 + [self._mk("HK", 0.0)]
        right = [self._mk("US", 0.0)] * 5 + [self._mk("LN", 0.0)] * 5 + [self._mk("HK", 0.0)]
        result = stratified_difference(
            left, right, value_of=lambda r: r.pnl_vwap, key_of=self._key(),
            min_stratum_sample=3,
        )
        assert result.strata_used == 2
        assert result.strata_skipped == 1
        assert result.coverage == pytest.approx(20 / 22)
        assert result.heterogeneity == pytest.approx(20.0)   # 层效应极差
        assert result.to_payload()["strata_used"] == 2

    def test_non_finite_values_are_dropped_not_zeroed(self) -> None:
        """缺失一律剔除，**不补 0**（补 0 会把缺失读成「成本为零」）。"""
        left = [
            self._mk("US", None),
            self._mk("US", float("nan")),
            self._mk("US", 4.0),
        ]
        right = [self._mk("US", 0.0)] * 3
        result = stratified_difference(
            left, right, value_of=lambda r: r.pnl_vwap, key_of=self._key(),
            min_stratum_sample=1,
        )
        assert result.n_left == 1


class TestStatsTests:
    """统计检验与可信区间（规格见 Algo_TCA.md:726-793）。"""

    def test_clean_values_drops_non_finite(self) -> None:
        assert clean_values([1.0, None, float("nan"), float("inf"), 2.0]) == [1.0, 2.0]

    def test_supported_methods_frozen(self) -> None:
        assert METHODS == ("t-test", "ks", "chi2")

    def test_rejects_unknown_method(self) -> None:
        with pytest.raises(ValueError, match="不支持的检验方法"):
            compare_groups([1.0, 2.0], [1.0, 2.0], method="anova")

    def test_t_test_detects_clear_difference(self) -> None:
        left = [10.0 + i * 0.01 for i in range(60)]
        right = [20.0 + i * 0.01 for i in range(60)]
        result = compare_groups(left, right, method="t-test")

        assert result.significant is True
        assert result.difference == pytest.approx(-10.0, abs=0.05)
        assert result.n_left == 60 and result.n_right == 60
        # 均值差可信区间应完全落在 0 左侧
        assert result.ci_low is not None and result.ci_high is not None
        assert result.ci_high < 0

    def test_ks_and_chi2_available(self) -> None:
        left = [float(i) for i in range(50)]
        right = [float(i) + 0.2 for i in range(50)]
        for method in ("ks", "chi2"):
            result = compare_groups(left, right, method=method)
            assert result.method == method
            assert 0.0 <= result.p_value <= 1.0

    def test_small_samples_declare_unusable(self) -> None:
        """样本不足时不静默给出「不显著」，而是显式标注不可用。"""
        result = compare_groups([1.0], [2.0])
        assert result.p_value == 1.0
        assert "样本不足" in result.note

    def test_bootstrap_ci_requires_two_samples_each(self) -> None:
        low, high = _ci_min_max([1.0], [2.0, 3.0])
        assert low is None and high is None

    def test_bootstrap_ci_brackets_zero_for_same_distribution(self) -> None:
        left = [float(i % 7) for i in range(200)]
        right = [float(i % 7) for i in range(200)]
        result = compare_groups(left, right, method="t-test")
        assert result.ci_low is not None and result.ci_high is not None
        assert result.ci_low <= 0 <= result.ci_high

    def test_adjust_pvalues_bh_and_bonferroni(self) -> None:
        raw = [0.001, 0.01, 0.02, 0.5]
        bh = adjust_pvalues(raw, method="bh")
        bonf = adjust_pvalues(raw, method="bonferroni")

        assert len(bh) == len(raw)
        assert all(0.0 <= p <= 1.0 for p in bh + bonf)
        # Bonferroni 不弱于原值；BH 不弱于 Bonferroni
        assert all(b <= max(1.0, value * len(raw)) for b, value in zip(bonf, raw))
        assert all(bh_p <= bonf_p for bh_p, bonf_p in zip(bh, bonf))

    def test_adjust_pvalues_rejects_unknown_method(self) -> None:
        with pytest.raises(ValueError, match="不支持的校正方法"):
            adjust_pvalues([0.1], method="holm")


def _ci_min_max(left: list[float], right: list[float]):
    from CostView.src.evaluation import mean_difference_ci

    return mean_difference_ci(left, right)


class TestPower:
    """样本功效（正态近似闭式公式，不引入 statsmodels）。"""

    def test_required_sample_matches_closed_form(self) -> None:
        expected = math.ceil(2 * (_Z_ALPHA + _Z_BETA) ** 2)
        assert required_sample_per_group(1.0) == expected == 16

    def test_achieved_power_is_inverse_of_required(self) -> None:
        n = required_sample_per_group(1.0)
        achieved = evaluation.achieved_power(n, 1.0)
        assert achieved >= 0.8
        assert achieved < 0.85        # 恰好跨过阈值，不会远超

    def test_minimum_detectable_effect_round_trip(self) -> None:
        n = required_sample_per_group(1.0)
        assert minimum_detectable_effect(n) == pytest.approx(1.0, rel=0.02)

    def test_rejects_non_positive_effect(self) -> None:
        with pytest.raises(ValueError, match="effect_size 必须为正"):
            required_sample_per_group(0.0)
        with pytest.raises(ValueError, match="effect_size 必须为正"):
            evaluation.achieved_power(10, -1.0)

    def test_power_summary_gives_actionable_shortfall(self) -> None:
        summary = power_summary(5, 1.0)
        assert summary["sufficient"] is False
        assert summary["required_per_group"] == 16
        assert summary["shortfall"] == 11
        assert summary["minimum_detectable_effect"] > 1.0


class TestCostModel:
    """幂律冲击模型（合成数据参数恢复 + 域外不外推）。"""

    @staticmethod
    def _samples(n: int = 200, *, a: float = 5.0, b: float = 0.6, c: float = 1.0):
        rows = []
        for i in range(n):
            participation = 0.001 * (1 + i)
            volatility = 1.0 + (i % 20) * 0.1
            impact = a * participation ** b * volatility ** c
            rows.append((participation, volatility, impact))
        return rows

    def test_recovers_known_parameters(self) -> None:
        model = fit_impact_model(self._samples())

        assert isinstance(model, ImpactModel)
        assert model.intercept == pytest.approx(math.log(5.0), abs=1e-3)
        assert model.slope_participation == pytest.approx(0.6, abs=1e-3)
        assert model.slope_volatility == pytest.approx(1.0, abs=1e-3)
        assert model.r_squared == pytest.approx(1.0, abs=1e-6)

    def test_insufficient_samples_return_none(self) -> None:
        assert fit_impact_model(self._samples(5)) is None

    def test_drops_non_positive_samples(self) -> None:
        """对数变换要求三项严格为正；脏样本被剔除而非静默替换。"""
        rows = self._samples(60) + [(0.0, 1.0, 1.0), (0.1, 0.0, 1.0), (0.1, 1.0, 0.0)]
        model = fit_impact_model(rows)
        assert model is not None
        assert model.n_observations == 60

    def test_no_extrapolation_outside_domain(self) -> None:
        model = fit_impact_model(self._samples())
        assert model is not None

        inside = model.participation_domain[0]
        assert model.predict_bps(inside, 1.0) is not None
        # 域外一律 None（不外推）
        assert model.predict_bps(inside / 100.0, 1.0) is None
        assert model.predict_bps(inside, 999.0) is None

    def test_payload_discloses_no_forecast_note(self) -> None:
        model = fit_impact_model(self._samples())
        assert model is not None
        payload = model.to_payload()
        assert "不外推" in payload["note"]
        assert payload["n_observations"] == 200


class TestGovernance:
    """评估治理元数据（B4 治理层；基准不可默认）。"""

    def test_benchmark_is_mandatory(self) -> None:
        """D1：基准冻结 —— 服务端不设默认值，缺失即报错。"""
        with pytest.raises(ValueError, match="benchmark 必须显式指定"):
            evaluation_metadata(
                benchmark="", spec_version="2026.09.7",
                data_range=("20260401", "20260430"), scope={"mode": "x"},
                sample_sizes={"A": 10},
            )

    def test_metadata_contains_required_keys(self) -> None:
        payload = evaluation_metadata(
            benchmark="arrival",
            spec_version="2026.09.7",
            data_range=("20260401", "20260430"),
            scope={"mode": "bdib_whitelist"},
            sample_sizes={"A": 40, "B": 42},
            degradations=["liquidity_adv20 覆盖率 88%"],
        )

        assert missing_metadata_keys(payload) == ()
        assert payload["benchmark"] == "arrival"
        assert payload["data_range"]["start_date"] == "20260401"
        assert payload["degradations"] == ["liquidity_adv20 覆盖率 88%"]
        assert evaluation.REQUIRED_METADATA_KEYS

    def test_incomplete_metadata_raises(self) -> None:
        with pytest.raises(ValueError, match="治理元数据不完整"):
            evaluation.assert_governance_complete({"benchmark": "arrival"})

    def test_governance_schema_marks_version_lock(self) -> None:
        payload = evaluation_metadata(
            benchmark="vwap", spec_version="2026.09.7",
            data_range=("20260401", "20260430"), scope={}, sample_sizes={},
        )
        assert payload["governance_schema"] == "026-phase3"


class TestSpecBinding:
    """口径声明与实现绑定。

    `report_spec` 刻意**不 import** `evaluation`（否则构成
    `evaluation → monitoring.env_context → monitoring/__init__ → report_spec` 的包级循环），
    因此声明是字面量 —— 必须有本护栏守住「声明-实现」不漂移。
    """

    def test_spec_evaluation_block_matches_implementation(self) -> None:
        from CostView.src.evaluation import IMBALANCE_ALERT_TVD
        from CostView.src.monitoring import report_spec

        spec = report_spec.REPORT_SPEC["evaluation"]
        assert tuple(spec["strata_dimensions"]) == STRATA_DIMENSIONS
        assert tuple(spec["methods"]) == METHODS
        assert spec["imbalance_alert_threshold"] == IMBALANCE_ALERT_TVD
        # 027：失衡为**描述性提示**，不再阻断结论输出
        assert spec["imbalance_blocks_output"] is False
        assert spec["comparability_enforced_server_side"] is False
        # 027：控制维度与分组维度正交；比较形态为「每组 vs 其余（层内）」
        assert spec["strata_excludes_grouping_dimension"] is True
        assert spec["comparison_shape"] == "group-vs-rest-stratified"
        assert tuple(spec["benchmarks"]) == tuple(BENCHMARK_METRICS)
        assert spec["primary_benchmark"] == PRIMARY_BENCHMARK
        assert spec["ci_method"] == "bootstrap-percentile"
        assert spec["ci_bootstrap"] == evaluation.DEFAULT_REPORT_BOOTSTRAP
        assert spec["multiple_comparison"] == "benjamini-hochberg"

    def test_spec_version_reflects_phase3(self) -> None:
        from CostView.src.monitoring import report_spec

        assert report_spec.SPEC_VERSION == "2026.09.10"


def _stub_routes(broker: str, exchange: str, pnl: float, count: int) -> list[Any]:
    """构造一组同分布的替身路由（成本围绕 ``pnl`` 小幅抖动）。

    `pnl_vwap` 与 `arrival_cost_bps` **同时**给出：报告主基准是 `arrival`，
    只给 `pnl_vwap` 会让主基准列整列缺失（该情形有专门用例覆盖其披露行为）。
    """
    return [
        _route(
            OrderId=f"{broker}{i}", RouteId="R1", Broker=broker, Exchange=exchange,
            pnl_vwap=pnl + (i % 5 - 2) * 0.1,
            arrival_cost_bps=pnl + (i % 5 - 2) * 0.1,
            par_rate=0.01,
        )
        for i in range(count)
    ]


class TestEvaluationReportOrchestration:
    """综合评估报告编排（``TcaQueryService.build_evaluation_report``）的行为契约。

    取数与环境上下文经 monkeypatch 替换：本用例聚焦 027 的两处形态修正 ——
    「无可选择项（维度遍历 / 基准并列 / 方法并列）」与「不可比不再拒绝结论」；
    取数层已由 `test_report_metrics` 与 `test_env_context` 覆盖。
    """

    @staticmethod
    def _service(monkeypatch: pytest.MonkeyPatch, routes: list[Any]):
        service = TcaQueryService()
        monkeypatch.setattr(
            service, "_collect_routes",
            lambda filters, max_routes: (routes, False, None),
        )
        monkeypatch.setattr(service, "_build_env_context", lambda rts: {})
        return service

    @staticmethod
    def _filters() -> ScorecardFilters:
        return ScorecardFilters(start_date="20260401", end_date="20260430")

    def test_no_dimension_benchmark_or_method_parameter(self) -> None:
        """**027 关键回归**：唯一输入是时间范围与作用域 —— 不再有「选择」类参数。"""
        import inspect

        params = set(inspect.signature(TcaQueryService.build_evaluation_report).parameters)
        # 用户「选择」型参数必须不存在；alpha / correction 等属服务端内建算法参数，
        # 有合理默认且不作为 UI 选择项暴露（027 plan §2.1 / DP-4）
        for forbidden in ("dimension", "cohort", "benchmark", "method"):
            assert forbidden not in params, f"评估报告不应接受 {forbidden} 参数"

    def test_unknown_granularity_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = self._service(monkeypatch, [])
        with pytest.raises(ValueError, match="不支持的粒度"):
            service.build_evaluation_report(self._filters(), granularity="fortnight")

    def test_all_dimensions_covered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """维度**遍历全部**（用户不选维度）。"""
        routes = _stub_routes("A", "US", -5.0, 30) + _stub_routes("B", "US", -7.0, 30)
        payload = self._service(monkeypatch, routes).build_evaluation_report(self._filters())

        blocks = payload["sections"]["dimensions"]
        assert [block["dimension"] for block in blocks] == list(SCORECARD_COHORTS)

    def test_incomparable_exchange_no_longer_blocks(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """**027 关键回归**：Exchange 分布完全分离时**仍给出结论**。

        026 在同一组数据上返回「不可比」且不给任何比较数值（真实库实测恒为拒绝）。
        """
        routes = _stub_routes("A", "US", -5.0, 30) + _stub_routes("B", "LN", -3.0, 30)
        payload = self._service(monkeypatch, routes).build_evaluation_report(self._filters())

        broker = next(
            block for block in payload["sections"]["dimensions"]
            if block["dimension"] == "broker"
        )
        assert broker["rows"], "必须给出分组结论"
        for row in broker["rows"]:
            assert row["vs_others"]["difference"] is not None
            assert row["vs_others"]["confidence"] in {"low", "medium", "high"}
        # 构成差异改为**披露**，而非阻断
        assert broker["stratification"]["alerts"]
        assert "comparable" not in payload["sections"]["credibility"]

    def test_benchmarks_and_methods_are_all_present(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """基准与方法**全部并列**（用户不选基准、不选方法）。"""
        routes = _stub_routes("A", "US", -5.0, 30) + _stub_routes("B", "US", -9.0, 30)
        payload = self._service(monkeypatch, routes).build_evaluation_report(self._filters())

        assert payload["benchmarks"] == list(BENCHMARK_METRICS)
        assert payload["primary_benchmark"] == PRIMARY_BENCHMARK
        row = payload["sections"]["dimensions"][0]["rows"][0]
        assert set(row["benchmarks"]) == set(BENCHMARK_METRICS)
        assert set(row["tests"]) == set(METHODS)
        assert len(row["ci"]) == 2
        for method in METHODS:
            assert "p_value_adjusted" in row["tests"][method]

    def test_missing_primary_metric_is_disclosed(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """主基准整列缺失时必须显式披露（否则「无数值」会被读成「无差异」）。"""
        routes = [
            _route(OrderId=f"A{i}", Broker="A", Exchange="US", pnl_vwap=-5.0)
            for i in range(30)
        ]
        payload = self._service(monkeypatch, routes).build_evaluation_report(self._filters())

        broker = payload["sections"]["dimensions"][0]
        assert any("整列缺失" in alert for alert in broker["highlights"]["alerts"])
        # 其余基准的水平仍照常给出
        assert broker["rows"][0]["benchmarks"]["vwap"]["n"] == 30

    def test_sections_cover_all_content_domains(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routes = _stub_routes("A", "US", -5.0, 30)
        payload = self._service(monkeypatch, routes).build_evaluation_report(
            self._filters(), granularity="week",
        )
        assert set(payload["sections"]) == {
            "credibility", "dimensions", "trend", "risk", "market",
        }
        assert payload["period"]["granularity"] == "week"

    def test_governance_attached_to_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """治理层随结果返回（版本锁定 / 基准冻结 / 数据血缘）。"""
        routes = _stub_routes("A", "US", -5.0, 30)
        payload = self._service(monkeypatch, routes).build_evaluation_report(self._filters())

        governance = payload["governance"]
        assert governance["benchmark"] == PRIMARY_BENCHMARK
        assert governance["data_range"]["start_date"] == "20260401"
        assert governance["sample_sizes"] == {"total": 30}

    def test_benchmark_metric_mapping_is_closed(self) -> None:
        """基准 → 指标列的映射是封闭集合（新增基准必须显式登记）。"""
        assert set(BENCHMARK_METRICS) == {"arrival", "vwap", "close", "is"}
        assert len(set(BENCHMARK_METRICS.values())) == len(BENCHMARK_METRICS)


def _api_client():
    """CostView API 测试客户端（端点级用例用）。"""
    import sys
    from pathlib import Path

    api_root = Path(__file__).resolve().parents[1] / "api"
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app)


class TestEvaluationEndpoint:
    """端点层契约：门控降级可见（026 遗留 T16）+ 形态参数已移除。"""

    def test_gate_disabled_is_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """门控关闭时返回**显式不可用**，不回退到未校验的均值比较。

        026 遗留 T16：该分支此前无任何用例覆盖（如实标注后转记本计划补齐）。
        """
        from data_access.config import Config

        monkeypatch.setattr(Config, "TCA_EVAL_ENABLED", False)
        response = _api_client().post("/api/tca/evaluation/report", json={})

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["enabled"] is False
        assert body["data"]["sections"] is None
        assert "TCA_EVAL_ENABLED" in body["message"]

    def test_request_accepts_only_scope_and_granularity(self) -> None:
        from CostView.api.routers.costview import EvaluationReportRequest

        payload = EvaluationReportRequest().model_dump()
        assert set(payload) == {"filters", "granularity"}
        for forbidden in ("cohort", "benchmark", "method", "alpha", "correction"):
            assert forbidden not in payload

    def test_compare_endpoint_removed_and_report_registered(self) -> None:
        """026 的 `/compare` 已随形态修正移除；新端点为 `/report`。"""
        from CostView.api.routers.costview import router

        paths = {route.path for route in router.routes}
        assert "/api/tca/evaluation/report" in paths
        assert "/api/tca/evaluation/compare" not in paths


def _evaluation_block(alert_count: int = 1) -> dict[str, Any]:
    """构造评估 payload 的最小骨架（渲染用例用）。"""
    return {
        "primary_benchmark": "arrival",
        "period": {"start_date": "20260401", "end_date": "20260430", "granularity": "week"},
        "sections": {
            "dimensions": [
                {
                    "dimension": "broker",
                    "group_count": 26,
                    "rows": [
                        {"vs_others": {"confidence": "medium"}},
                        {"vs_others": {"confidence": "low"}},
                    ],
                    "highlights": {
                        "best": {"label": "EQ-RBC", "difference": -29.58},
                        "worst": {"label": "EQ-CLSA", "difference": 16.2},
                        "minimum_detectable_effect": 71.88,
                        "alerts": [f"告警 {index}" for index in range(alert_count)],
                    },
                }
            ]
        },
    }


class TestEvaluationReportSection:
    """报告内嵌评估章节（027 P3）：渲染、限行与降级。"""

    def test_renders_dimension_summary(self) -> None:
        from CostView.src.monitoring.tca_report_html import _render_evaluation_section

        html = _render_evaluation_section(_evaluation_block())
        assert "算法执行质量综合评估" in html
        assert "broker" in html
        assert "EQ-RBC" in html and "EQ-CLSA" in html
        # 口径解释必须随章节出现（读者需知道结论建立在层内比较之上）
        assert "共同层内" in html

    def test_absent_evaluation_renders_nothing(self) -> None:
        from CostView.src.monitoring.tca_report_html import _render_evaluation_section

        assert _render_evaluation_section(None) == ""
        assert _render_evaluation_section({"sections": {"dimensions": []}}) == ""

    def test_alerts_are_capped(self) -> None:
        """报告是归档物：告警数量必须受控。"""
        from CostView.src.monitoring.tca_report_html import (
            _MAX_EVALUATION_ALERTS,
            _render_evaluation_section,
        )

        html = _render_evaluation_section(_evaluation_block(alert_count=20))
        assert html.count("<li>") == _MAX_EVALUATION_ALERTS

    def test_empty_report_carries_evaluation_key(self) -> None:
        """空报告也须带 ``evaluation`` 键（消费方统一处理，不必判 key 是否存在）。"""
        from CostView.src.monitoring.report_aggregator import TcaReportAggregator

        empty = TcaReportAggregator()._empty_report(
            "20260401", "20260430", None, None, None, None, [],
        )
        assert empty["evaluation"] is None

    def test_evaluation_failure_does_not_break_report(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """评估章节失败**不得**使整份报告不可用（与各小节可独立降级一致）。"""
        service = TcaQueryService()

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("simulated evaluation failure")

        monkeypatch.setattr(service, "build_evaluation_report", _boom)
        report: dict[str, Any] = {"filters": {"granularity": "day"}, "kpi": {"route_count": 1}}
        service.attach_evaluation_summary(report, ScorecardFilters())

        assert report["evaluation"] is None
        assert report["kpi"] == {"route_count": 1}      # 其余内容不受影响

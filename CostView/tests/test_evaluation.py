"""026 阶段三：评估层回归测试（可比性 / 检验 / 功效 / 冲击模型 / 治理）。

覆盖 plan §5.10 的检验项：数值对照、可信区间、可比性拒绝、基准强制、
多重比较、功效正确性、冲击模型参数恢复、导出护栏。
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

import CostView.src.evaluation as evaluation
from CostView.src.evaluation import (
    METHODS,
    ComparabilityVerdict,
    ImpactModel,
    adjust_pvalues,
    assess_comparability,
    clean_values,
    compare_groups,
    dimension_label,
    evaluation_metadata,
    fit_impact_model,
    minimum_detectable_effect,
    missing_metadata_keys,
    power_summary,
    required_sample_per_group,
    total_variation_distance,
)

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

        assert not hasattr(monitoring, "assess_comparability")


class TestComparability:
    """可比性判定（B3 约束的服务端强制，plan §5.2 DP-3-2）。"""

    def test_total_variation_distance_bounds(self) -> None:
        identical = {"a": 0.5, "b": 0.5}
        disjoint = {"a": 1.0}
        assert total_variation_distance(identical, dict(identical)) == 0.0
        assert total_variation_distance(disjoint, {"b": 1.0}) == 1.0
        assert total_variation_distance({"a": 0.5, "b": 0.5}, {"a": 1.0}) == 0.5

    def test_undersized_group_is_not_comparable(self) -> None:
        verdict = assess_comparability(
            {"A": [_route() for _ in range(3)], "B": [_route() for _ in range(50)]},
        )
        assert verdict.comparable is False
        assert any("组样本不足" in reason for reason in verdict.reasons)

    def test_balanced_groups_are_comparable(self) -> None:
        """同分布、样本充足 → 可比。"""
        groups = {
            "A": [_route(Exchange="US") for _ in range(40)],
            "B": [_route(Exchange="US") for _ in range(40)],
        }
        verdict = assess_comparability(groups, min_group_sample=10)
        assert isinstance(verdict, ComparabilityVerdict)
        assert verdict.comparable is True
        assert verdict.unmet_dimensions == ()
        assert verdict.common_strata >= 1

    def test_imbalanced_dimension_blocks_comparison(self) -> None:
        """Exchange 分布完全分离 → 该维度失衡，判不可比。"""
        groups = {
            "A": [_route(Exchange="US") for _ in range(30)],
            "B": [_route(Exchange="LN") for _ in range(30)],
        }
        verdict = assess_comparability(groups, min_group_sample=10)

        assert verdict.comparable is False
        assert "Exchange" in verdict.unmet_dimensions
        assert verdict.imbalance["Exchange"] == pytest.approx(1.0)
        # payload 必须让不可比原因可见
        payload = verdict.to_payload()
        assert payload["comparable"] is False
        assert payload["unmet_dimensions"] == ["Exchange"]

    def test_dimension_label_reuses_bucketing_single_source(self) -> None:
        """环境维度复用 tca_utils 分桶单点（缺失一律 unknown，不臆造桶）。"""
        assert dimension_label(_route(), "Exchange") == "US"
        assert dimension_label(_route(Exchange=None), "Exchange") == "unknown"
        assert dimension_label(_route(), "asset_class") == "equity"
        assert dimension_label(_route(), "time_of_day") == "unknown"
        assert dimension_label(_route(), "unknown_dim") == "unknown"

    def test_default_strata_dimensions_cover_plan_spec(self) -> None:
        """默认分层键覆盖 plan §5.3 声明的五个维度。"""
        assert evaluation.DEFAULT_STRATA_DIMENSIONS == (
            "Exchange", "asset_class", "time_of_day", "liquidity_adv20", "volatility",
        )


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
        from CostView.src.monitoring import report_spec

        spec = report_spec.REPORT_SPEC["evaluation"]
        assert tuple(spec["strata_dimensions"]) == evaluation.DEFAULT_STRATA_DIMENSIONS
        assert tuple(spec["methods"]) == METHODS
        assert spec["imbalance_threshold"] == evaluation.DEFAULT_IMBALANCE_TVD
        assert spec["benchmark_required"] is True
        assert spec["comparability_enforced_server_side"] is True
        assert spec["ci_method"] == "bootstrap-percentile"
        assert spec["multiple_comparison"] == "benjamini-hochberg"

    def test_spec_version_reflects_phase3(self) -> None:
        from CostView.src.monitoring import report_spec

        assert report_spec.SPEC_VERSION == "2026.09.8"

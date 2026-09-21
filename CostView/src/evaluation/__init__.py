"""CostView 算法评估层（026 建立、**027 改造形态**）—— ADR-0004 规划的 `evaluation/` 落地。

## 027 的定位变化

026 交付的是「交互式比较工具」：调用方选 1 个维度 + 1 个基准 + 1 种方法。
027 改为「**按时间范围自动产出的综合评估报告**」——维度遍历、基准并列、方法并列，
「不可比就拒绝输出」改为「层内比较 + 置信度披露」。

职责：

    report        — 综合评估编排（唯一入口：`build_evaluation_report`）
    stratified    — 分层内比较与样本量加权合并（027 替代 026 的可比性门禁）
    comparability — 控制维度定义、分层键、构成失衡**描述**（不再阻断结论）
    stats_tests   — 统计检验与可信区间（t / KS / χ²；含多重比较校正）
    power         — 样本功效与最小可检测效应（正态近似，不引入 statsmodels）
    cost_model    — 成本回归与市场冲击函数估计（幂律；域外不外推）
    governance    — 评估治理元数据（版本锁定 / 基准冻结 / 数据血缘 / 降级披露）

``__all__`` 必须与上方 import 严格对应（与 ``monitoring`` 包同一约定，
由 ``CostView/tests/test_evaluation.py`` 的导出护栏守住）。

**不负责**：报告口径（``monitoring.report_measure`` / ``report_spec``）、
执行环境派生（``monitoring.env_context``）、分桶（``tca_utils``）——
本包只消费它们，不重复实现。
"""

from .comparability import (
    DEFAULT_MIN_GROUP_SAMPLE,
    ENV_DIMS,
    IMBALANCE_ALERT_TVD,
    STRATA_DIMENSIONS,
    UNKNOWN_LABEL,
    describe_strata,
    dimension_label,
    strata_key_of,
    total_variation_distance,
    worst_pairwise_tvd,
)
from .cost_model import (
    DEFAULT_MIN_OBSERVATIONS,
    ImpactModel,
    fit_impact_model,
)
from .governance import (
    REQUIRED_METADATA_KEYS,
    assert_governance_complete,
    evaluation_metadata,
    missing_metadata_keys,
)
from .power import (
    DEFAULT_ALPHA,
    DEFAULT_POWER,
    achieved_power,
    minimum_detectable_effect,
    power_summary,
    required_sample_per_group,
)
from .report import (
    BENCHMARK_METRICS,
    DEFAULT_MAX_GROUPS,
    DEFAULT_REPORT_BOOTSTRAP,
    DEFAULT_REPORT_MIN_SAMPLE,
    PRIMARY_BENCHMARK,
    build_evaluation_report,
    describe_values,
    evaluate_dimension,
)
from .stats_tests import (
    CHI2_BUCKETS,
    METHODS,
    TestResult,
    adjust_pvalues,
    clean_values,
    compare_groups,
    mean_difference_ci,
)
from .stratified import (
    CONFIDENCE_HIGH_COVERAGE,
    CONFIDENCE_HIGH_STRATA,
    DEFAULT_LOW_COVERAGE,
    MIN_STRATUM_SAMPLE,
    StratifiedResult,
    StratumEffect,
    stratified_difference,
    stratum_values,
)

__all__ = [
    "BENCHMARK_METRICS",
    "CHI2_BUCKETS",
    "CONFIDENCE_HIGH_COVERAGE",
    "CONFIDENCE_HIGH_STRATA",
    "DEFAULT_ALPHA",
    "DEFAULT_LOW_COVERAGE",
    "DEFAULT_MAX_GROUPS",
    "DEFAULT_MIN_GROUP_SAMPLE",
    "DEFAULT_MIN_OBSERVATIONS",
    "DEFAULT_POWER",
    "DEFAULT_REPORT_BOOTSTRAP",
    "DEFAULT_REPORT_MIN_SAMPLE",
    "ENV_DIMS",
    "IMBALANCE_ALERT_TVD",
    "METHODS",
    "MIN_STRATUM_SAMPLE",
    "PRIMARY_BENCHMARK",
    "REQUIRED_METADATA_KEYS",
    "STRATA_DIMENSIONS",
    "UNKNOWN_LABEL",
    "ImpactModel",
    "StratifiedResult",
    "StratumEffect",
    "TestResult",
    "achieved_power",
    "adjust_pvalues",
    "assert_governance_complete",
    "build_evaluation_report",
    "clean_values",
    "compare_groups",
    "describe_strata",
    "describe_values",
    "dimension_label",
    "evaluate_dimension",
    "evaluation_metadata",
    "fit_impact_model",
    "mean_difference_ci",
    "minimum_detectable_effect",
    "missing_metadata_keys",
    "power_summary",
    "required_sample_per_group",
    "strata_key_of",
    "stratified_difference",
    "stratum_values",
    "total_variation_distance",
    "worst_pairwise_tvd",
]

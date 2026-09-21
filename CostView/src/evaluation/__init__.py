"""CostView 算法评估层（026 阶段三）—— ADR-0004 规划的 `evaluation/` 落地。

职责：

    comparability — 可比样本匹配与可比性判定（B3「足够相似才具解释力」的服务端强制）
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
    DEFAULT_IMBALANCE_TVD,
    DEFAULT_MIN_GROUP_SAMPLE,
    DEFAULT_STRATA_DIMENSIONS,
    ComparabilityVerdict,
    assess_comparability,
    dimension_label,
    total_variation_distance,
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
from .stats_tests import (
    CHI2_BUCKETS,
    METHODS,
    TestResult,
    adjust_pvalues,
    clean_values,
    compare_groups,
    mean_difference_ci,
)

__all__ = [
    "CHI2_BUCKETS",
    "DEFAULT_ALPHA",
    "DEFAULT_IMBALANCE_TVD",
    "DEFAULT_MIN_GROUP_SAMPLE",
    "DEFAULT_MIN_OBSERVATIONS",
    "DEFAULT_POWER",
    "DEFAULT_STRATA_DIMENSIONS",
    "METHODS",
    "REQUIRED_METADATA_KEYS",
    "ComparabilityVerdict",
    "ImpactModel",
    "TestResult",
    "achieved_power",
    "adjust_pvalues",
    "assert_governance_complete",
    "assess_comparability",
    "clean_values",
    "compare_groups",
    "dimension_label",
    "evaluation_metadata",
    "fit_impact_model",
    "mean_difference_ci",
    "minimum_detectable_effect",
    "missing_metadata_keys",
    "power_summary",
    "required_sample_per_group",
    "total_variation_distance",
]

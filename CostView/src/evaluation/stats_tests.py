"""统计检验与可信区间 —— 026 阶段三（评估层）。

规格来源（库内一致性）：`docs/textbook/Algo_TCA.md` 给出 χ² 检验（`:726-767`）与
Kolmogorov-Smirnov 检验（`:789-793`）的分步算法，以及**可比性前置要求**（`:764`、`:789`）：

> Ensure that the orders traded in each algorithm have similar characteristics such as
> side, size, volatility, trade time, and market cap, and were traded in similar market
> conditions.

该前置要求由 `comparability.assess_comparability` 强制；本模块只负责「可比之后」的检验。

**依赖**：`scipy`（DP-3-1 已裁定引入）。**不引入 `statsmodels`**：样本功效由 `power.py`
以正态近似闭式公式自实现。

**可信区间为何用 bootstrap**：成本分布右偏、尾部厚（`cost_cvar` 的存在即证据），
正态近似会系统性窄化区间。
"""

from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from scipy import stats as _stats

#: 支持的检验方法：t = Welch 不等方差；ks = 分布差异；chi2 = 分桶分布差异
METHODS: tuple[str, ...] = ("t-test", "ks", "chi2")

#: χ² 分桶数（`Algo_TCA.md:766` 建议 10~20 桶，取区间下沿以适配中小样本）
CHI2_BUCKETS: int = 10

DEFAULT_BOOTSTRAP: int = 2000


@dataclass(frozen=True)
class TestResult:
    """检验结果：统计量 + p 值 + 可信区间 + 样本量，缺一项都不足以审计。"""

    method: str
    statistic: float
    p_value: float
    n_left: int
    n_right: int
    difference: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]
    alpha: float
    note: str = ""

    @property
    def significant(self) -> bool:
        """在给定 alpha 下是否拒绝「两组无差异」原假设。"""
        return self.p_value < self.alpha

    def to_payload(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "statistic": self.statistic,
            "p_value": self.p_value,
            "n_left": self.n_left,
            "n_right": self.n_right,
            "difference": self.difference,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "alpha": self.alpha,
            "significant": self.significant,
            "note": self.note,
        }


def clean_values(values: Sequence[Optional[float]]) -> list[float]:
    """剔除非有限值（None / NaN / inf）—— 检验不接受脏样本，且不静默补 0。"""
    cleaned: list[float] = []
    for value in values:
        if value is None:
            continue
        number = float(value)
        if math.isfinite(number):
            cleaned.append(number)
    return cleaned


def mean_difference_ci(
    left: Sequence[float],
    right: Sequence[float],
    *,
    alpha: float = 0.05,
    bootstrap: int = DEFAULT_BOOTSTRAP,
    seed: int = 0,
) -> tuple[Optional[float], Optional[float]]:
    """均值差（left − right）的 bootstrap 百分位可信区间。样本过少时返回 (None, None)。"""
    if len(left) < 2 or len(right) < 2 or bootstrap <= 0:
        return None, None
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(bootstrap):
        sample_l = [left[rng.randrange(len(left))] for _ in range(len(left))]
        sample_r = [right[rng.randrange(len(right))] for _ in range(len(right))]
        diffs.append(
            sum(sample_l) / len(sample_l) - sum(sample_r) / len(sample_r)
        )
    diffs.sort()
    low = diffs[max(0, int(alpha / 2 * bootstrap))]
    high = diffs[min(bootstrap - 1, int((1 - alpha / 2) * bootstrap))]
    return round(low, 6), round(high, 6)


def _chi2_on_buckets(left: list[float], right: list[float]) -> tuple[float, float, str]:
    """按**合并样本的分位切点**分桶后做卡方检验（`Algo_TCA.md:766` 口径）。

    返回 ``(statistic, p_value, note)``。两类退化情形在此处理并给出可用性说明：

    - 取值大量重复时多个分位切点取到同一数值 → 出现**空桶**（整列计数为 0），
      `scipy.stats.chi2_contingency` 会因期望频数为 0 直接抛 ``ValueError``
      —— 026 的小样本用例未覆盖，真实库（`202604` 期 `broker` 维度）首次触发；
    - 过滤空桶后有效桶 < 2 → 卡方检验无意义。

    两类情形均置 ``p = 1.0``（保守：不声称显著），并由 ``note`` 显式披露，
    而不是让异常穿透到调用方。
    """
    combined = sorted(left + right)
    total = len(combined)
    breakpoints = [
        combined[min(total - 1, int(k / CHI2_BUCKETS * total))]
        for k in range(1, CHI2_BUCKETS)
    ]

    def bucketize(values: list[float]) -> list[int]:
        counts = [0] * CHI2_BUCKETS
        for value in values:
            counts[min(CHI2_BUCKETS - 1, bisect.bisect_left(breakpoints, value))] += 1
        return counts

    rows = [bucketize(left), bucketize(right)]
    # 剔除空桶（两侧计数都为 0 的列）：其期望频数为 0，卡方统计量在此无定义
    non_empty = [
        index for index in range(CHI2_BUCKETS)
        if rows[0][index] + rows[1][index] > 0
    ]
    if len(non_empty) < 2:
        return 0.0, 1.0, (
            f"分桶后退化（有效桶 {len(non_empty)} 个 < 2），卡方检验不可用（p 值置 1）"
        )

    table = [[row[index] for index in non_empty] for row in rows]
    try:
        statistic, p_value, _, _ = _stats.chi2_contingency(table)
    except ValueError as exc:  # 兜底：期望频数为 0 等退化情形
        return 0.0, 1.0, f"卡方检验退化（{exc}），p 值置 1"
    return float(statistic), float(p_value), ""


def compare_groups(
    left: Sequence[Optional[float]],
    right: Sequence[Optional[float]],
    *,
    method: str = "t-test",
    alpha: float = 0.05,
    bootstrap: int = DEFAULT_BOOTSTRAP,
    seed: int = 0,
    with_ci: bool = True,
) -> TestResult:
    """两组成本的差异检验（含均值差的可信区间）。

    方法语义：

    - ``t-test``：Welch 不等方差 t 检验（比较**均值**，对尾部不敏感）；
    - ``ks``：两样本 Kolmogorov-Smirnov 检验（比较**整条分布**，不假设正态）；
    - ``chi2``：分桶后的卡方检验（对分位切点敏感，适合看「分布形状迁移」）。

    三种方法回答不同问题，**不应只报其中最有利的一个**（D1 基准冻结的同源要求）。
    """
    if method not in METHODS:
        raise ValueError(f"不支持的检验方法 {method!r}；可用：{', '.join(METHODS)}")

    values_l = clean_values(left)
    values_r = clean_values(right)
    difference = (
        sum(values_l) / len(values_l) - sum(values_r) / len(values_r)
        if values_l and values_r else None
    )

    note = ""
    if len(values_l) < 2 or len(values_r) < 2:
        statistic, p_value = 0.0, 1.0
        note = "样本不足两组各 2 条，检验结果不可用（p 值置 1）"
    elif method == "t-test":
        statistic, p_value = _stats.ttest_ind(values_l, values_r, equal_var=False)
    elif method == "ks":
        statistic, p_value = _stats.ks_2samp(values_l, values_r)
    else:
        statistic, p_value, note = _chi2_on_buckets(values_l, values_r)

    if with_ci:
        ci_low, ci_high = mean_difference_ci(
            values_l, values_r, alpha=alpha, bootstrap=bootstrap, seed=seed,
        )
    else:
        # 可信区间只依赖数据、不依赖检验方法：报告场景下同一对样本只算一次，
        # 由调用方在方法循环外求得（026 曾在每个方法内各算一次，实测放大 3 倍耗时）
        ci_low, ci_high = None, None
    return TestResult(
        method=method,
        statistic=float(statistic),
        p_value=float(p_value),
        n_left=len(values_l),
        n_right=len(values_r),
        difference=None if difference is None else round(difference, 6),
        ci_low=ci_low,
        ci_high=ci_high,
        alpha=alpha,
        note=note,
    )


def adjust_pvalues(
    pvalues: Sequence[float], *, method: str = "bh",
) -> list[float]:
    """多重比较校正（同一报告内比较多个 broker / 算法时**必须**校正）。

    - ``bh``：Benjamini-Hochberg（控制 FDR，默认；探索性比较的常规选择）；
    - ``bonferroni``：Bonferroni（控制 FWER，更保守）。

    未校正与校正后的 p 值都应随结果返回 —— 只报其一都会掩盖多重比较的代价。
    """
    raw = [float(p) for p in pvalues]
    n = len(raw)
    if n == 0:
        return []
    if method == "bonferroni":
        return [min(1.0, p * n) for p in raw]
    if method != "bh":
        raise ValueError(f"不支持的校正方法 {method!r}；可用：bh, bonferroni")

    order = sorted(range(n), key=lambda i: raw[i])
    adjusted = [0.0] * n
    running = 1.0
    for rank, index in enumerate(reversed(order), start=1):
        position = n - rank + 1
        running = min(running, raw[index] * n / position)
        adjusted[index] = min(1.0, running)
    return adjusted

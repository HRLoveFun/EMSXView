"""分层内比较与加权合并 —— 027。

## 为什么不是「可比性门禁」

026 把 B3 的「足够相似才具解释力」实现成了**门禁**：先检查两组在各分层维度上的整体
分布是否一致，不一致就**拒绝输出**比较数值。真实数据上该门禁恒为拒绝 —— 券商的成交
本就横跨多个交易市场，`Exchange` 的总变差距离实测恒等于 **1.0**（理论最大值），
于是任何跨券商比较都拿不到结论（`docs/archive/2026-09-21/026-costview-algo-eval/`）。

正确做法是用分层来**控制**而不是用来拒绝：在同一层内（同一市场、同一时段、同一流动性
桶）比较，层内这些维度自然一致，构成差异被剔除；再把各层效应按样本量加权合并。
结论仍然给出，但**建立在可比样本之上**，并披露它覆盖了多少样本。

## 合并方式

样本量加权（固定效应）：

    difference = Σ(n_i · d_i) / Σ n_i        （n_i 取层内两侧样本量之和）

层间异质性以「层效应极差」与「纳入层数」披露 —— 不引随机效应模型：报告读者需要回答的
是「结论是否依赖某一层」，而不是一个需要额外假设的方差分量估计。

## 退化为整体比较

纳入层数 < 2 时无法加权合并（也没有「控制」可言），此时**退化为整体比较**并置
``stratified=False`` + 原因 —— 既不静默降级，也不拒绝结论。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Callable, Mapping, Optional, Sequence

#: 层内**两侧各自**的最小样本量；低于此值的层不纳入合并
MIN_STRATUM_SAMPLE: int = 3

#: 层覆盖率低于该值时标记为低置信（仅影响 `confidence` 分档，不阻断输出）
DEFAULT_LOW_COVERAGE: float = 0.5

#: 置信度分档阈值
CONFIDENCE_HIGH_COVERAGE: float = 0.9
CONFIDENCE_HIGH_STRATA: int = 5

StrataKey = tuple[str, ...]
ValueOf = Callable[[Any], Optional[float]]
KeyOf = Callable[[Any], StrataKey]


@dataclass(frozen=True)
class StratumEffect:
    """单个层内的比较结果。"""

    key: StrataKey
    n_left: int
    n_right: int
    difference: float

    @property
    def weight(self) -> int:
        return self.n_left + self.n_right


@dataclass(frozen=True)
class StratifiedResult:
    """分层比较结果。

    ``difference`` 为层样本量加权的合并均值差（``left − right``）；``stratified=False``
    表示未分层（层数不足），此时 ``difference`` 为整体均值差。
    """

    difference: Optional[float]
    stratified: bool
    reason: str
    strata: tuple[StratumEffect, ...] = ()
    strata_skipped: int = 0
    coverage: float = 0.0
    heterogeneity: float = 0.0
    confidence: str = "low"
    n_left: int = 0
    n_right: int = 0

    @property
    def strata_used(self) -> int:
        return len(self.strata)

    def to_payload(self) -> dict[str, Any]:
        """结构化输出（层明细一并返回，供报告下钻与审计）。"""
        return {
            "difference": None if self.difference is None else round(self.difference, 4),
            "stratified": self.stratified,
            "reason": self.reason,
            "strata_used": self.strata_used,
            "strata_skipped": self.strata_skipped,
            "coverage": round(self.coverage, 4),
            "heterogeneity": round(self.heterogeneity, 4),
            "confidence": self.confidence,
            "n_left": self.n_left,
            "n_right": self.n_right,
            "strata": [
                {
                    "key": list(item.key),
                    "n_left": item.n_left,
                    "n_right": item.n_right,
                    "difference": round(item.difference, 4),
                }
                for item in self.strata
            ],
        }


def _clean_pairs(
    routes: Sequence[Any], value_of: ValueOf, key_of: KeyOf,
) -> tuple[dict[StrataKey, list[float]], int]:
    """路由 → (层键 → 有效值列表) 与「总有效样本量」。

    非有限值（``None`` / ``nan`` / ``inf``）一律剔除，不补 0 —— 补 0 会把缺失读成
    「成本为零」，是比丢样本更有害的失真。
    """
    buckets: dict[StrataKey, list[float]] = {}
    total = 0
    for route in routes:
        value = value_of(route)
        if value is None:
            continue
        value = float(value)
        if not math.isfinite(value):
            continue
        key = key_of(route)
        buckets.setdefault(key, []).append(value)
        total += 1
    return buckets, total


def _confidence(
    *, stratified: bool, coverage: float, strata_used: int,
    n_left: int, low_coverage: float,
) -> str:
    """置信度分档（描述性，不改变结论是否输出）。"""
    if n_left <= 0:
        return "low"
    if not stratified or coverage < low_coverage:
        return "low"
    if coverage >= CONFIDENCE_HIGH_COVERAGE and strata_used >= CONFIDENCE_HIGH_STRATA:
        return "high"
    return "medium"


def stratified_difference(
    left: Sequence[Any],
    right: Sequence[Any],
    *,
    value_of: ValueOf,
    key_of: KeyOf,
    min_stratum_sample: int = MIN_STRATUM_SAMPLE,
    low_coverage: float = DEFAULT_LOW_COVERAGE,
) -> StratifiedResult:
    """在共同层内比较 ``left`` 与 ``right``，按层样本量加权合并。

    - 层内**两侧各自**样本量 < ``min_stratum_sample`` 的层不纳入（计入 ``strata_skipped``）；
    - 无共同层或纳入层数 < 2 → 退化为整体均值差，``stratified=False`` 并给出原因；
    - ``coverage`` = 纳入层样本量 / 总有效样本量（两侧合计）。
    """
    left_buckets, left_total = _clean_pairs(left, value_of, key_of)
    right_buckets, right_total = _clean_pairs(right, value_of, key_of)
    grand_total = left_total + right_total

    strata: list[StratumEffect] = []
    skipped = 0
    for key in sorted(set(left_buckets) & set(right_buckets)):
        left_values = left_buckets[key]
        right_values = right_buckets[key]
        if len(left_values) < min_stratum_sample or len(right_values) < min_stratum_sample:
            skipped += 1
            continue
        strata.append(StratumEffect(
            key=key,
            n_left=len(left_values),
            n_right=len(right_values),
            difference=mean(left_values) - mean(right_values),
        ))

    if len(strata) < 2:
        # 退化：整体比较（层内控制不成立，故不作分层声称）
        pooled = _pooled_difference(left_buckets, right_buckets)
        reason = (
            "共同层不足 2 个，未做分层控制"
            if not strata else
            "仅有 1 个可用层，未做分层控制"
        )
        return StratifiedResult(
            difference=pooled,
            stratified=False,
            reason=reason,
            strata=tuple(strata),
            strata_skipped=skipped,
            coverage=0.0,
            heterogeneity=0.0,
            confidence=_confidence(
                stratified=False, coverage=0.0, strata_used=len(strata),
                n_left=left_total, low_coverage=low_coverage,
            ),
            n_left=left_total,
            n_right=right_total,
        )

    total_weight = sum(item.weight for item in strata)
    merged = sum(item.difference * item.weight for item in strata) / total_weight
    covered = sum(item.weight for item in strata)
    coverage = covered / grand_total if grand_total else 0.0
    differences = [item.difference for item in strata]

    return StratifiedResult(
        difference=merged,
        stratified=True,
        reason="",
        strata=tuple(strata),
        strata_skipped=skipped,
        coverage=coverage,
        heterogeneity=max(differences) - min(differences),
        confidence=_confidence(
            stratified=True, coverage=coverage, strata_used=len(strata),
            n_left=left_total, low_coverage=low_coverage,
        ),
        n_left=left_total,
        n_right=right_total,
    )


def _pooled_difference(
    left_buckets: Mapping[StrataKey, list[float]],
    right_buckets: Mapping[StrataKey, list[float]],
) -> Optional[float]:
    """退化路径：忽略分层键的整体均值差（无有效样本时返回 ``None``）。"""
    left_values = [value for values in left_buckets.values() for value in values]
    right_values = [value for values in right_buckets.values() for value in values]
    if not left_values or not right_values:
        return None
    return mean(left_values) - mean(right_values)


def stratum_values(
    routes: Sequence[Any], *, value_of: ValueOf, key_of: KeyOf,
) -> dict[StrataKey, list[float]]:
    """按层分组取有效值（供调用方复用同一清洗口径，避免各处重复实现）。"""
    buckets, _ = _clean_pairs(routes, value_of, key_of)
    return buckets


__all__ = [
    "CONFIDENCE_HIGH_COVERAGE",
    "CONFIDENCE_HIGH_STRATA",
    "DEFAULT_LOW_COVERAGE",
    "MIN_STRATUM_SAMPLE",
    "StratifiedResult",
    "StratumEffect",
    "stratified_difference",
    "stratum_values",
]

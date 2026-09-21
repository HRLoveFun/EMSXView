"""可比样本匹配与可比性判定 —— 026 阶段三（ADR-0004 规划的评估层）。

## 为什么必须有这一层

B3 的逐字要求（`docs/textbook/股票交易执行质量与交易成本分析（TCA）：跨时期学术研究综述与方法框架.md:109`）：

> 按股票流动性、订单规模/ADV、交易方向、时段、波动状态、紧迫度和执行算法分层。
> **只有在这些维度足够相似时，跨经纪商或跨策略比较才具有解释力。**

原始均值排序在分层失衡时会把「样本构成差异」读成「执行能力差异」。本模块把该约束
做成**服务端强制**（plan §5.2 DP-3-2）：不可比时返回结构化判定，**不返回比较数值**，
调用方无法绕过 —— 若检查只放 UI 层，直接调用 API 仍可取原始均值做比较。

## 分层键

`(Exchange, asset_class, time_of_day, liquidity_adv20, volatility)` —— 后三者全部来自
阶段二的**真实环境变量**。**禁止**用 `pnl_vwap` 等成本量作分层键：那会构成循环论证
（用成本定义分层、再按分层比较成本）。

## 失衡度量的选择

用**总变差距离（TVD）**而非卡方检验：TVD 对期望频数无下限要求（小样本稳定），
且数值可直接读作「概率质量不重叠比例」，便于在报告中向人解释 —— 而卡方在
`time_of_day` 这类多层稀疏维度上常因期望频数不足而不可靠。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from ..monitoring.env_context import env_route_key
from ..tca_utils import cohort_key_and_label

#: 默认分层键（顺序即报告中的展示顺序）
DEFAULT_STRATA_DIMENSIONS: tuple[str, ...] = (
    "Exchange", "asset_class", "time_of_day", "liquidity_adv20", "volatility",
)

#: 「非环境维度」之外的三个环境维度（取值经 tca_utils 分桶单点，避免重复实现）
ENV_DIMS: tuple[str, ...] = ("time_of_day", "liquidity_adv20", "volatility")

#: 分布失衡阈值（总变差距离）：两两分布差异超过该值即判该维度不可比。
#: 0.2 = 至少 20% 的概率质量不重叠；属经验阈值，可由调用方覆盖。
DEFAULT_IMBALANCE_TVD: float = 0.2

#: 单组最小样本量（低于此值不进入比较）
DEFAULT_MIN_GROUP_SAMPLE: int = 10

UNKNOWN_LABEL = "unknown"


@dataclass(frozen=True)
class ComparabilityVerdict:
    """可比性判定结果。``comparable=False`` 时**不得**输出任何比较数值。"""

    comparable: bool
    reasons: tuple[str, ...]
    unmet_dimensions: tuple[str, ...]
    group_sizes: Mapping[str, int]
    imbalance: Mapping[str, float]
    common_strata: int

    def to_payload(self) -> dict[str, Any]:
        """供 API / UI 消费的结构化判定（不可比原因必须可见）。"""
        return {
            "comparable": self.comparable,
            "reasons": list(self.reasons),
            "unmet_dimensions": list(self.unmet_dimensions),
            "group_sizes": dict(self.group_sizes),
            "imbalance": dict(self.imbalance),
            "common_strata": self.common_strata,
        }


def dimension_label(route: Any, dimension: str, env: Optional[Any] = None) -> str:
    """路由在某分层维度上的取值标签（缺失一律取 ``unknown``）。

    环境与资产类别维度**复用 `tca_utils` 的分桶单点**，不在此重写降级逻辑 ——
    否则「同口径两处实现」会再次分叉（`docs/report-tca-known-limitations.md:68-69`）。
    """
    if dimension == "Exchange":
        return str(getattr(route, "Exchange", None) or UNKNOWN_LABEL)
    if dimension == "asset_class":
        return cohort_key_and_label(route, "asset_class", env)[0]
    if dimension in ENV_DIMS:
        return cohort_key_and_label(route, dimension, env)[0]
    return UNKNOWN_LABEL


def _distribution(labels: Sequence[str]) -> dict[str, float]:
    """标签序列 → 归一化分布（空序列 → 空分布）。"""
    total = len(labels)
    if not total:
        return {}
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return {label: count / total for label, count in counts.items()}


def total_variation_distance(
    left: Mapping[str, float], right: Mapping[str, float],
) -> float:
    """两组分布的**总变差距离**（0 = 完全同分布，1 = 完全不重叠）。"""
    keys = set(left) | set(right)
    return 0.5 * sum(abs(left.get(k, 0.0) - right.get(k, 0.0)) for k in keys)


def _labels_by_group(
    groups: Mapping[str, Sequence[Any]],
    env_by_route: Optional[Mapping[tuple[str, str, str], Any]],
    dimensions: Sequence[str],
) -> dict[str, list[dict[str, str]]]:
    """每组路由 → 每条的「维度 → 标签」映射。"""
    result: dict[str, list[dict[str, str]]] = {}
    for name, routes in groups.items():
        rows: list[dict[str, str]] = []
        for route in routes:
            env = None
            if env_by_route:
                env = env_by_route.get(env_route_key(
                    getattr(route, "OrderId", None),
                    getattr(route, "RouteId", None),
                    getattr(route, "order_as_of_date", None),
                ))
            rows.append({dim: dimension_label(route, dim, env) for dim in dimensions})
        result[name] = rows
    return result


def _worst_pairwise_tvd(distributions: Sequence[Mapping[str, float]]) -> float:
    """多组分布的最差两两 TVD（两组时即该对的 TVD）。"""
    worst = 0.0
    for i in range(len(distributions)):
        for j in range(i + 1, len(distributions)):
            worst = max(worst, total_variation_distance(distributions[i], distributions[j]))
    return worst


def _common_strata_count(
    labeled: Mapping[str, list[dict[str, str]]], dimensions: Sequence[str],
) -> int:
    """各组**共有**的完整分层组合数（组数 < 2 时为 0）。

    共有层是「精确分层匹配」的可用样本域：只有当共有层足够大，层内比较才有意义。
    """
    if len(labeled) < 2:
        return 0
    common: Optional[set[tuple[str, ...]]] = None
    for rows in labeled.values():
        keys = {tuple(row[dim] for dim in dimensions) for row in rows}
        common = keys if common is None else (common & keys)
    return len(common or set())


def assess_comparability(
    groups: Mapping[str, Sequence[Any]],
    env_by_route: Optional[Mapping[tuple[str, str, str], Any]] = None,
    *,
    dimensions: Sequence[str] = DEFAULT_STRATA_DIMENSIONS,
    min_group_sample: int = DEFAULT_MIN_GROUP_SAMPLE,
    imbalance_threshold: float = DEFAULT_IMBALANCE_TVD,
) -> ComparabilityVerdict:
    """判定多组样本在给定分层维度上是否可比。

    判定规则（**全部满足**才 ``comparable=True``）：

    1. 每组样本量 ≥ ``min_group_sample``；
    2. 每个分层维度的最差两两 TVD ≤ ``imbalance_threshold``。

    不满足时返回原因与具体失衡维度，**由调用方负责不输出比较数值**（DP-3-2）。
    """
    dimensions = tuple(dimensions)
    labeled = _labels_by_group(groups, env_by_route, dimensions)
    group_sizes = {name: len(rows) for name, rows in labeled.items()}

    reasons: list[str] = []
    undersized = [name for name, size in group_sizes.items() if size < min_group_sample]
    if undersized:
        reasons.append(
            f"组样本不足 {min_group_sample} 条：{', '.join(sorted(undersized))}"
        )

    imbalance: dict[str, float] = {}
    for dim in dimensions:
        distributions = [_distribution([row[dim] for row in rows])
                         for rows in labeled.values()]
        imbalance[dim] = round(_worst_pairwise_tvd(distributions), 4)

    unmet = tuple(dim for dim, tvd in imbalance.items() if tvd > imbalance_threshold)
    if unmet:
        reasons.append("分层分布失衡（总变差距离超阈值）：" + ", ".join(unmet))

    return ComparabilityVerdict(
        comparable=not reasons,
        reasons=tuple(reasons),
        unmet_dimensions=unmet,
        group_sizes=group_sizes,
        imbalance=imbalance,
        common_strata=_common_strata_count(labeled, dimensions),
    )

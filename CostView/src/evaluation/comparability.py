"""分层键与可比性披露 —— 026 建立、**027 改造**。

## 026 的错与 027 的改法

026 把 B3 的要求实现成了**门禁**（`assess_comparability`）：

> 按股票流动性、订单规模/ADV、交易方向、时段、波动状态、紧迫度和执行算法分层。
> **只有在这些维度足够相似时，跨经纪商或跨策略比较才具有解释力。**

026 的读法是「不够相似 → 不输出比较数值」。真实数据实测结果是**恒为拒绝**：

    imbalance = {"Exchange": 1.0, "time_of_day": 0.9286, "liquidity_adv20": 0.6923}
    common_strata = 0

券商的成交本就横跨多个交易市场 —— 要求两个券商的市场分布一致，在业务上永远不成立；
而把 5 个维度**交叉**后要求共同分层，层只会越来越空。

027 改为**控制**：本模块负责

1. 定义**控制维度**与分层键（`STRATA_DIMENSIONS` / `strata_key_of`）；
2. **描述**样本在控制维度上的构成与失衡（`describe_strata`）—— 作为报告置信度的输入，
   **不阻断任何结论**。

层内比较与加权合并见 `stratified.py`；「不可比就拒绝」的语义已整体移除。

## 控制维度的选择

`Exchange` + 环境三维（`time_of_day` / `liquidity_adv20` / `volatility`）。
**不含 `asset_class`**：它与 `Exchange` 高度共线（同一市场通常同一资产类别），
纳入只会让层更稀疏而几乎不增加控制力。

环境三维的取值一律经 `tca_utils` 的分桶单点（017 / 026 约定），不在此重写降级逻辑。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from ..monitoring.env_context import env_route_key
from ..tca_utils import cohort_key_and_label

#: 控制维度（顺序即报告中展示顺序）：层内比较时这些维度取值一致
STRATA_DIMENSIONS: tuple[str, ...] = (
    "Exchange", "time_of_day", "liquidity_adv20", "volatility",
)

#: 环境维度（取值经 `tca_utils` 分桶单点）
ENV_DIMS: tuple[str, ...] = ("time_of_day", "liquidity_adv20", "volatility")

#: 失衡**提示**阈值（总变差距离）：超过则报告标注「构成差异较大」。
#: 027 起仅为描述性提示（026 中同样的数值曾用于**拒绝**输出）。
IMBALANCE_ALERT_TVD: float = 0.2

#: 单组最小样本量（低于此值的组在报告中标注为样本不足，但不从报告中消失）
DEFAULT_MIN_GROUP_SAMPLE: int = 10

UNKNOWN_LABEL = "unknown"

StrataKey = tuple[str, ...]
KeyOf = Callable[[Any], StrataKey]


def dimension_label(route: Any, dimension: str, env: Optional[Any] = None) -> str:
    """路由在某维度上的取值标签（缺失一律取 ``unknown``）。

    环境与资产类别维度**复用 `tca_utils` 的分桶单点**，不在此重写 ——
    否则「同口径两处实现」会再次分叉（`docs/report-tca-known-limitations.md:68-69`）。
    """
    if dimension == "Exchange":
        return str(getattr(route, "Exchange", None) or UNKNOWN_LABEL)
    if dimension == "asset_class":
        return cohort_key_and_label(route, "asset_class", env)[0]
    if dimension in ENV_DIMS:
        return cohort_key_and_label(route, dimension, env)[0]
    return UNKNOWN_LABEL


def _env_of(route: Any, env_by_route: Optional[Mapping[StrataKey, Any]]) -> Optional[Any]:
    if not env_by_route:
        return None
    return env_by_route.get(env_route_key(
        getattr(route, "OrderId", None),
        getattr(route, "RouteId", None),
        getattr(route, "order_as_of_date", None),
    ))


def strata_key_of(
    env_by_route: Optional[Mapping[StrataKey, Any]] = None,
    dimensions: Sequence[str] = STRATA_DIMENSIONS,
) -> KeyOf:
    """返回「路由 → 分层键」函数（供 `stratified.stratified_difference` 直接消费）。

    闭包捕获 ``env_by_route``，避免调用方每层反复传环境映射。
    """
    dims = tuple(dimensions)

    def _key(route: Any) -> StrataKey:
        env = _env_of(route, env_by_route)
        return tuple(dimension_label(route, dim, env) for dim in dims)

    return _key


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
    """两组分布的**总变差距离**（0 = 同分布，1 = 完全不重叠）。

    027 起仅作**描述性指标**（构成差异提示），不再是阻断条件。
    """
    keys = set(left) | set(right)
    return 0.5 * sum(abs(left.get(k, 0.0) - right.get(k, 0.0)) for k in keys)


def worst_pairwise_tvd(distributions: Sequence[Mapping[str, float]]) -> float:
    """多组分布的最差两两 TVD（两组时即该对的 TVD）。"""
    worst = 0.0
    for i in range(len(distributions)):
        for j in range(i + 1, len(distributions)):
            worst = max(worst, total_variation_distance(distributions[i], distributions[j]))
    return worst


def describe_strata(
    groups: Mapping[str, Sequence[Any]],
    env_by_route: Optional[Mapping[StrataKey, Any]] = None,
    *,
    dimensions: Sequence[str] = STRATA_DIMENSIONS,
    alert_threshold: float = IMBALANCE_ALERT_TVD,
) -> dict[str, Any]:
    """**描述**各分组在控制维度上的构成与失衡（不判定可否比较）。

    返回：

    - ``group_sizes``：各组样本量；
    - ``imbalance``：每个控制维度的最差两两 TVD（> ``alert_threshold`` 计入 ``alerts``）；
    - ``cross_strata``：控制维度**交叉**后的层数分布（描述稀疏程度，不做门禁）；
    - ``alerts``：需要读者注意的构成差异条目（人类可读）。
    """
    dims = tuple(dimensions)
    labeled: dict[str, list[dict[str, str]]] = {}
    for name, routes in groups.items():
        labeled[name] = [
            {dim: dimension_label(route, dim, _env_of(route, env_by_route)) for dim in dims}
            for route in routes
        ]

    group_sizes = {name: len(rows) for name, rows in labeled.items()}

    imbalance: dict[str, float] = {}
    for dim in dims:
        distributions = [_distribution([row[dim] for row in rows])
                         for rows in labeled.values()]
        imbalance[dim] = round(worst_pairwise_tvd(distributions), 4)

    cross: dict[str, int] = {}
    for name, rows in labeled.items():
        for row in rows:
            key = " | ".join(row[dim] for dim in dims)
            cross[key] = cross.get(key, 0) + 1

    alerts = [
        f"「{dim}」构成差异较大（最差两两总变差 {value:.2f}）—— 报告已按该维度分层控制，"
        f"层内比较不受此影响，但层覆盖率可能下降"
        for dim, value in imbalance.items()
        if value > alert_threshold
    ]

    return {
        "dimensions": list(dims),
        "group_sizes": group_sizes,
        "imbalance": imbalance,
        "cross_strata": {
            "count": len(cross),
            "largest": max(cross.values()) if cross else 0,
        },
        "alerts": alerts,
    }


__all__ = [
    "DEFAULT_MIN_GROUP_SAMPLE",
    "ENV_DIMS",
    "IMBALANCE_ALERT_TVD",
    "STRATA_DIMENSIONS",
    "UNKNOWN_LABEL",
    "describe_strata",
    "dimension_label",
    "strata_key_of",
    "total_variation_distance",
    "worst_pairwise_tvd",
]

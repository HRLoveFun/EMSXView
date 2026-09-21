"""综合评估报告编排 —— 027。

输入 = **时间范围 + 作用域**；输出 = 覆盖全部比较维度与六项内容领域的综合评估。

## 与 026 形态的差别（来自用户反馈与真实数据实测）

| 026（错） | 027 |
|---|---|
| 用户选 1 个比较维度 | 遍历 `SCORECARD_COHORTS` **全部维度** |
| 用户选 1 个基准 | `arrival` / `vwap` / `close` / `is` **并列**（检验固定在主基准） |
| 用户选 1 种检验方法 | t / KS / χ² **并列** |
| 不可比 → 拒绝输出 | **层内比较** + 加权合并 + 覆盖率 / 置信度披露 |

## 比较形态：每组 vs 其余（层内）

报告读者的真实问题是「谁偏离常态、偏多少、可信吗」，不是「枚举所有对」——
26 个券商的 C(26,2) = 325 对检验，对报告没有可读性。因此每个分组做**一次**比较：
该组 vs 其余全部（在共同层内、按层样本量加权），并披露层覆盖率与置信度。

## 符号约定

主基准 `arrival` 为**成本**语义（越大越差），`best`/`worst` 与方向判定依此；
其余基准（`vwap` / `close` / `is`）仅作水平并列展示，不参与方向判定 ——
它们的符号约定不同（详见 `report_spec`），强行统一方向会产生误读。
"""

from __future__ import annotations

import datetime as _dt
import math
import statistics
from typing import Any, Callable, Mapping, Optional, Sequence

from platform_data.contracts import SCORECARD_COHORTS

from ..monitoring.env_context import env_coverage, env_route_key
from ..tca_utils import cohort_key_and_label
from .comparability import (
    DEFAULT_MIN_GROUP_SAMPLE,
    STRATA_DIMENSIONS,
    describe_strata,
    dimension_label,
    strata_key_of,
)
from .governance import evaluation_metadata
from .power import minimum_detectable_effect
from .stats_tests import METHODS, adjust_pvalues, compare_groups, mean_difference_ci
from .stratified import MIN_STRATUM_SAMPLE, stratified_difference

#: 基准名 → 成本指标列。全部并列呈现；**检验固定用 `PRIMARY_BENCHMARK`**。
BENCHMARK_METRICS: dict[str, str] = {
    "arrival": "arrival_cost_bps",
    "vwap": "pnl_vwap",
    "close": "close_cost_bps",
    "is": "wagner_is_bps",
}

#: 主基准（成本语义，用于方向判定与检验）；**不作为用户可选项暴露**。
PRIMARY_BENCHMARK: str = "arrival"

#: 报告中每个维度的最小样本门槛（低于此值标注样本不足，但不从报告消失）
DEFAULT_REPORT_MIN_SAMPLE: int = 5

#: 报告中列出的分组上限（超出按样本量取前 N，并披露截断）
DEFAULT_MAX_GROUPS: int = 20

#: 报告场景的 bootstrap 重采样次数。可信区间与检验方法无关、每对样本只算一次，
#: 故次数按「报告可接受耗时」取值，而非统计研究的常用 1000 —— 真实库实测差异达分钟级。
DEFAULT_REPORT_BOOTSTRAP: int = 200


def _metric_values(routes: Sequence[Any], metric: str) -> list[Optional[float]]:
    return [getattr(route, metric, None) for route in routes]


def _metric_getter(metric: str) -> Callable[[Any], Optional[float]]:
    def _get(route: Any) -> Optional[float]:
        value = getattr(route, metric, None)
        return None if value is None else float(value)

    return _get


def _env_of_route(
    route: Any, env_by_route: Optional[Mapping[tuple[str, str, str], Any]],
) -> Any:
    """路由 → 环境上下文（键与 `env_context.env_route_key` 同源）。"""
    if not env_by_route:
        return None
    return env_by_route.get(env_route_key(
        getattr(route, "OrderId", None),
        getattr(route, "RouteId", None),
        getattr(route, "order_as_of_date", None),
    ))


def _finite(values: Sequence[Optional[float]]) -> list[float]:
    return [
        float(value) for value in values
        if value is not None and math.isfinite(float(value))
    ]


def _percentile(sorted_values: Sequence[float], fraction: float) -> Optional[float]:
    """线性插值分位数（不引额外依赖；`fraction` ∈ [0, 1]）。"""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = int(math.floor(position))
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = position - lower
    return sorted_values[lower] * (1 - frac) + sorted_values[upper] * frac


def describe_values(values: Sequence[Optional[float]]) -> dict[str, Any]:
    """一组取值的水平描述（均值 / 中位数 / 尾部 / 条件尾部均值 / 样本量）。

    `cvar` 取**最差 5%** 的条件均值（成本越大越差的语义下即尾部风险）。
    """
    finite = _finite(values)
    if not finite:
        return {"n": 0, "mean": None, "median": None, "p95": None, "cvar": None, "stddev": None}
    ordered = sorted(finite)
    cut = max(1, int(math.ceil(len(ordered) * 0.05)))
    return {
        "n": len(ordered),
        "mean": round(statistics.fmean(ordered), 4),
        "median": round(statistics.median(ordered), 4),
        "p95": round(_percentile(ordered, 0.95) or 0.0, 4),
        "cvar": round(statistics.fmean(ordered[-cut:]), 4),
        "stddev": round(statistics.pstdev(ordered), 4) if len(ordered) > 1 else 0.0,
    }


def _period_key(value: Any, granularity: str) -> str:
    """``YYYYMMDD`` → 期间键（与 `report_measure` 的日 / ISO 周 / 月口径一致）。"""
    text = str(value or "")
    if granularity == "day" or len(text) != 8:
        return text
    iso = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if granularity == "month":
        return iso[:7]
    try:
        year, week, _ = _dt.date.fromisoformat(iso).isocalendar()
    except ValueError:
        return iso
    return f"{year}-W{week:02d}"


def _group_by_dimension(
    routes: Sequence[Any], dimension: str,
    env_by_route: Optional[Mapping[tuple[str, str, str], Any]],
) -> dict[str, list[Any]]:
    """按维度分组（分组口径复用 `tca_utils.cohort_key_and_label` 单点）。"""
    grouped: dict[str, list[Any]] = {}
    for route in routes:
        env = _env_of_route(route, env_by_route)
        _, label = cohort_key_and_label(route, dimension, env)
        grouped.setdefault(label, []).append(route)
    return grouped


def evaluate_dimension(
    routes: Sequence[Any],
    dimension: str,
    env_by_route: Optional[Mapping[tuple[str, str, str], Any]] = None,
    *,
    min_group_sample: int = DEFAULT_REPORT_MIN_SAMPLE,
    max_groups: int = DEFAULT_MAX_GROUPS,
    correction: str = "bh",
    alpha: float = 0.05,
    bootstrap: int = DEFAULT_REPORT_BOOTSTRAP,
) -> dict[str, Any]:
    """单个比较维度的评估：各组 vs 其余（层内）+ 多方法检验 + 置信度。

    不返回「不可比」这种终止态 —— 层次不足时由 `stratified` 退化为整体比较并说明原因，
    结论照出，**可信度以 `confidence` 与 `coverage` 显式披露**。
    """
    grouped = _group_by_dimension(routes, dimension, env_by_route)
    # **排除当前分组维度**：控制变量若与被解释的分组维度相同，层内该维度取值恒定，
    # 分层会退化成「只有 1 层」（实测：time_of_day / liquidity_adv20 / volatility
    # 三个维度曾全部 `stratified=False`）。分层键必须与分组维度正交。
    control_dims = tuple(dim for dim in STRATA_DIMENSIONS if dim != dimension)
    key_of = strata_key_of(env_by_route, control_dims)
    metric = BENCHMARK_METRICS[PRIMARY_BENCHMARK]

    sizes = {label: len(group) for label, group in grouped.items()}
    ranked = sorted(grouped, key=lambda label: (-sizes[label], label))
    truncated = len(ranked) > max_groups
    selected = ranked[:max_groups]

    rows: list[dict[str, Any]] = []
    raw_pvalues: dict[str, list[float]] = {method: [] for method in METHODS}
    for label in selected:
        own = grouped[label]
        others = [r for other in selected if other != label for r in grouped[other]]
        stratified = stratified_difference(
            own, others,
            value_of=_metric_getter(metric), key_of=key_of,
            min_stratum_sample=MIN_STRATUM_SAMPLE,
        )
        tests: dict[str, Any] = {}
        for method in METHODS:
            outcome = compare_groups(
                _metric_values(own, metric), _metric_values(others, metric),
                method=method, alpha=alpha, with_ci=False,
            )
            tests[method] = outcome.to_payload()
            raw_pvalues[method].append(float(outcome.p_value))
        # 可信区间只依赖数据、不依赖检验方法：同一对样本只算一次。
        # （026 曾在每个方法内各算一次 bootstrap，实测把最长耗时放大 3 倍）
        ci_low, ci_high = mean_difference_ci(
            _finite(_metric_values(own, metric)),
            _finite(_metric_values(others, metric)),
            alpha=alpha, bootstrap=bootstrap,
        )

        rows.append({
            "label": label,
            "sample_size": sizes[label],
            "undersized": sizes[label] < min_group_sample,
            "benchmarks": {
                name: describe_values(_metric_values(own, column))
                for name, column in BENCHMARK_METRICS.items()
            },
            "vs_others": stratified.to_payload(),
            "ci": [ci_low, ci_high],
            "tests": tests,
        })

    for method, values in raw_pvalues.items():
        for row, adjusted in zip(rows, adjust_pvalues(values, method=correction)):
            row["tests"][method]["p_value_adjusted"] = adjusted

    scored = [row for row in rows if row["vs_others"]["difference"] is not None]
    highlights: dict[str, Any] = {"alerts": []}
    if scored:
        best = min(scored, key=lambda row: row["vs_others"]["difference"])
        worst = max(scored, key=lambda row: row["vs_others"]["difference"])
        highlights["best"] = {"label": best["label"], "difference": best["vs_others"]["difference"]}
        highlights["worst"] = {"label": worst["label"], "difference": worst["vs_others"]["difference"]}
    low_confidence = [row["label"] for row in rows if row["vs_others"]["confidence"] == "low"]
    if low_confidence:
        highlights["alerts"].append(
            f"{len(low_confidence)} 个分组置信度偏低（层覆盖不足或样本量小）："
            + ", ".join(low_confidence[:5])
        )
    # 功效指引：回答「当前样本量能检出多大差异」，而非只给「样本不足」判词
    smallest = min((row["vs_others"]["n_left"] for row in rows), default=0)
    spread_values = _finite(_metric_values(routes, metric))
    # 该指标在该维度上可能整列缺失（真实库实测：部分基准覆盖不全）→ 不可直接 pstdev
    spread = statistics.pstdev(spread_values) if len(spread_values) > 1 else 0.0
    if smallest > 1 and spread > 0:
        highlights["minimum_detectable_effect"] = round(
            minimum_detectable_effect(smallest, alpha=alpha, stddev=spread), 4,
        )
    if truncated:
        highlights["alerts"].append(
            f"分组数 {len(ranked)} 超出报告上限 {max_groups}，已按样本量取前 {max_groups} 组"
        )
    if not _finite(_metric_values(routes, metric)):
        # 主基准整列缺失时必须显式披露：否则读者会把「无差异数值」读成「无差异」
        highlights["alerts"].append(
            f"主基准指标 {metric} 在本次范围内整列缺失，各组差异不可计算"
            "（其余基准的水平仍照常给出）"
        )

    return {
        "dimension": dimension,
        "primary_benchmark": PRIMARY_BENCHMARK,
        "primary_metric": metric,
        "group_count": len(grouped),
        "groups_reported": len(rows),
        "truncated": truncated,
        "rows": rows,
        "stratification": describe_strata(grouped, env_by_route, dimensions=STRATA_DIMENSIONS),
        "highlights": highlights,
    }


def _trend_section(routes: Sequence[Any], granularity: str) -> dict[str, Any]:
    """时间趋势与稳定性：按期间的成本水平 / 波动 / 样本量（复用 026 粒度口径）。"""
    buckets: dict[str, list[Any]] = {}
    for route in routes:
        key = _period_key(getattr(route, "order_as_of_date", None), granularity)
        buckets.setdefault(key, []).append(route)
    metric = BENCHMARK_METRICS[PRIMARY_BENCHMARK]
    series = [
        {"period": key, **describe_values(_metric_values(buckets[key], metric))}
        for key in sorted(buckets)
    ]
    means = [item["mean"] for item in series if item["mean"] is not None]
    return {
        "granularity": granularity,
        "periods": len(series),
        "series": series,
        "stability": {
            "mean_of_means": round(statistics.fmean(means), 4) if means else None,
            "stddev_of_means": round(statistics.pstdev(means), 4) if len(means) > 1 else 0.0,
            "best_period": min(series, key=lambda item: item["mean"])["period"] if means else None,
            "worst_period": max(series, key=lambda item: item["mean"])["period"] if means else None,
        },
    }


def _risk_section(routes: Sequence[Any]) -> dict[str, Any]:
    """风险与尾部：各基准的成本波动、CVaR、p95 与尾部占比。"""
    payload: dict[str, Any] = {}
    for name, column in BENCHMARK_METRICS.items():
        values = _finite(_metric_values(routes, column))
        stats = describe_values(values)
        if not values:
            payload[name] = {**stats, "tail_share": None}
            continue
        ordered = sorted(values)
        p95 = _percentile(ordered, 0.95) or 0.0
        tail_share = sum(1 for value in ordered if value >= p95) / len(ordered)
        payload[name] = {**stats, "tail_share": round(tail_share, 4)}
    return payload


def _market_section(
    routes: Sequence[Any],
    env_by_route: Optional[Mapping[tuple[str, str, str], Any]],
) -> dict[str, Any]:
    """市场维度：各交易市场的执行质量水平（分市场的横向对比入口）。"""
    # `Exchange` **不是** `SCORECARD_COHORTS` 成员，不能走 `cohort_key_and_label`
    # （那会把全部路由落进同一个标签，实测只得到 1 组）；此处用 `dimension_label`
    # 的单点取值 —— 两者的交易所口径因此保持同一实现。
    grouped: dict[str, list[Any]] = {}
    for route in routes:
        grouped.setdefault(
            dimension_label(route, "Exchange", _env_of_route(route, env_by_route)), [],
        ).append(route)
    metric = BENCHMARK_METRICS[PRIMARY_BENCHMARK]
    rows = [
        {"exchange": label, "sample_size": len(group),
         **describe_values(_metric_values(group, metric))}
        for label, group in sorted(grouped.items(), key=lambda item: -len(item[1]))
    ]
    return {"primary_benchmark": PRIMARY_BENCHMARK, "rows": rows}


def build_evaluation_report(
    routes: Sequence[Any],
    env_by_route: Optional[Mapping[tuple[str, str, str], Any]] = None,
    *,
    start_date: str = "",
    end_date: str = "",
    granularity: str = "day",
    dimensions: Sequence[str] = SCORECARD_COHORTS,
    min_group_sample: int = DEFAULT_REPORT_MIN_SAMPLE,
    correction: str = "bh",
    alpha: float = 0.05,
    bootstrap: int = DEFAULT_REPORT_BOOTSTRAP,
) -> dict[str, Any]:
    """组装综合评估报告（单一数据源，供 Report 内嵌章节与独立 Tab 共用）。"""
    dims = tuple(dimensions)
    sections = {
        "credibility": {
            "total_routes": len(routes),
            "env_coverage": env_coverage(list(routes), env_by_route or {}) if env_by_route else {},
            "correction": correction,
            "alpha": alpha,
            "min_group_sample": min_group_sample,
            "stratified": True,
            "stratification_note": (
                "组间比较在控制维度（" + " / ".join(STRATA_DIMENSIONS) + "）的**共同层内**进行，"
                "层内这些维度取值一致，构成差异被剔除；各层效应按样本量加权合并。"
            ),
        },
        "dimensions": [
            evaluate_dimension(
                routes, dim, env_by_route,
                min_group_sample=min_group_sample, correction=correction, alpha=alpha,
            )
            for dim in dims
        ],
        "trend": _trend_section(routes, granularity),
        "risk": _risk_section(routes),
        "market": _market_section(routes, env_by_route),
    }
    return {
        "period": {"start_date": start_date, "end_date": end_date, "granularity": granularity},
        "benchmarks": list(BENCHMARK_METRICS),
        "primary_benchmark": PRIMARY_BENCHMARK,
        "dimensions_covered": list(dims),
        "sections": sections,
        "governance": evaluation_metadata(
            benchmark=PRIMARY_BENCHMARK,
            spec_version=_spec_version(),
            data_range=(start_date, end_date),
            scope={"dimensions": list(dims), "granularity": granularity},
            sample_sizes={"total": len(routes)},
        ),
    }


def _spec_version() -> str:
    """评估口径版本（与 `report_spec.SPEC_VERSION` 同源，避免两处漂移）。"""
    from ..monitoring.report_spec import SPEC_VERSION

    return SPEC_VERSION


__all__ = [
    "BENCHMARK_METRICS",
    "DEFAULT_MAX_GROUPS",
    "DEFAULT_REPORT_BOOTSTRAP",
    "DEFAULT_REPORT_MIN_SAMPLE",
    "PRIMARY_BENCHMARK",
    "build_evaluation_report",
    "describe_values",
    "evaluate_dimension",
]

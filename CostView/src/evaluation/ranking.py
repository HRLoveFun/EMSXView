"""聚类推断与收缩排名（057 DL-23/216）。

同日路由共享市场冲击，iid 推断会低估标准误；小样本单元的名次不稳定。本模块：

1. 按**交易日聚类**的稳健标准误 + 按交易日**块 bootstrap**；
2. **DerSimonian–Laird** 随机效应收缩（numpy）与分级回退；
3. 后验 **P(top-k)** 模拟与**不可区分集合**；
4. 只使用**正式**路由（`is_provisional` / 非 formal source 排除）。

输出供 DL-24 快照与 DL-27 轮换候选消费。纯计算，无 IO。
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from typing import Any, Optional, Sequence

import numpy as np

#: 单元最小样本（低于此值标 low_sample，由 DL 收缩向父层靠拢）
MIN_UNIT_SAMPLE = 10

#: 默认 top-k、bootstrap 次数与固定种子（可复现）
DEFAULT_TOP_K = 3
DEFAULT_BOOTSTRAP = 1000
DEFAULT_SIMULATIONS = 2000
DEFAULT_SEED = 20261125

#: 正式数据来源（空串 = 未标注，TCA 日汇总默认正式）
FORMAL_SOURCES = {"", "formal", "daily", "tca"}


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def is_formal_route(route: Any) -> bool:
    """正式数据判定：显式 provisional 或非 formal source 排除。"""
    if bool(getattr(route, "is_provisional", False)):
        return False
    source = str(getattr(route, "source", "") or "").strip().lower()
    return source in FORMAL_SOURCES


def _day_of(route: Any) -> str:
    return str(getattr(route, "order_as_of_date", "") or "")


def _broker_of(route: Any) -> str:
    return str(getattr(route, "Broker", None) or "Unknown")


def _metric_of(route: Any, metric: str) -> Optional[float]:
    return _finite(getattr(route, metric, None))


def cluster_robust_mean(
    values: Sequence[float], clusters: Sequence[str],
) -> tuple[Optional[float], Optional[float], bool]:
    """按交易日聚类的均值与标准误（返回 `(mean, se, clustered)`）。

    G<2 时回退 iid 标准误并返回 `clustered=False`。
    """
    pairs = [
        (float(value), str(cluster))
        for value, cluster in zip(values, clusters)
        if _finite(value) is not None
    ]
    n = len(pairs)
    if n == 0:
        return None, None, False
    mean = sum(value for value, _ in pairs) / n
    groups: dict[str, list[float]] = defaultdict(list)
    for value, cluster in pairs:
        groups[cluster].append(value)
    g = len(groups)
    if g < 2:
        if n < 2:
            return mean, None, False
        variance = sum((value - mean) ** 2 for value, _ in pairs) / (n - 1)
        return mean, math.sqrt(variance / n), False
    score_sum = sum(
        (sum(value - mean for value in members)) ** 2
        for members in groups.values()
    )
    variance = (g / (g - 1)) * score_sum / (n * n)
    return mean, math.sqrt(max(variance, 0.0)), True


def block_bootstrap_ci(
    values: Sequence[float],
    clusters: Sequence[str],
    *,
    n_boot: int = DEFAULT_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = DEFAULT_SEED,
) -> tuple[Optional[float], Optional[float]]:
    """按交易日整块有放回重采样的均值百分位区间（固定 seed）。"""
    groups: dict[str, list[float]] = defaultdict(list)
    for value, cluster in zip(values, clusters):
        number = _finite(value)
        if number is not None:
            groups[str(cluster)].append(number)
    blocks = list(groups.values())
    if len(blocks) < 2:
        return None, None
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(max(1, int(n_boot))):
        sample: list[float] = []
        for _ in blocks:
            sample.extend(blocks[rng.randrange(len(blocks))])
        if sample:
            means.append(sum(sample) / len(sample))
    if not means:
        return None, None
    means.sort()
    lower = means[min(len(means) - 1, int(alpha / 2 * (len(means) - 1)))]
    upper = means[min(len(means) - 1, int((1 - alpha / 2) * (len(means) - 1)))]
    return lower, upper


def dersimonian_laird(
    estimates: Sequence[Optional[float]], variances: Sequence[Optional[float]],
) -> dict[str, Any]:
    """随机效应合并（DerSimonian–Laird）；返回 mu/var/tau2/k。"""
    pairs = [
        (float(y), float(v))
        for y, v in zip(estimates, variances)
        if _finite(y) is not None and _finite(v) is not None and float(v) > 0
    ]
    if not pairs:
        return {"mu": None, "var": None, "tau2": None, "k": 0}
    if len(pairs) == 1:
        return {"mu": pairs[0][0], "var": pairs[0][1], "tau2": 0.0, "k": 1}

    weights = [1.0 / variance for _, variance in pairs]
    estimates_only = [estimate for estimate, _ in pairs]
    total_weight = sum(weights)
    fixed_mean = sum(w * y for w, y in zip(weights, estimates_only)) / total_weight
    q_stat = sum(w * (y - fixed_mean) ** 2 for w, y in zip(weights, estimates_only))
    dof = len(pairs) - 1
    c_const = total_weight - sum(w * w for w in weights) / total_weight
    tau2 = max(0.0, (q_stat - dof) / c_const) if c_const > 0 else 0.0
    random_weights = [1.0 / (variance + tau2) for _, variance in pairs]
    total_random = sum(random_weights)
    mu = sum(w * y for w, y in zip(random_weights, estimates_only)) / total_random
    return {"mu": mu, "var": 1.0 / total_random, "tau2": tau2, "k": len(pairs)}


def shrink_estimates(units: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """经验贝叶斯后验均值/方差；tau²=0 时退化为完全合并。"""
    pooled = dersimonian_laird(
        [unit.get("mean") for unit in units],
        [unit.get("se") ** 2 if unit.get("se") is not None else None for unit in units],
    )
    tau2 = pooled.get("tau2") or 0.0
    mu = pooled.get("mu")
    outlined: list[dict[str, Any]] = []
    for unit in units:
        estimate = unit.get("mean")
        se = unit.get("se")
        if mu is None or estimate is None:
            posterior_mean, posterior_sd = estimate, None
        elif tau2 <= 0 or se is None or se <= 0:
            posterior_mean = mu
            posterior_sd = math.sqrt(tau2) if tau2 > 0 else 0.0
        else:
            precision = 1.0 / (se * se) + 1.0 / tau2
            posterior_mean = ((estimate / (se * se)) + (mu / tau2)) / precision
            posterior_sd = math.sqrt(1.0 / precision)
        item = dict(unit)
        item["posterior_mean"] = posterior_mean
        item["posterior_sd"] = posterior_sd
        if posterior_mean is not None and posterior_sd is not None:
            item["posterior_ci_low"] = posterior_mean - 1.96 * posterior_sd
            item["posterior_ci_high"] = posterior_mean + 1.96 * posterior_sd
        else:
            item["posterior_ci_low"] = None
            item["posterior_ci_high"] = None
        outlined.append(item)
    return outlined, pooled


def p_top_k(
    units: Sequence[dict[str, Any]],
    *,
    top_k: int = DEFAULT_TOP_K,
    simulations: int = DEFAULT_SIMULATIONS,
    seed: int = DEFAULT_SEED,
) -> list[float]:
    """后验抽样下各单元进入前 k 的概率（成本越低越好）。"""
    if not units:
        return []
    rng = np.random.default_rng(seed)
    draws = np.empty((len(units), max(1, int(simulations))), dtype=float)
    for index, unit in enumerate(units):
        mean = unit.get("posterior_mean")
        sd = unit.get("posterior_sd")
        if mean is None:
            draws[index, :] = np.inf
        elif sd is None or sd <= 0:
            draws[index, :] = float(mean)
        else:
            draws[index, :] = rng.normal(float(mean), float(sd), size=draws.shape[1])
    k = max(1, min(int(top_k), len(units)))
    order = np.argsort(draws, axis=0)
    counts = np.zeros(len(units), dtype=int)
    for simulation in range(draws.shape[1]):
        counts[order[:k, simulation]] += 1
    return [float(count) / draws.shape[1] for count in counts]


def _overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_low, left_high = left.get("posterior_ci_low"), left.get("posterior_ci_high")
    right_low, right_high = right.get("posterior_ci_low"), right.get("posterior_ci_high")
    if None in (left_low, left_high, right_low, right_high):
        return False
    return not (left_high < right_low or right_high < left_low)


def rank_brokers(
    routes: Sequence[Any],
    *,
    metric: str = "arrival_cost_bps",
    min_unit_sample: int = MIN_UNIT_SAMPLE,
    top_k: int = DEFAULT_TOP_K,
    n_boot: int = DEFAULT_BOOTSTRAP,
    simulations: int = DEFAULT_SIMULATIONS,
    alpha: float = 0.05,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """券商排名 v2：聚类稳健 + DL 收缩 + P(top-k) + 不可区分集合。"""
    formal = [route for route in routes if is_formal_route(route)]
    excluded = len(routes) - len(formal)
    grouped: dict[str, list[Any]] = defaultdict(list)
    for route in formal:
        if _metric_of(route, metric) is not None:
            grouped[_broker_of(route)].append(route)

    units: list[dict[str, Any]] = []
    all_days: set[str] = set()
    for broker, items in grouped.items():
        values = [_metric_of(route, metric) for route in items]
        days = [_day_of(route) for route in items]
        all_days.update(days)
        mean, cluster_se, clustered = cluster_robust_mean(values, days)
        iid_mean, iid_se, _ = cluster_robust_mean(values, [f"obs-{i}" for i in range(len(values))])
        ci_low, ci_high = block_bootstrap_ci(values, days, n_boot=n_boot, alpha=alpha, seed=seed)
        units.append(
            {
                "broker": broker,
                "n": len(values),
                "days": len(set(days)),
                "mean": mean,
                "se": cluster_se,
                "cluster_robust": clustered,
                "iid_se": iid_se,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "low_sample": len(values) < min_unit_sample,
            }
        )

    if not units:
        return {
            "available": False,
            "metric": metric,
            "coverage": {
                "routes": 0,
                "excluded_non_formal": excluded,
                "brokers": 0,
                "days": len(all_days),
            },
            "units": [],
            "indistinguishable": [],
        }

    shrunk, pooled = shrink_estimates(units)
    probabilities = p_top_k(shrunk, top_k=top_k, simulations=simulations, seed=seed)
    for unit, probability in zip(shrunk, probabilities):
        unit["p_top_k"] = round(probability, 4)

    ordered = sorted(
        shrunk,
        key=lambda item: (item.get("posterior_mean") is None, item.get("posterior_mean") or 0.0),
    )
    best = ordered[0] if ordered else None
    indistinguishable = []
    if best is not None:
        indistinguishable = [
            unit["broker"]
            for unit in ordered
            if _overlaps(unit, best) or (unit.get("p_top_k") or 0.0) >= 0.1
        ]

    return {
        "available": True,
        "metric": metric,
        "method": (
            "cluster-robust (trading day) + block bootstrap + "
            "DerSimonian-Laird shrinkage + posterior P(top-k)"
        ),
        "alpha": alpha,
        "top_k": top_k,
        "seed": seed,
        "bootstrap": n_boot,
        "simulations": simulations,
        "coverage": {
            "routes": len(formal),
            "excluded_non_formal": excluded,
            "brokers": len(units),
            "days": len(all_days),
        },
        "pooled": {
            "mean": pooled.get("mu"),
            "tau2": pooled.get("tau2"),
            "k": pooled.get("k"),
        },
        "units": ordered,
        "indistinguishable": indistinguishable,
    }

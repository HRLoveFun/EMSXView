"""订单内配对评估 D1（057 DL-20）。

设计（`Algo_TCA.md:567-651`）：同一订单、同一批窗口内的多券商路由共享相同的
市场与个股冲击；用组内相对成本把共同漂移消掉，只留下券商执行差异。

口径（与 DL-05 `monitoring.data_inventory` 的 D1 候选判定一致）：
- 同 `OrderId` + 同 `order_as_of_date`；
- 窗口内 `route_as_of_time` 跨度 ≤ ``PAIR_MAX_SPREAD_MINUTES``（决策时点，非成交时刻）；
- 不同 ``Broker`` 数 ≥ ``PAIR_MIN_BROKERS``。

相对成本 = 路由成本 − 组内**成交额加权均值**（权重 ``fill × p_avg``）。
检验：Wilcoxon 符号秩 + 符号检验（scipy）；订单固定效应回归用组内去均值 +
券商哑变量 + 份额协变量（numpy OLS，不引入 statsmodels）。
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

import numpy as np
from scipy import stats as _stats

from ..monitoring.env_context import env_route_key

#: D1 配对判定（与 DL-05 同值；单测断言两处一致）
PAIR_MIN_BROKERS = 2
PAIR_MAX_SPREAD_MINUTES = 5.0

#: 券商对检验的最小配对组数（低于此值只出描述统计）
MIN_PAIRS_FOR_TEST = 10

#: 默认成本列（报告主基准 arrival；由报告层显式传入，这里只作默认）
DEFAULT_COST_KEY = "arrival_cost_bps"

#: 相对成本权重（与 report_spec.weight_expression 同源）
COST_WEIGHT_EXPRESSION = "fill * p_avg"


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_minutes(value: Any) -> Optional[float]:
    """``HH:MM:SS`` / ``YYYYMMDD HH:MM:SS`` → 当日分钟数（含秒的小数）。"""
    if not value:
        return None
    text = str(value).strip()
    if len(text) > 8:
        text = text[-8:]
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        hour, minute, second = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    return hour * 60 + minute + second / 60.0


def _route_time(route: Any, env_by_route: Optional[Mapping[Any, Any]]) -> Optional[str]:
    if not env_by_route:
        return None
    key = env_route_key(
        getattr(route, "OrderId", None),
        getattr(route, "RouteId", None),
        getattr(route, "order_as_of_date", None),
    )
    env = env_by_route.get(key)
    return getattr(env, "start_time", None) if env is not None else None


def _broker(route: Any) -> str:
    return str(getattr(route, "Broker", None) or "Unknown")


def _cost(route: Any, cost_key: str) -> Optional[float]:
    return _finite(getattr(route, cost_key, None))


def _weight(route: Any) -> Optional[float]:
    fill = _finite(getattr(route, "fill", None))
    price = _finite(getattr(route, "p_avg", None))
    if fill is None or price is None:
        return None
    weight = fill * price
    return weight if weight > 0 and math.isfinite(weight) else None


def _share(route: Any) -> Optional[float]:
    return _finite(getattr(route, "RouteShares", None))


@dataclass
class PairGroup:
    """同单同窗多券商组。"""

    group_id: str
    order_id: str
    order_as_of_date: str
    window_start: str
    routes: list[Any] = field(default_factory=list)
    brokers: tuple[str, ...] = ()


def pair_groups(
    routes: Sequence[Any],
    env_by_route: Optional[Mapping[Any, Any]],
) -> tuple[list[PairGroup], dict[str, int]]:
    """按「同单 + 同窗 + ≥2 券商」切分配对组。

    返回 ``(groups, excluded)``；``excluded`` 记录 ``no_time`` 路由数与
    ``single_broker`` 订单数，供覆盖率披露。
    """
    orders: dict[tuple[str, str], list[tuple[float, str, Any]]] = defaultdict(list)
    no_time = 0
    for route in routes:
        start = _route_time(route, env_by_route)
        minutes = _parse_minutes(start)
        if minutes is None:
            no_time += 1
            continue
        order_id = str(getattr(route, "OrderId", None) or "")
        date = str(getattr(route, "order_as_of_date", None) or "")
        orders[(order_id, date)].append((minutes, str(start), route))

    groups: list[PairGroup] = []
    single_broker = 0
    for (order_id, date), items in orders.items():
        items.sort(key=lambda item: (item[0], item[1]))
        index = 0
        found = False
        while index < len(items):
            start_min, start_text, first_route = items[index]
            window = [first_route]
            cursor = index + 1
            while cursor < len(items) and items[cursor][0] - start_min <= PAIR_MAX_SPREAD_MINUTES:
                window.append(items[cursor][2])
                cursor += 1
            brokers = tuple(sorted({_broker(route) for route in window}))
            if len(brokers) >= PAIR_MIN_BROKERS:
                found = True
                groups.append(
                    PairGroup(
                        group_id=f"{order_id}|{date}|{start_text}",
                        order_id=order_id,
                        order_as_of_date=date,
                        window_start=start_text,
                        routes=window,
                        brokers=brokers,
                    )
                )
            index = cursor
        if not found:
            single_broker += 1

    return groups, {"no_time": no_time, "single_broker_orders": single_broker}


def relative_costs(
    group: PairGroup,
    cost_key: str = DEFAULT_COST_KEY,
) -> list[dict[str, Any]]:
    """组内相对成本（成本 − 成交额加权均值），每路由一行。

    权重缺失的路由不参与组均值；若组内无有效权重，返回空列表（调用方披露）。
    """
    weighted: list[tuple[Any, float, float]] = []
    total_weight = 0.0
    total_value = 0.0
    for route in group.routes:
        cost = _cost(route, cost_key)
        weight = _weight(route)
        if cost is None or weight is None:
            continue
        weighted.append((route, cost, weight))
        total_weight += weight
        total_value += cost * weight
    if total_weight <= 0:
        return []
    mean_cost = total_value / total_weight

    total_shares = sum(
        shares for route in group.routes
        if (shares := _share(route)) is not None and shares > 0
    )
    rows: list[dict[str, Any]] = []
    for route in group.routes:
        cost = _cost(route, cost_key)
        if cost is None:
            continue
        shares = _share(route)
        rows.append(
            {
                "pair_group_id": group.group_id,
                "order_id": group.order_id,
                "order_as_of_date": group.order_as_of_date,
                "broker": _broker(route),
                "route_key": [
                    str(getattr(route, "OrderId", None) or ""),
                    str(getattr(route, "RouteId", None) or ""),
                    str(getattr(route, "order_as_of_date", None) or ""),
                ],
                "cost_bps": round(cost, 6),
                "weight": round(_weight(route), 6) if _weight(route) is not None else None,
                "relative_cost_bps": round(cost - mean_cost, 6),
                "share": (
                    round(shares / total_shares, 6)
                    if shares is not None and total_shares > 0
                    else None
                ),
            }
        )
    return rows


def _clean_diffs(values: Sequence[Optional[float]]) -> list[float]:
    cleaned: list[float] = []
    for value in values:
        number = _finite(value)
        if number is not None:
            cleaned.append(number)
    return cleaned


def wilcoxon_signed_rank(diffs: Sequence[Optional[float]]) -> dict[str, Any]:
    """Wilcoxon 符号秩检验（双侧，零差按 wilcox 处理）。"""
    cleaned = _clean_diffs(diffs)
    if not cleaned:
        return {"n": 0, "statistic": None, "p_value": None, "note": "no_pairs"}
    try:
        result = _stats.wilcoxon(cleaned, zero_method="wilcox", alternative="two-sided")
        return {
            "n": len(cleaned),
            "statistic": float(result.statistic),
            "p_value": float(result.pvalue),
            "note": "",
        }
    except ValueError as exc:  # 全零差等退化情形
        return {"n": len(cleaned), "statistic": None, "p_value": None, "note": str(exc)}


def sign_test(diffs: Sequence[Optional[float]]) -> dict[str, Any]:
    """符号检验（双侧二项检验，忽略零差）。"""
    cleaned = _clean_diffs(diffs)
    positive = sum(1 for value in cleaned if value > 0)
    negative = sum(1 for value in cleaned if value < 0)
    n = positive + negative
    if n == 0:
        return {"n": 0, "positive": 0, "negative": 0, "p_value": None, "note": "no_pairs"}
    result = _stats.binomtest(positive, n, 0.5, alternative="two-sided")
    return {
        "n": n,
        "positive": positive,
        "negative": negative,
        "p_value": float(result.pvalue),
        "note": "",
    }


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def broker_pair_tests(
    rows: Sequence[Mapping[str, Any]],
    min_pairs: int = MIN_PAIRS_FOR_TEST,
) -> list[dict[str, Any]]:
    """对每对券商在共同配对组内做配对检验（相对成本差 A − B）。"""
    by_group: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        broker = str(row.get("broker") or "")
        group_id = str(row.get("pair_group_id") or "")
        value = _finite(row.get("relative_cost_bps"))
        if broker and group_id and value is not None:
            by_group[group_id][broker].append(value)

    pair_diffs: dict[tuple[str, str], list[float]] = defaultdict(list)
    for broker_values in by_group.values():
        brokers = sorted(broker_values)
        for left_index, left in enumerate(brokers):
            for right in brokers[left_index + 1:]:
                left_mean = sum(broker_values[left]) / len(broker_values[left])
                right_mean = sum(broker_values[right]) / len(broker_values[right])
                pair_diffs[(left, right)].append(left_mean - right_mean)

    results: list[dict[str, Any]] = []
    for (left, right), diffs in pair_diffs.items():
        if len(diffs) < min_pairs:
            continue
        wilcoxon = wilcoxon_signed_rank(diffs)
        signs = sign_test(diffs)
        results.append(
            {
                "broker_a": left,
                "broker_b": right,
                "pairs": len(diffs),
                "median_diff_bps": round(_median(diffs) or 0.0, 6),
                "wilcoxon": wilcoxon,
                "sign": signs,
            }
        )
    results.sort(key=lambda item: -abs(item["median_diff_bps"]))
    return results


def fixed_effects_broker_effects(
    rows: Sequence[Mapping[str, Any]],
    min_groups: int = MIN_PAIRS_FOR_TEST,
) -> dict[str, Any]:
    """订单固定效应回归：组内去均值 + 券商哑变量 + 份额协变量（numpy OLS）。"""
    usable = [
        row for row in rows
        if _finite(row.get("relative_cost_bps")) is not None
        and _finite(row.get("share")) is not None
    ]
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in usable:
        groups[str(row.get("pair_group_id") or "")].append(row)
    groups = {key: items for key, items in groups.items() if len(items) >= 2}
    if len(groups) < min_groups:
        return {
            "available": False,
            "reason": "insufficient_groups",
            "groups": len(groups),
            "min_groups": min_groups,
            "effects": [],
        }

    y: list[float] = []
    share_x: list[float] = []
    brokers: list[str] = []
    group_ids: list[str] = []
    for group_id, items in groups.items():
        cost_mean = sum(float(item["relative_cost_bps"]) for item in items) / len(items)
        share_mean = sum(float(item["share"]) for item in items) / len(items)
        for item in items:
            y.append(float(item["relative_cost_bps"]) - cost_mean)
            share_x.append(float(item["share"]) - share_mean)
            brokers.append(str(item.get("broker") or ""))
            group_ids.append(group_id)

    counts = Counter(brokers)
    reference = counts.most_common(1)[0][0]
    others = sorted(broker for broker in counts if broker != reference)
    # 组内去均值：哑变量也要去均值（otherwise 截距被组内变换吸收，
    # 2 券商组的系数会变成真实效应的一半）
    dummy_columns: list[list[float]] = []
    for other in others:
        raw = [1.0 if broker == other else 0.0 for broker in brokers]
        means: dict[str, float] = defaultdict(float)
        sizes: dict[str, int] = defaultdict(int)
        for group_id, value in zip(group_ids, raw):
            means[group_id] += value
            sizes[group_id] += 1
        dummy_columns.append(
            [
                value - means[group_id] / sizes[group_id]
                for group_id, value in zip(group_ids, raw)
            ]
        )
    matrix = [
        [share_x[index]] + [column[index] for column in dummy_columns]
        for index in range(len(y))
    ]
    design = np.asarray(matrix, dtype=float)
    target = np.asarray(y, dtype=float)
    coefficients, _residuals, rank, _singular = np.linalg.lstsq(design, target, rcond=None)

    residual = target - design @ coefficients
    dof = len(target) - int(rank)
    sigma2 = float(residual @ residual) / dof if dof > 0 else None
    std_errors: list[Optional[float]] = [None] * len(coefficients)
    if sigma2 is not None:
        try:
            covariance = np.linalg.inv(design.T @ design) * sigma2
            std_errors = [
                float(math.sqrt(max(covariance[i, i], 0.0))) for i in range(len(coefficients))
            ]
        except np.linalg.LinAlgError:
            pass

    effects = [
        {
            "broker": other,
            "coefficient_bps": round(float(coefficients[index + 1]), 6),
            "std_error": (
                round(std_errors[index + 1], 6)
                if std_errors[index + 1] is not None else None
            ),
        }
        for index, other in enumerate(others)
    ]
    return {
        "available": True,
        "reference_broker": reference,
        "share_coefficient_bps_per_share": round(float(coefficients[0]), 6),
        "effects": effects,
        "rows": len(target),
        "groups": len(groups),
        "rank": int(rank),
    }


def _describe(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "p95": None}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {
        "n": len(values),
        "mean": round(sum(values) / len(values), 6),
        "median": round(_median(values) or 0.0, 6),
        "p95": round(ordered[p95_index], 6),
    }


def d1_section(
    routes: Sequence[Any],
    env_by_route: Optional[Mapping[Any, Any]],
    *,
    cost_key: str = DEFAULT_COST_KEY,
    min_pairs: int = MIN_PAIRS_FOR_TEST,
) -> dict[str, Any]:
    """报告 D1 章节：覆盖率、相对成本、券商对检验、固定效应。"""
    groups, excluded = pair_groups(routes, env_by_route)
    rows = [row for group in groups for row in relative_costs(group, cost_key)]
    relative = [float(row["relative_cost_bps"]) for row in rows]
    brokers = sorted({str(row["broker"]) for row in rows})
    grouped_routes = sum(len(group.routes) for group in groups)
    total_orders = len({
        (
            str(getattr(route, "OrderId", None) or ""),
            str(getattr(route, "order_as_of_date", None) or ""),
        )
        for route in routes
    })
    candidate_orders = len({(group.order_id, group.order_as_of_date) for group in groups})
    coverage_pct = (
        round(candidate_orders / total_orders * 100.0, 2) if total_orders else None
    )
    return {
        "rule": {
            "min_brokers": PAIR_MIN_BROKERS,
            "max_spread_minutes": PAIR_MAX_SPREAD_MINUTES,
            "cost_key": cost_key,
            "weight_expression": COST_WEIGHT_EXPRESSION,
            "min_pairs_for_test": min_pairs,
        },
        "coverage": {
            "total_orders": total_orders,
            "candidate_orders": candidate_orders,
            "candidate_pct": coverage_pct,
            "groups": len(groups),
            "grouped_routes": grouped_routes,
            "relative_cost_routes": len(rows),
            "brokers": len(brokers),
        },
        "excluded": {
            "no_time_routes": excluded["no_time"],
            "single_broker_orders": excluded["single_broker_orders"],
            "no_cost_routes": sum(
                1 for group in groups for route in group.routes
                if _cost(route, cost_key) is None
            ),
            "no_weight_groups": sum(
                1 for group in groups if not relative_costs(group, cost_key)
            ),
        },
        "relative_cost": _describe(relative),
        "broker_pair_tests": broker_pair_tests(rows, min_pairs=min_pairs),
        "fixed_effects": fixed_effects_broker_effects(rows, min_groups=min_pairs),
        "sample_rows": rows[:50],
    }

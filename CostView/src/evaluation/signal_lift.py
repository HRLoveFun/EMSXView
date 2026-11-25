"""信号与规则月度回检（057 DL-26/221）。

## 回答什么问题

每条告警规则（`monitoring.anomaly_query` 的 9 条阈值规则）每月都要自证价值：
**命中告警的路由，成本是否真的更差、差多少、是否只是规模/市场结构差异。**
无增量即下线；规则改阈值后，旧结论要能按版本追溯。

## 口径

- 成本：默认 `arrival_cost_bps`（报告主基准），可切换其它基准列；正值 = 成本更高。
- 标准化：按交易日 z 分数，剔除共同市场漂移；当日样本 <5 或标准差为 0 时保留原值并标注。
- 控制规模：路由名义额 `RouteShares × p_avg × fx_rate`（USD）的月度五分位 +
  `Exchange` 组成分层键，层内比较命中 vs 未命中；复用 `stratified_difference`
  的层内最小样本与加权合并规则。
- 可信区间：按 `OrderId` 聚类 bootstrap（固定种子），百分位 95% CI。
- 版本：解析后的完整规则做 SHA-256 指纹，与 `SPEC_VERSION` 一起归档。

## 不声称因果

分层控制规模与市场后，结论是**关联强度**；未观测混杂仍可能存在。自指规则
（`pnl_vwap_bps` / `intraday_volatility`，标签由成本派生）照常输出但标
``cost_derived=True``，且不进入 ``any_actionable_signal`` 汇总。
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, stdev
from typing import Any, Mapping, Optional, Sequence

from ..monitoring.anomaly_query import (
    ANOMALY_RULE_META,
    ThresholdRules,
    evaluate_route_thresholds,
)
from ..monitoring.report_spec import SPEC_VERSION
from .stratified import MIN_STRATUM_SAMPLE, stratified_difference

SIGNAL_LIFT_VERSION = "signal-lift-v1"

#: 成本派生规则：与成本 lift 机械相关，输出但排除出可执行信号汇总
COST_DERIVED_RULES: frozenset[str] = frozenset({"pnl_vwap_bps", "intraday_volatility"})

#: 数据质量探针：衡量数据可信度，不作为「交易信号」汇总
DATA_QUALITY_RULES: frozenset[str] = frozenset({
    "overfill_pct", "order_par_single_gt100", "route_par_extreme",
})

#: 可执行信号 = 非成本派生、非数据质量
NON_ACTIONABLE_RULES: frozenset[str] = COST_DERIVED_RULES | DATA_QUALITY_RULES

DEFAULT_COST_FIELD = "arrival_cost_bps"
DEFAULT_SIZE_BUCKETS = 5
DEFAULT_BOOTSTRAP = 300
DEFAULT_SEED = 2601
MIN_DAY_SAMPLE_FOR_Z = 5
MIN_BOOTSTRAP_SAMPLES = 10
ANY_ACTIONABLE_SIGNAL = "any_actionable_signal"


# ── 清洗与派生 ──────────────────────────────────────────────────────────────

def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _notional_usd(row: Mapping[str, Any]) -> Optional[float]:
    """路由名义额（USD）：股数 × 价格 × 汇率；汇率缺失且币种未知 → None（不猜 1.0）。"""
    shares = _finite(row.get("RouteShares"))
    if shares is None or shares <= 0:
        shares = _finite(row.get("Amount"))
    price = _finite(row.get("p_avg"))
    if price is None or price <= 0:
        price = _finite(row.get("p_avg_continuous"))
    fx = _finite(row.get("fx_rate"))
    if fx is None:
        currency = str(row.get("Currency") or "").strip().upper()
        if currency == "USD":
            fx = 1.0
    if shares is None or shares <= 0 or price is None or fx is None or fx <= 0:
        return None
    return shares * price * fx


def _completion_rate(row: Mapping[str, Any]) -> Optional[float]:
    fill = _finite(row.get("fill"))
    denominator = _finite(row.get("RouteShares"))
    if fill is None or denominator is None or denominator <= 0:
        return None
    return fill / denominator


def _quantile_edges(values: Sequence[float], buckets: int) -> list[float]:
    """等频分位边界（对 log1p 名义额取分位）；样本不足时返回空（退化为不分层）。"""
    if buckets < 2 or len(values) < buckets:
        return []
    ordered = sorted(values)
    n = len(ordered)
    return [ordered[min(n - 1, (n * i) // buckets)] for i in range(1, buckets)]


def _bucket_of(value: float, edges: Sequence[float]) -> int:
    return bisect.bisect_right(edges, value)


def _day_z(
    costs_by_day: Mapping[str, Sequence[float]],
) -> dict[str, tuple[float, float, bool]]:
    """每个交易日 → (均值, 标准差, 是否成功标准化)。"""
    result: dict[str, tuple[float, float, bool]] = {}
    for day, values in costs_by_day.items():
        if day and len(values) >= MIN_DAY_SAMPLE_FOR_Z:
            sd = stdev(values)
            if sd > 0:
                result[day] = (mean(values), sd, True)
                continue
        result[day] = (mean(values) if values else 0.0, 0.0, False)
    return result


# ── 单信号 lift ─────────────────────────────────────────────────────────────

def _strata_key(row: Mapping[str, Any]) -> tuple[str, int]:
    return (str(row["_exchange"]), int(row["_size_bucket"]))


def _cluster_bootstrap_ci(
    rows: Sequence[Mapping[str, Any]],
    signal_key: str,
    *,
    reps: int,
    seed: int,
    min_stratum_sample: int,
) -> Optional[list[float]]:
    """按 OrderId 聚类重采样的 95% 百分位区间（标准化成本差）。"""
    clusters: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        cluster = str(row["_order_id"] or row["_route_id"] or index)
        clusters[cluster].append(row)
    keys = list(clusters)
    if not keys or reps <= 0:
        return None
    rng = random.Random(seed)
    differences: list[float] = []
    for _ in range(reps):
        sample: list[Mapping[str, Any]] = []
        for key in rng.choices(keys, k=len(keys)):
            sample.extend(clusters[key])
        hit = [row for row in sample if signal_key in row["_hits"]]
        miss = [row for row in sample if signal_key not in row["_hits"]]
        result = stratified_difference(
            hit, miss,
            value_of=lambda row: row["_cost_std"],
            key_of=_strata_key,
            min_stratum_sample=min_stratum_sample,
        )
        if result.difference is not None:
            differences.append(result.difference)
    if len(differences) < MIN_BOOTSTRAP_SAMPLES:
        return None
    differences.sort()
    low_index = max(0, int(0.025 * len(differences)) - 1)
    high_index = min(len(differences) - 1, int(0.975 * len(differences)))
    return [round(differences[low_index], 4), round(differences[high_index], 4)]


def signal_lift(
    rows: Sequence[Mapping[str, Any]],
    signal_key: str,
    *,
    min_stratum_sample: int = MIN_STRATUM_SAMPLE,
    bootstrap: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """单信号：命中 vs 未命中的成本差（分层控制规模 + 按日标准化）。"""
    hit = [row for row in rows if signal_key in row["_hits"]]
    miss = [row for row in rows if signal_key not in row["_hits"]]
    usable = len(rows)
    hit_costs = [row["_cost"] for row in hit]
    miss_costs = [row["_cost"] for row in miss]

    standardized = stratified_difference(
        hit, miss,
        value_of=lambda row: row["_cost_std"],
        key_of=_strata_key,
        min_stratum_sample=min_stratum_sample,
    )
    raw_stratified = stratified_difference(
        hit, miss,
        value_of=lambda row: row["_cost"],
        key_of=_strata_key,
        min_stratum_sample=min_stratum_sample,
    )
    pooled_raw = (
        mean(hit_costs) - mean(miss_costs) if hit_costs and miss_costs else None
    )
    ci = _cluster_bootstrap_ci(
        rows, signal_key,
        reps=bootstrap, seed=seed, min_stratum_sample=min_stratum_sample,
    )
    return {
        "n_hit": len(hit),
        "n_miss": len(miss),
        "hit_rate": round(len(hit) / usable, 4) if usable else None,
        "raw_cost_bps": {
            "hit": round(mean(hit_costs), 4) if hit_costs else None,
            "miss": round(mean(miss_costs), 4) if miss_costs else None,
            "pooled_delta": None if pooled_raw is None else round(pooled_raw, 4),
        },
        "raw_stratified_delta_bps": (
            None if raw_stratified.difference is None
            else round(raw_stratified.difference, 4)
        ),
        "std_delta": standardized.to_payload(),
        "std_delta_ci95": ci,
        "significant_at_95": (
            None if ci is None else (ci[0] > 0 or ci[1] < 0)
        ),
    }


# ── 月度报告 ────────────────────────────────────────────────────────────────

def _rules_fingerprint(rules: ThresholdRules) -> str:
    payload = json.dumps(rules.rules, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def prepare_routes(
    routes: Sequence[Mapping[str, Any]],
    *,
    cost_field: str = DEFAULT_COST_FIELD,
    size_buckets: int = DEFAULT_SIZE_BUCKETS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """路由行 → 可计算样本 + 样本元数据（缺失不补 0）。"""
    total = len(routes)
    cost_missing = 0
    size_missing = 0
    prepared: list[dict[str, Any]] = []

    for raw in routes:
        row = dict(raw)
        # 生产查询把 RPM 别名成小写 rpm；直接读表时补齐，避免规则静默不评估
        if row.get("rpm") is None and row.get("RPM") is not None:
            row["rpm"] = row.get("RPM")
        if row.get("completion_rate") is None:
            row["completion_rate"] = _completion_rate(row)
        cost = _finite(row.get(cost_field))
        size = _notional_usd(row)
        if cost is None:
            cost_missing += 1
        if size is None:
            size_missing += 1
        if cost is None or size is None:
            continue
        prepared.append({
            "_raw": row,
            "_cost": cost,
            "_size": size,
            "_log_size": math.log1p(size),
            "_day": str(row.get("order_as_of_date") or ""),
            "_exchange": str(row.get("Exchange") or "UNKNOWN"),
            "_order_id": str(row.get("OrderId") or ""),
            "_route_id": str(row.get("RouteId") or ""),
        })

    edges = _quantile_edges([row["_log_size"] for row in prepared], size_buckets)
    by_day: dict[str, list[float]] = defaultdict(list)
    for row in prepared:
        row["_size_bucket"] = _bucket_of(row["_log_size"], edges)
        by_day[row["_day"]].append(row["_cost"])
    day_stats = _day_z(by_day)
    for row in prepared:
        day_mean, day_sd, scaled = day_stats.get(row["_day"], (0.0, 0.0, False))
        row["_cost_std"] = (row["_cost"] - day_mean) / day_sd if scaled else row["_cost"]

    days = sorted(day for day in by_day if day)
    sample = {
        "routes": total,
        "usable": len(prepared),
        "cost_missing": cost_missing,
        "size_missing": size_missing,
        "orders": len({row["_order_id"] for row in prepared if row["_order_id"]}),
        "days": len(days),
        "period": {"start": days[0] if days else None, "end": days[-1] if days else None},
        "day_standardized": sum(1 for row in prepared if day_stats.get(row["_day"], (0, 0, False))[2]),
    }
    return prepared, {
        "sample": sample,
        "size": {
            "field": "notional_usd",
            "buckets": size_buckets,
            "edges_log1p": [round(edge, 6) for edge in edges],
        },
    }


def _rule_available(rows: Sequence[Mapping[str, Any]], metric_field: str) -> bool:
    return any(row["_raw"].get(metric_field) is not None for row in rows)


def monthly_signal_lift(
    routes: Sequence[Mapping[str, Any]],
    *,
    cost_field: str = DEFAULT_COST_FIELD,
    rules_payload: Optional[dict[str, Any]] = None,
    size_buckets: int = DEFAULT_SIZE_BUCKETS,
    min_stratum_sample: int = MIN_STRATUM_SAMPLE,
    bootstrap: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """月度 lift 报告：每个规则 + 可执行信号汇总，附规则指纹与口径元数据。"""
    rules = ThresholdRules.from_payload(rules_payload)
    prepared, describe = prepare_routes(
        routes, cost_field=cost_field, size_buckets=size_buckets,
    )

    for row in prepared:
        row["_hits"] = {
            hit["key"] for hit in evaluate_route_thresholds(row["_raw"], rules)
        }
    for row in prepared:
        if any(key in row["_hits"] for key in ANOMALY_RULE_META if key not in NON_ACTIONABLE_RULES):
            row["_hits"].add(ANY_ACTIONABLE_SIGNAL)

    signals: dict[str, dict[str, Any]] = {}
    for key, meta in ANOMALY_RULE_META.items():
        result = signal_lift(
            prepared, key,
            min_stratum_sample=min_stratum_sample,
            bootstrap=bootstrap, seed=seed,
        )
        signals[key] = {
            "label": meta["label"],
            "metric_field": meta["metric_field"],
            "scale": meta["scale"],
            "cost_derived": key in COST_DERIVED_RULES,
            "data_quality": key in DATA_QUALITY_RULES,
            "enabled": bool(rules.rules[key].get("enabled", True)),
            "available": _rule_available(prepared, meta["metric_field"]),
            **result,
        }

    actionable_available = any(
        signals[key]["available"] for key in signals if key not in NON_ACTIONABLE_RULES
    )
    signals[ANY_ACTIONABLE_SIGNAL] = {
        "label": "Any actionable signal",
        "metric_field": None,
        "scale": None,
        "cost_derived": False,
        "data_quality": False,
        "enabled": True,
        "available": actionable_available,
        "excludes": sorted(NON_ACTIONABLE_RULES),
        **signal_lift(
            prepared, ANY_ACTIONABLE_SIGNAL,
            min_stratum_sample=min_stratum_sample,
            bootstrap=bootstrap, seed=seed,
        ),
    }

    period = describe["sample"]["period"]
    return {
        "version": SIGNAL_LIFT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "spec_version": SPEC_VERSION,
        "cost_field": cost_field,
        "period": period,
        "standardization": {
            "method": "per-day z-score",
            "min_day_sample": MIN_DAY_SAMPLE_FOR_Z,
            "fallback": "raw cost (day flagged in sample.day_standardized)",
        },
        "size": describe["size"],
        "sample": describe["sample"],
        "rules": {
            "fingerprint": _rules_fingerprint(rules),
            "resolved": rules.rules,
            "input": rules_payload or {},
        },
        "signals": signals,
        "notes": [
            "Lift is association, not causation; unobserved confounding may remain.",
            "Cost-derived rules are reported but excluded from any_actionable_signal.",
            "Order-level rules need order-group stats and are marked available=false in v0.",
            "Bootstrap CI resamples OrderId clusters on fixed day-standardized costs.",
        ],
    }


def render_summary(report: Mapping[str, Any]) -> str:
    """CLI 单行摘要：每个可执行信号的标准化差与 CI。"""
    parts: list[str] = []
    for key, item in (report.get("signals") or {}).items():
        if key == ANY_ACTIONABLE_SIGNAL:
            continue
        if not item.get("available"):
            continue
        delta = (item.get("std_delta") or {}).get("difference")
        ci = item.get("std_delta_ci95")
        parts.append(f"{key}={delta:+.3f} z" if delta is not None else f"{key}=n/a")
        if ci:
            parts.append(f"[{ci[0]:+.3f},{ci[1]:+.3f}]")
    return " ".join(parts)


__all__ = [
    "ANY_ACTIONABLE_SIGNAL",
    "COST_DERIVED_RULES",
    "DATA_QUALITY_RULES",
    "DEFAULT_BOOTSTRAP",
    "DEFAULT_COST_FIELD",
    "DEFAULT_SEED",
    "DEFAULT_SIZE_BUCKETS",
    "MIN_DAY_SAMPLE_FOR_Z",
    "NON_ACTIONABLE_RULES",
    "SIGNAL_LIFT_VERSION",
    "monthly_signal_lift",
    "prepare_routes",
    "render_summary",
    "signal_lift",
]

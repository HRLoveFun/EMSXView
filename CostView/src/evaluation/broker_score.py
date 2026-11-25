"""BrokerScoreSnapshot 与分项得分（057 DL-24/217）。

只出分项，不合成（D-5）：成本（DL-23 后验均值）、尾部风险（当日截面 z 的
CVaR）、完成率、机会成本、信息泄露（管道 S10 字段未进本侧作用域 → 显式不可得）、
运营质量（有成交路由占比）。CUSUM 监控日成本均值漂移；错位期样本单列。

纯计算 + 可选治理元数据；输入为正式路由（与 DL-23 `is_formal_route` 同源）。
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict
from typing import Any, Optional, Sequence

from platform_data.contracts import (
    BROKER_SCORE_VERSION,
    SCORE_COMPONENTS,
    BrokerScoreSnapshot,
    ScoreComponent,
)

from .governance import assert_governance_complete, evaluation_metadata
from .ranking import MIN_UNIT_SAMPLE, is_formal_route

CUSUM_THRESHOLD = 5.0


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _day_of(route: Any) -> str:
    return str(getattr(route, "order_as_of_date", "") or "")


def _broker_of(route: Any) -> str:
    return str(getattr(route, "Broker", None) or "Unknown")


def _daily_z(values: Sequence[float], days: Sequence[str]) -> list[float]:
    groups: dict[str, list[float]] = defaultdict(list)
    for value, day in zip(values, days):
        if day:
            groups[day].append(value)
    z_values: list[float] = []
    for value, day in zip(values, days):
        members = groups.get(day) or []
        if day and len(members) >= 2:
            mean = sum(members) / len(members)
            variance = sum((member - mean) ** 2 for member in members) / (len(members) - 1)
            sd = math.sqrt(variance)
            z_values.append((value - mean) / sd if sd > 0 else 0.0)
        else:
            z_values.append(0.0)
    return z_values


def _cvar(z_values: Sequence[float], alpha: float = 0.95) -> Optional[float]:
    if not z_values:
        return None
    ordered = sorted(z_values)
    tail = max(1, int(round((1.0 - alpha) * len(ordered))))
    return sum(ordered[-tail:]) / tail


def _completion(route: Any) -> Optional[float]:
    fill = _finite(getattr(route, "fill", None))
    denominator = _finite(getattr(route, "RouteShares", None))
    if denominator is None or denominator <= 0:
        denominator = _finite(getattr(route, "Amount", None))
    if fill is None or denominator is None or denominator <= 0:
        return None
    return fill / denominator


def _operational(route: Any) -> Optional[bool]:
    fill_count = _finite(getattr(route, "fill_count", None))
    if fill_count is not None:
        return fill_count > 0
    fill = _finite(getattr(route, "fill", None))
    return None if fill is None else fill > 0


def _cusum(daily_means: Sequence[float]) -> dict[str, Any]:
    """上/下 CUSUM（目标 = 均值，σ = 标准差）；阈值 5σ。"""
    values = [float(value) for value in daily_means if _finite(value) is not None]
    if len(values) < 3:
        return {"up_peak": 0.0, "down_peak": 0.0, "alert": False, "direction": "none", "days": len(values)}
    target = sum(values) / len(values)
    variance = sum((value - target) ** 2 for value in values) / (len(values) - 1)
    sd = math.sqrt(variance)
    if sd <= 0:
        return {"up_peak": 0.0, "down_peak": 0.0, "alert": False, "direction": "none", "days": len(values)}
    up = down = 0.0
    up_peak = down_peak = 0.0
    for value in values:
        step = (value - target) / sd
        up = max(0.0, up + step)
        down = min(0.0, down + step)
        up_peak = max(up_peak, up)
        down_peak = min(down_peak, down)
    alert = max(up_peak, abs(down_peak)) > CUSUM_THRESHOLD
    direction = "up" if up_peak >= abs(down_peak) else "down"
    return {
        "up_peak": round(up_peak, 4),
        "down_peak": round(down_peak, 4),
        "alert": alert,
        "direction": direction if alert else "none",
        "days": len(values),
    }


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def build_broker_scores(
    routes: Sequence[Any],
    ranking: dict[str, Any],
    *,
    as_of: str,
    window_start: str,
    window_end: str,
    spec_version: str,
    benchmark: str = "arrival",
    min_unit_sample: int = MIN_UNIT_SAMPLE,
) -> dict[str, Any]:
    """由正式路由 + DL-23 ranking 构建券商分项快照与治理元数据。"""
    formal = [route for route in routes if is_formal_route(route)]
    grouped: dict[str, list[Any]] = defaultdict(list)
    for route in formal:
        if _finite(getattr(route, "arrival_cost_bps", None)) is not None:
            grouped[_broker_of(route)].append(route)

    ranking_units = {
        str(unit.get("broker") or ""): unit
        for unit in ranking.get("units") or []
        if unit.get("broker")
    }

    snapshots: list[BrokerScoreSnapshot] = []
    for broker, items in sorted(grouped.items()):
        aligned = [route for route in items if _day_of(route)]
        misaligned = len(items) - len(aligned)
        values = [float(getattr(route, "arrival_cost_bps")) for route in aligned]
        days = [_day_of(route) for route in aligned]
        z_values = _daily_z(values, days)
        unit = ranking_units.get(broker) or {}
        daily_means = {
            day: _mean([value for value, d in zip(values, days) if d == day])
            for day in sorted(set(days))
        }
        cusum = _cusum([mean for mean in daily_means.values() if mean is not None])

        completions = [
            completion for route in aligned
            if (completion := _completion(route)) is not None
        ]
        opportunities = [
            cost for route in aligned
            if (cost := _finite(getattr(route, "opportunity_cost", None))) is not None
        ]
        operational = [
            flag for route in aligned
            if (flag := _operational(route)) is not None
        ]
        components = (
            ScoreComponent(
                name="cost",
                value=unit.get("posterior_mean"),
                unit="bps",
                sample_size=len(values),
                available=unit.get("posterior_mean") is not None,
                note=(
                    "DL-23 posterior mean (cluster-robust + shrinkage); low_sample"
                    if unit.get("low_sample") else
                    "DL-23 posterior mean (cluster-robust + shrinkage)"
                ),
            ),
            ScoreComponent(
                name="tail_risk",
                value=_cvar(z_values),
                unit="z",
                sample_size=len(z_values),
                available=len(z_values) >= 2,
                note="95% CVaR of same-day cross-sectional z (positive = worse)",
            ),
            ScoreComponent(
                name="completion",
                value=_mean(completions),
                unit="ratio",
                sample_size=len(completions),
                available=bool(completions),
                note="mean fill / RouteShares (fallback fill / Amount)",
            ),
            ScoreComponent(
                name="opportunity_cost",
                value=_mean(opportunities),
                unit="currency",
                sample_size=len(opportunities),
                available=bool(opportunities),
                note="mean opportunity_cost (native currency)",
            ),
            ScoreComponent(
                name="leakage",
                value=None,
                unit="bps",
                sample_size=0,
                available=False,
                note="pipeline S10 reversal_30m_bps not in CostView scope yet",
            ),
            ScoreComponent(
                name="operational",
                value=(sum(1 for flag in operational if flag) / len(operational))
                if operational else None,
                unit="ratio",
                sample_size=len(operational),
                available=bool(operational),
                note="share of routes with fill_count > 0 (proxy)",
            ),
        )
        snapshots.append(
            BrokerScoreSnapshot(
                broker=broker,
                as_of=as_of,
                window_start=window_start,
                window_end=window_end,
                spec_version=BROKER_SCORE_VERSION,
                components=components,
                weights={},
                composite=None,
                cusum=cusum,
                misaligned_samples=misaligned,
                low_sample=len(values) < min_unit_sample,
            )
        )

    governance = evaluation_metadata(
        benchmark=benchmark,
        spec_version=spec_version,
        data_range=(window_start, window_end),
        scope={
            "components": list(SCORE_COMPONENTS),
            "window": {"start": window_start, "end": window_end},
        },
        sample_sizes={"routes": len(formal), "brokers": len(snapshots)},
        degradations=["leakage_unavailable"],
        extra={
            "broker_score_version": BROKER_SCORE_VERSION,
            "composite": "not-scheduled (D-5)",
        },
    )
    assert_governance_complete(governance)

    return {
        "available": bool(snapshots),
        "schema_version": BROKER_SCORE_VERSION,
        "spec_version": spec_version,
        "as_of": as_of,
        "window_start": window_start,
        "window_end": window_end,
        "benchmark": benchmark,
        "components": list(SCORE_COMPONENTS),
        "snapshots": [asdict(snapshot) for snapshot in snapshots],
        "coverage": {
            "routes": len(formal),
            "brokers": len(snapshots),
            "misaligned_samples": sum(snapshot.misaligned_samples for snapshot in snapshots),
        },
        "governance": governance,
    }

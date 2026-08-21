"""异常路由判定查询与阈值参数化。

供 HTML 报告 S6 异常路由明细表使用，判定口径与前端
``frontend/src/modules/costview/lib/thresholds.ts`` 完全对齐：
- 规则键 → 指标字段映射（getMetricValue 同款）
- mode：absolute-above / above / below（evaluateThreshold 同款）
- 默认阈值 = 前端 DEFAULT_RULES 同值（两处常量，注释互引）

查询全部参数化（? 占位符），指标名仅来自内部白名单常量，无注入风险。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager

# ── 阈值规则定义（与前端 thresholds.ts 同步）────────────────────────────────

#: 规则键 → (tca_route_summary 字段, 缩放系数)。缩放系数用于把存储值换算成阈值口径：
#: par_rate 存储为 0-1 小数，阈值按百分比 0-100 → ×100；
#: pnl_vwap_continuous 为 bps，阈值按百分比 → ÷100。
_METRIC_MAP: dict[str, tuple[str, float]] = {
    "tracking_error_bps": ("pnl_vwap", 1.0),
    "fill_pct": ("fill", 1.0),
    "volume_pct_adv20": ("par_rate", 100.0),
    "volume_pct_interval": ("par_rate_continuous", 100.0),
    "intraday_volatility": ("pnl_vwap_continuous", 0.01),
    "price_movement_pct": ("rpm", 1.0),
}

_RULE_KEYS: tuple[str, ...] = (
    "tracking_error_bps", "fill_pct", "volume_pct_adv20",
    "volume_pct_interval", "intraday_volatility", "price_movement_pct",
)

#: 命中规则的中文标签（渲染展示用）
_RULE_LABELS: dict[str, str] = {
    "tracking_error_bps": "Tracking Error",
    "fill_pct": "Fill %",
    "volume_pct_adv20": "Vol % ADV20",
    "volume_pct_interval": "Vol % Interval",
    "intraday_volatility": "Intraday Vol",
    "price_movement_pct": "Price Move",
}

#: 默认阈值（与前端 DEFAULT_RULES 同值，改动需同步 two places）
DEFAULT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "tracking_error_bps": {"mode": "absolute-above", "warning": 10, "critical": 25, "enabled": True},
    "fill_pct": {"mode": "below", "warning": 80, "critical": 50, "enabled": True},
    "volume_pct_adv20": {"mode": "above", "warning": 5, "critical": 10, "enabled": True},
    "volume_pct_interval": {"mode": "above", "warning": 20, "critical": 35, "enabled": True},
    "intraday_volatility": {"mode": "above", "warning": 2.5, "critical": 4, "enabled": True},
    "price_movement_pct": {"mode": "absolute-above", "warning": 1, "critical": 2.5, "enabled": True},
}


@dataclass(frozen=True)
class ThresholdRules:
    """解析并校验后的阈值规则集合。"""

    rules: dict[str, dict[str, Any]]

    @classmethod
    def from_payload(cls, payload: Optional[dict[str, Any]]) -> "ThresholdRules":
        """从请求 payload 构造；None/空 → 默认阈值。校验字段类型与白名单。"""
        merged: dict[str, dict[str, Any]] = {}
        for key in _RULE_KEYS:
            base = dict(DEFAULT_THRESHOLDS[key])
            if payload and key in payload and isinstance(payload[key], dict):
                src = payload[key]
                if "mode" in src:
                    base["mode"] = src["mode"]
                if "warning" in src:
                    base["warning"] = float(src["warning"])
                if "critical" in src:
                    base["critical"] = float(src["critical"])
                if "enabled" in src:
                    base["enabled"] = bool(src["enabled"])
            merged[key] = base
        return cls(rules=merged)


# ── 异常判定（与前端 evaluateThreshold / getMetricValue 同款逻辑）────────────

def _evaluate_rule(
    rule: dict[str, Any], raw_value: Optional[float],
) -> str:
    """返回 'none' | 'warning' | 'critical' | 'normal'（none=未启用或值缺失）。"""
    if not rule.get("enabled", True) or raw_value is None:
        return "none"
    mode = rule.get("mode", "absolute-above")
    value = abs(raw_value) if mode == "absolute-above" else raw_value
    warning = float(rule.get("warning", 0))
    critical = float(rule.get("critical", 0))
    if mode == "below":
        if value <= critical:
            return "critical"
        if value <= warning:
            return "warning"
        return "normal"
    if value >= critical:
        return "critical"
    if value >= warning:
        return "warning"
    return "normal"


def evaluate_route_thresholds(
    route: dict[str, Any], rules: ThresholdRules,
) -> list[dict[str, Any]]:
    """对单条路由行评估全部规则，返回命中的告警列表（按规则顺序）。"""
    hits: list[dict[str, Any]] = []
    for key in _RULE_KEYS:
        field_name, scale = _METRIC_MAP[key]
        raw = route.get(field_name)
        if raw is None:
            continue
        try:
            value = float(raw) * scale
        except (TypeError, ValueError):
            continue
        severity = _evaluate_rule(rules.rules[key], value)
        if severity in ("warning", "critical"):
            hits.append({
                "key": key, "label": _RULE_LABELS[key],
                "severity": severity, "value": round(value, 4),
            })
    return hits


def _highest_severity(hits: list[dict[str, Any]]) -> str:
    """命中告警中的最高严重度。"""
    for sev in ("critical", "warning"):
        if any(h["severity"] == sev for h in hits):
            return sev
    return "normal"


# ── 明细行查询 ──────────────────────────────────────────────────────────────


@dataclass
class AnomalyRoute:
    """异常路由明细行（供渲染器直接消费）。"""

    severity: str
    order_id: str
    route_id: str
    date: str
    ticker: str
    exchange: Optional[str]
    side: Optional[str]
    broker: Optional[str]
    algo: Optional[str]
    fill: Optional[float]
    completion_rate: Optional[float]
    par_rate: Optional[float]
    pnl_vwap: Optional[float]
    arrival_cost_bps: Optional[float]
    wagner_is_bps: Optional[float]
    opportunity_cost: Optional[float]
    unfilled: Optional[float]
    cost_cvar: Optional[float]
    order_duration_sec: Optional[float]
    recovery_truncated: Optional[int]
    hits: list[dict[str, Any]] = field(default_factory=list)


def query_anomaly_routes(
    mgr: ConnectionManager,
    start_date: str,
    end_date: str,
    rules: ThresholdRules,
    *,
    broker: Optional[str] = None,
    algo: Optional[str] = None,
    symbol: Optional[str] = None,
    exchange: Optional[str] = None,
) -> list[AnomalyRoute]:
    """查询筛选范围内触发 warning/critical 的全部路由（无上限）。

    按严重度 critical → warning 降序，再按日期、OrderId、RouteId 排序。
    表不存在时返回空列表。
    """
    conn = mgr.get_connection("fill_bdib", AccessTier.READ)
    try:
        cursor = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            [Config.TCA_ROUTE_SUMMARY_TABLE],
        )
        if cursor.fetchone() is None:
            return []

        conditions = ["order_as_of_date BETWEEN ? AND ?"]
        params: list[Any] = [start_date, end_date]
        for column, value in (
            ("Broker", broker), ("algo", algo),
            ("equ_ticker", symbol), ("Exchange", exchange),
        ):
            if value:
                conditions.append(f"{column} = ?")
                params.append(value)

        sql = f"""
            SELECT OrderId, RouteId, order_as_of_date, equ_ticker, Exchange,
                   Side, Broker, algo, fill, par_rate, pnl_vwap,
                   arrival_cost_bps, wagner_is_bps, opportunity_cost,
                   RouteShares, cost_cvar, order_duration_sec, recovery_truncated
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            WHERE {" AND ".join(conditions)}
        """
        cursor = conn.execute(sql, params)
        rows = [dict(zip([d[0] for d in cursor.description], r)) for r in cursor.fetchall()]
    finally:
        conn.close()

    results: list[AnomalyRoute] = []
    for row in rows:
        hits = evaluate_route_thresholds(row, rules)
        severity = _highest_severity(hits)
        if severity not in ("warning", "critical"):
            continue
        route_shares = _to_float(row.get("RouteShares"))
        fill = _to_float(row.get("fill"))
        unfilled = None
        completion_rate = None
        if route_shares is not None and fill is not None and route_shares > 0:
            unfilled = route_shares - fill
            completion_rate = fill / route_shares
        results.append(AnomalyRoute(
            severity=severity,
            order_id=str(row.get("OrderId") or ""),
            route_id=str(row.get("RouteId") or ""),
            date=str(row.get("order_as_of_date") or ""),
            ticker=row.get("equ_ticker") or "",
            exchange=row.get("Exchange"),
            side=row.get("Side"),
            broker=row.get("Broker"),
            algo=row.get("algo"),
            fill=fill,
            completion_rate=completion_rate,
            par_rate=_to_float(row.get("par_rate")),
            pnl_vwap=_to_float(row.get("pnl_vwap")),
            arrival_cost_bps=_to_float(row.get("arrival_cost_bps")),
            wagner_is_bps=_to_float(row.get("wagner_is_bps")),
            opportunity_cost=_to_float(row.get("opportunity_cost")),
            unfilled=unfilled,
            cost_cvar=_to_float(row.get("cost_cvar")),
            order_duration_sec=_to_float(row.get("order_duration_sec")),
            recovery_truncated=row.get("recovery_truncated"),
            hits=hits,
        ))

    order = {"critical": 0, "warning": 1}
    results.sort(key=lambda r: (order.get(r.severity, 9), r.date, r.order_id, r.route_id))
    return results


def _to_float(value: Any) -> Optional[float]:
    """数值安全转换，None/NaN → None。"""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None

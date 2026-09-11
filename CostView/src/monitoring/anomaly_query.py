"""异常路由判定查询与阈值参数化。

供 HTML 报告 S6 异常路由明细表使用，判定口径与前端
``frontend/src/modules/costview/lib/thresholds.ts`` 完全对齐：
- 规则键 → 指标字段映射（getMetricValue 同款）
- mode：absolute-above / above / below（evaluateThreshold 同款）
- 默认阈值 = 前端 DEFAULT_RULES 同值（两处常量，注释互引）

查询全部参数化（? 占位符），指标名仅来自内部白名单常量，无注入风险。
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from data_access.config import Config
from data_access.storage.connection import AccessTier, ConnectionManager

# ── 阈值规则定义（与前端 thresholds.ts 同步）────────────────────────────────

#: 规则键 → (tca_route_summary 字段, 缩放系数)。缩放系数用于把存储值换算成阈值口径：
#: completion_rate / par_rate 存储为 0-1 小数，阈值按百分比 0-100 → ×100；
#: pnl_vwap_continuous 为 bps，阈值按百分比 → ÷100。
#: 注意：fill_pct 必须用完成率百分比（fill/RouteShares×100）比对，不能用工数字段 fill（股数），
#: 否则永远不触发阈值。完成率在查询期预计算并注入 row["completion_rate"]。
_METRIC_MAP: dict[str, tuple[str, float]] = {
    "tracking_error_bps": ("pnl_vwap", 1.0),
    "fill_pct": ("completion_rate", 100.0),
    "volume_pct_adv20": ("par_rate", 100.0),
    "volume_pct_interval": ("par_rate_continuous", 100.0),
    "intraday_volatility": ("pnl_vwap_continuous", 0.01),
    "price_movement_pct": ("rpm", 1.0),
    # 数据质量探针（013）：完成率超过 100% / 订单参与率求和超过 100% 均属数据矛盾，
    # 此前被展示层封顶掩盖，现作为独立规则纳入异常判定，不再静默放过。
    "overfill_pct": ("completion_rate", 100.0),
    "order_par_gt100": ("order_par_rate", 100.0),
}

_RULE_KEYS: tuple[str, ...] = (
    "tracking_error_bps", "fill_pct", "volume_pct_adv20",
    "volume_pct_interval", "intraday_volatility", "price_movement_pct",
    "overfill_pct", "order_par_gt100",
)

#: 命中规则的中文标签（渲染展示用）
_RULE_LABELS: dict[str, str] = {
    "tracking_error_bps": "Tracking Error",
    "fill_pct": "Fill %",
    "volume_pct_adv20": "Vol % ADV20",
    "volume_pct_interval": "Vol % Interval",
    "intraday_volatility": "Intraday Vol",
    "price_movement_pct": "Price Move",
    "overfill_pct": "Overfill %",
    "order_par_gt100": "Order Par >100%",
}

#: 命中规则的单位（渲染「超限具体数值」用）
_RULE_UNITS: dict[str, str] = {
    "tracking_error_bps": "bps",
    "fill_pct": "percent",
    "volume_pct_adv20": "percent",
    "volume_pct_interval": "percent",
    "intraday_volatility": "percent",
    "price_movement_pct": "percent",
    "overfill_pct": "percent",
    "order_par_gt100": "percent",
}

#: 默认阈值（后端为唯一真相源；前端经 /api/tca/monitoring/anomaly-thresholds 拉取，
#: 本地 DEFAULT_RULES 仅作离线兜底。调整阈值只需改此处）。
#: 双档语义（修订 ADR-0015）：``warning`` 为「进入异常清单」的边界（覆盖范围与该
#: ADR 单档时期保持一致），``critical`` 仅用于分级标注，不改变清单覆盖范围。
#: below 模式下 critical < warning（更严格），above/absolute-above 模式下
#: critical > warning。
DEFAULT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "tracking_error_bps": {
        "mode": "absolute-above", "warning": 10, "critical": 25, "enabled": True},
    "fill_pct": {"mode": "below", "warning": 80, "critical": 50, "enabled": True},
    "volume_pct_adv20": {"mode": "above", "warning": 5, "critical": 10, "enabled": True},
    "volume_pct_interval": {
        "mode": "above", "warning": 20, "critical": 35, "enabled": True},
    "intraday_volatility": {
        "mode": "above", "warning": 2.5, "critical": 4, "enabled": True},
    "price_movement_pct": {
        "mode": "absolute-above", "warning": 1, "critical": 2.5, "enabled": True},
    # 数据质量探针：超过 warning 档即入清单，超过 critical 档标注为严重
    "overfill_pct": {"mode": "above", "warning": 100, "critical": 110, "enabled": True},
    "order_par_gt100": {
        "mode": "above", "warning": 100, "critical": 200, "enabled": True},
}

#: 合法的比较模式白名单（P2-6：payload 内 mode 缺失或非法时 fail-fast，
#: 此前任意字符串会被静默按 above 处理，阈值语义被无声改变）
_VALID_MODES: tuple[str, ...] = ("absolute-above", "above", "below")


def get_default_thresholds() -> dict[str, dict[str, Any]]:
    """返回异常路由判定默认阈值（后端为唯一真相源，前端从此拉取）。

    返回深拷贝，避免调用方误改模块级常量。
    """
    return {key: dict(value) for key, value in DEFAULT_THRESHOLDS.items()}


#: 规则元数据（对外暴露：键 → 中文标签 / 指标字段 / 缩放系数），供前端构建规则 UI。
ANOMALY_RULE_META: dict[str, dict[str, Any]] = {
    key: {
        "label": _RULE_LABELS[key],
        "metric_field": _METRIC_MAP[key][0],
        "scale": _METRIC_MAP[key][1],
    }
    for key in _RULE_KEYS
}


@dataclass(frozen=True)
class ThresholdRules:
    """解析并校验后的阈值规则集合。"""

    rules: dict[str, dict[str, Any]]

    @classmethod
    def from_payload(cls, payload: Optional[dict[str, Any]]) -> "ThresholdRules":
        """从请求 payload 构造；None/空 → 默认阈值。校验字段类型与白名单。

        支持双档 ``warning`` / ``critical``；同时向后兼容 ADR-0015 单档
        ``threshold`` 写法（等价 warning = critical = threshold，不产生分级）。

        P2-6 整改：
        - mode 必须属于 _VALID_MODES，否则抛 ValueError（调用方转 422），
          不再静默回退为 above；
        - enabled 必须为 JSON 布尔值，不再用 bool() 强转（字符串 "false"
          此前会被强转为 True）。
        """
        merged: dict[str, dict[str, Any]] = {}
        for key in _RULE_KEYS:
            base = dict(DEFAULT_THRESHOLDS[key])
            if payload and key in payload and isinstance(payload[key], dict):
                base = cls._merge_rule(key, base, payload[key])
            merged[key] = base
        return cls(rules=merged)

    @staticmethod
    def _merge_rule(
        key: str, base: dict[str, Any], src: dict[str, Any],
    ) -> dict[str, Any]:
        """合并单条规则的 payload 覆盖（含单档 threshold 向后兼容）。"""
        if "mode" in src:
            if src["mode"] not in _VALID_MODES:
                raise ValueError(
                    f"规则 {key} 的 mode 非法: {src['mode']!r}，"
                    f"可选: {', '.join(_VALID_MODES)}"
                )
            base["mode"] = src["mode"]
        if "warning" in src:
            base["warning"] = float(src["warning"])
        if "critical" in src:
            base["critical"] = float(src["critical"])
        if "threshold" in src:
            # 向后兼容 ADR-0015 单档 payload：两档同值（不产生分级）
            merged_value = float(src["threshold"])
            base["warning"] = merged_value
            base["critical"] = merged_value
        if "enabled" in src:
            if not isinstance(src["enabled"], bool):
                raise ValueError(
                    f"规则 {key} 的 enabled 必须为布尔值，"
                    f"得到: {src['enabled']!r}"
                )
            base["enabled"] = src["enabled"]
        return base


# ── 异常判定（与前端 evaluateThreshold / getMetricValue 同款逻辑）────────────

#: 严重度排序权重（数值越小越严重），用于明细排序与「最严重档」归并
_SEVERITY_RANK: dict[str, int] = {"critical": 0, "warning": 1, "none": 2}


def _evaluate_rule(
    rule: dict[str, Any], raw_value: Optional[float],
) -> str:
    """返回 'none' | 'warning' | 'critical'（none = 未启用或值缺失）。

    进入异常清单的边界为 ``warning`` 档（与 ADR-0015 单档时期的覆盖范围一致）；
    ``critical`` 档仅用于分级标注，不改变清单覆盖范围。below 模式下两档关系
    相反（critical 阈值更小、更严格）。
    """
    if not rule.get("enabled", True) or raw_value is None:
        return "none"
    mode = rule.get("mode", "absolute-above")
    value = abs(raw_value) if mode == "absolute-above" else raw_value
    warning = float(rule.get("warning", rule.get("threshold", 0)))
    critical = float(rule.get("critical", warning))
    if mode == "below":
        if value <= critical:
            return "critical"
        return "warning" if value <= warning else "none"
    if value >= critical:
        return "critical"
    return "warning" if value >= warning else "none"


def _worst_severity(hits: list[dict[str, Any]]) -> str:
    """取命中项中最严重的档（critical > warning）；无命中返回 'none'。"""
    if any(h.get("severity") == "critical" for h in hits):
        return "critical"
    return "warning" if hits else "none"


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
        if severity != "none":
            hits.append({
                "key": key, "label": _RULE_LABELS[key],
                "value": round(value, 4), "unit": _RULE_UNITS[key],
                "severity": severity,
            })
    return hits


# ── 明细行查询 ──────────────────────────────────────────────────────────────


#: overfill 判定容差：fill > RouteShares × (1 + eps) 视为成交超过委托（数据矛盾）
_OVERFILL_EPS = 1e-9


def _order_par_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """订单参与率聚合键：(OrderId, order_as_of_date, Exchange)。

    按交易所分组，避免跨市场求和使订单参与率失去物理意义
    （不同市场的成交量不可直接相加）。
    """
    return (
        str(row.get("OrderId") or ""),
        str(row.get("order_as_of_date") or ""),
        str(row.get("Exchange") or ""),
    )


@dataclass
class AnomalyRoute:
    """异常路由明细行（供渲染器直接消费）。"""

    order_id: str
    route_id: str
    date: str
    ticker: str
    exchange: Optional[str]
    side: Optional[str]
    broker: Optional[str]
    algo: Optional[str]
    fill: Optional[float]
    fill_count: Optional[int]
    route_shares: Optional[float]
    completion_rate: Optional[float]
    par_rate: Optional[float]
    order_par_rate: Optional[float]
    pnl_vwap: Optional[float]
    arrival_cost_bps: Optional[float]
    wagner_is_bps: Optional[float]
    opportunity_cost: Optional[float]
    unfilled: Optional[float]
    cost_cvar: Optional[float]
    order_duration_sec: Optional[float]
    recovery_truncated: Optional[int]
    currency: Optional[str] = None
    notional_local: Optional[float] = None
    notional_usd: Optional[float] = None
    #: 数据质量标记（013）：成交超过委托 / 订单参与率求和 >100%
    overfill: bool = False
    order_par_gt100: bool = False
    #: 命中项中的最严重档（critical / warning），供明细排序与分级渲染
    severity: str = "warning"
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
    min_fill_count: int = 10,
    min_notional_usd: float = 10000.0,
    limit: Optional[int] = None,
) -> list[AnomalyRoute]:
    """查询异常路由（便捷封装，返回排序后的明细列表）。

    limit 为 None 时返回全部命中路由；否则仅返回严重度最高的前 limit 条。
    需要同时获得命中总数时请用 :func:`query_anomaly_routes_page`。
    """
    routes, _ = query_anomaly_routes_page(
        mgr, start_date, end_date, rules,
        broker=broker, algo=algo, symbol=symbol, exchange=exchange,
        min_fill_count=min_fill_count, min_notional_usd=min_notional_usd,
        limit=limit,
    )
    return routes


def query_anomaly_routes_page(
    mgr: ConnectionManager,
    start_date: str,
    end_date: str,
    rules: ThresholdRules,
    *,
    broker: Optional[str] = None,
    algo: Optional[str] = None,
    symbol: Optional[str] = None,
    exchange: Optional[str] = None,
    min_fill_count: int = 10,
    min_notional_usd: float = 10000.0,
    limit: Optional[int] = None,
) -> tuple[list[AnomalyRoute], int]:
    """查询筛选范围内命中阈值（warning 档及以上）的路由，返回 (明细, 命中总数)。

    min_fill_count：异常路由填充笔数下限（默认 10）。仅对 algo <> "close" 的路由生效——
    该档路由填充笔数低于下限时视为样本噪声、不计入异常清单；algo="close" 不做此限制。
    min_notional_usd：异常路由成交金额(USD)下限（默认 10000），对全部路由生效——
    无法换算 USD（fx 缺失）或金额低于下限的路由不计入异常清单。
    明细按「严重度优先 + pnl_vwap 升序」排序（critical 在前，同档内成本由劣到优）；
    limit 截断的是**排序后**的前 N 条，因此截断样本无偏（必为最严重的 N 条）。
    表不存在时返回 ([], 0)。
    """
    conn = None
    try:
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        cursor = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            [Config.TCA_ROUTE_SUMMARY_TABLE],
        )
        if cursor.fetchone() is None:
            return []

        # fx_rate 列在旧库可能缺失（向后兼容）：缺失时以 NULL 占位，USD 不换算。
        has_fx = _has_column(conn, Config.TCA_ROUTE_SUMMARY_TABLE, "fx_rate")
        has_fill_count = _has_column(conn, Config.TCA_ROUTE_SUMMARY_TABLE, "fill_count")
        # 报告期 fill_bdib 汇率回填（与 report_aggregator 同源，改用 CTE 以兼容
        # READ 只读事务，避免 CREATE TEMP TABLE 被访问层拒绝），使异常明细的成交
        # 金额(USD) 在 tca.fx_rate 缺失时也能从 fill_bdib 补全。
        fbfx_ready = _prepare_anomaly_fx(conn) if has_fx else False

        conditions = ["order_as_of_date BETWEEN ? AND ?"]
        params: list[Any] = [start_date, end_date]
        for column, value in (
            ("Broker", broker), ("algo", algo),
            ("equ_ticker", symbol), ("Exchange", exchange),
        ):
            if value:
                conditions.append(f"{column} = ?")
                params.append(value)

        join = _anomaly_fx_join() if fbfx_ready else ""
        fx_select = "fx_rate" if has_fx else "NULL AS fx_rate"
        fill_count_select = "fill_count" if has_fill_count else "NULL AS fill_count"
        notional_usd_expr = _anomaly_notional_usd_expr(fbfx_ready, has_fx)
        sql = f"""
            SELECT OrderId, RouteId, order_as_of_date, equ_ticker, Exchange,
                   Side, Broker, algo, fill, par_rate, pnl_vwap,
                   arrival_cost_bps, wagner_is_bps, opportunity_cost,
                   RouteShares, cost_cvar, order_duration_sec, recovery_truncated,
                   Amount, Currency, {fill_count_select}, {fx_select},
                   {notional_usd_expr} AS notional_usd_calc
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}{join}
            WHERE {" AND ".join(conditions)}
        """
        if fbfx_ready:
            sql = _ANOMALY_FX_CTE + sql
            params = [start_date, end_date] + params
        cursor = conn.execute(sql, params)
        rows = [dict(zip([d[0] for d in cursor.description], r)) for r in cursor.fetchall()]
    except FileNotFoundError:
        # 只读模式下 fill_bdib.db 缺失 → 无异常路由（与表缺失同语义, 009）
        return []
    finally:
        if conn is not None:
            conn.close()

    # 订单参与率：同一订单键下所有路由 par_rate 之和（0-1 小数，可能 >1）
    order_par_sum: dict[tuple[str, str, str], float] = {}
    for row in rows:
        key = _order_par_key(row)
        pr = _to_float(row.get("par_rate"))
        if pr is not None:
            order_par_sum[key] = order_par_sum.get(key, 0.0) + pr

    results: list[AnomalyRoute] = []
    for row in rows:
        route_shares = _to_float(row.get("RouteShares"))
        fill = _to_float(row.get("fill"))
        unfilled = None
        completion_rate = None
        overfill = False
        if route_shares is not None and fill is not None and route_shares > 0:
            unfilled = route_shares - fill
            completion_rate = fill / route_shares
            overfill = fill > route_shares * (1.0 + _OVERFILL_EPS)
        # 预计算完成率与订单参与率注入 row，供 fill_pct / overfill_pct /
        # order_par_gt100 规则评估（阈值按百分比 0-100）
        order_par_rate = order_par_sum.get(_order_par_key(row))
        row["completion_rate"] = completion_rate
        row["order_par_rate"] = order_par_rate
        hits = evaluate_route_thresholds(row, rules)
        if not hits:
            continue
        # 填充笔数下限过滤：仅对 algo <> "close" 的路由生效（下限为 0 时关闭）
        algo_value = (row.get("algo") or "")
        if algo_value != "close" and min_fill_count > 0:
            fc = _to_int(row.get("fill_count"))
            if fc is None or fc < min_fill_count:
                continue
        amount = _to_float(row.get("Amount"))
        notional_usd = _to_float(row.get("notional_usd_calc"))
        # 成交金额(USD)下限过滤：对全部路由生效（下限为 0 时关闭，含无法换算 USD 的路由）
        if min_notional_usd > 0 and (notional_usd is None or notional_usd < min_notional_usd):
            continue
        results.append(AnomalyRoute(
            order_id=str(row.get("OrderId") or ""),
            route_id=str(row.get("RouteId") or ""),
            date=str(row.get("order_as_of_date") or ""),
            ticker=row.get("equ_ticker") or "",
            exchange=row.get("Exchange"),
            side=row.get("Side"),
            broker=row.get("Broker"),
            algo=row.get("algo"),
            fill=fill,
            fill_count=_to_int(row.get("fill_count")),
            route_shares=route_shares,
            completion_rate=completion_rate,
            par_rate=_to_float(row.get("par_rate")),
            order_par_rate=order_par_rate,
            pnl_vwap=_to_float(row.get("pnl_vwap")),
            arrival_cost_bps=_to_float(row.get("arrival_cost_bps")),
            wagner_is_bps=_to_float(row.get("wagner_is_bps")),
            opportunity_cost=_to_float(row.get("opportunity_cost")),
            unfilled=unfilled,
            cost_cvar=_to_float(row.get("cost_cvar")),
            order_duration_sec=_to_float(row.get("order_duration_sec")),
            recovery_truncated=row.get("recovery_truncated"),
            currency=row.get("Currency"),
            notional_local=amount,
            notional_usd=notional_usd,
            overfill=overfill,
            order_par_gt100=order_par_rate is not None and order_par_rate > 1.0,
            severity=_worst_severity(hits),
            hits=hits,
        ))

    results.sort(key=lambda r: (
        _SEVERITY_RANK.get(r.severity, 2),
        r.pnl_vwap if r.pnl_vwap is not None else float("inf"),
        r.date, r.order_id, r.route_id,
    ))
    total = len(results)
    if limit is not None:
        results = results[: max(0, limit)]
    return results, total


def _to_float(value: Any) -> Optional[float]:
    """数值安全转换，None/NaN → None。"""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _to_int(value: Any) -> Optional[int]:
    """整数安全转换（fill_count 等），None/NaN → None。"""
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _has_column(conn: Any, table: str, column: str) -> bool:
    """判断表是否含指定列（向后兼容旧库缺列场景）。"""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


# ── fx 汇率回填（异常明细成交金额 USD 补全，与 report_aggregator 同源）────────

#: fill_bdib 汇率回填 CTE（替代临时表，兼容 READ 只读事务）。列名加 fxf_ 前缀避免与主表
#: OrderId/RouteId/order_as_of_date 列名冲突（主查询 SELECT 列表未加表别名限定）。
_ANOMALY_FX_CTE = (
    "WITH _fbfx AS ("
    "SELECT OrderId AS fxf_oid, RouteId AS fxf_rid, order_as_of_date AS fxf_oad, "
    "SUM(fill_volume * fx_rate) / NULLIF(SUM(fill_volume), 0) AS fb_fx "
    "FROM fill_bdib WHERE fx_rate IS NOT NULL "
    "AND order_as_of_date BETWEEN ? AND ? "
    "GROUP BY OrderId, RouteId, order_as_of_date) "
)


def _prepare_anomaly_fx(conn) -> bool:
    """探测 fill_bdib 汇率回填可行性（不再建临时表，返回是否可用）。

    无 fill_bdib 表时返回 False（向后兼容；test_anomaly_notional_usd_missing_fx
    的 fixture 即无 fill_bdib 表，notional_usd 仍按 tca.fx_rate 口径为空）。
    """
    try:
        has_fb = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fill_bdib' LIMIT 1"
        ).fetchone() is not None
    except Exception:
        has_fb = False
    return bool(has_fb)


def _anomaly_fx_join() -> str:
    """fill_bdib 汇率回填 LEFT JOIN 片段（回填可用时生效）。

    P3-4：表名改从 Config 常量取，避免硬编码与配置漂移断裂。
    """
    tca = Config.TCA_ROUTE_SUMMARY_TABLE
    return (
        " LEFT JOIN _fbfx"
        f" ON _fbfx.fxf_oid = {tca}.OrderId"
        f" AND _fbfx.fxf_rid = {tca}.RouteId"
        f" AND _fbfx.fxf_oad = {tca}.order_as_of_date"
    )


def _anomaly_notional_usd_expr(fbfx_ready: bool, has_fx: bool) -> str:
    """异常明细成交金额(USD) 表达式（含小计价单位货币 ÷100 修正）。

    Amount × 有效汇率；有效汇率 = COALESCE(tca.fx_rate, fill_bdib 回填 fb_fx)。
    USD/未知币种缺汇率按 1.0 兜底；非 USD 仍缺汇率时为 NULL（不虚高）。
    无 fx_rate 列时整体返回 NULL（向后兼容旧 schema）。
    """
    if not has_fx:
        return "NULL"
    minor = "CASE WHEN Currency IN ('GBp', 'ILs', 'ZAr') THEN 0.01 ELSE 1.0 END"
    tca = Config.TCA_ROUTE_SUMMARY_TABLE
    eff = (
        f"COALESCE({tca}.fx_rate, _fbfx.fb_fx)" if fbfx_ready else f"{tca}.fx_rate"
    )
    return (
        f"CASE WHEN {eff} IS NOT NULL THEN Amount * {eff} * {minor} "
        f"WHEN Currency IS NULL OR Currency = 'USD' THEN Amount * 1.0 "
        f"ELSE NULL END"
    )


# ── 全量明细导出（014：HTML 截断与审计导出分离）──────────────────────────────

#: 异常明细 CSV 列（与报告明细表列一致 + 数据质量标记，便于离线审计核对）
_ANOMALY_CSV_COLUMNS: tuple[str, ...] = (
    "order_id", "route_id", "date", "ticker", "exchange", "side",
    "broker", "algo", "currency",
    "notional_local", "notional_usd",
    "route_shares", "fill", "unfilled", "completion_rate",
    "par_rate", "order_par_rate", "fill_count",
    "pnl_vwap", "arrival_cost_bps", "wagner_is_bps", "opportunity_cost",
    "cost_cvar", "order_duration_sec",
    "recovery_truncated", "severity", "overfill", "order_par_gt100",
    "hit_rules",
)


def _format_hit(hit: dict[str, Any]) -> str:
    """命中规则的可读串：``标签 数值单位 (严重度)``。"""
    label = hit.get("label") or hit.get("key") or ""
    return f"{label} {hit.get('value')}{hit.get('unit')} ({hit.get('severity')})"


def export_anomaly_rows_csv(rows: list[dict[str, Any]], path: str | Path) -> Path:
    """把异常明细行（AnomalyRoute.__dict__ 形态）全量写入 CSV。

    使用 UTF-8-SIG 编码，Excel 可直接打开；命中规则拼接为单列 ``hit_rules``。
    供 HTML 报告以相对链接引用，实现「渲染截断、导出全量」的审计闭环。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(_ANOMALY_CSV_COLUMNS)
        for row in rows:
            values = [row.get(col) for col in _ANOMALY_CSV_COLUMNS[:-1]]
            values.append("; ".join(_format_hit(h) for h in row.get("hits") or []))
            writer.writerow(values)
    return target

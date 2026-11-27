"""执行简报聚合服务（230）。

面向「每日/每周/每月/每季/每年/自定义区间」的执行管理摘要：以 **订单** 为
主粒度，回答「这段时间执行了什么、完成得怎么样、成本在哪里、哪些单需要处理」。
与 ``trader_service``（订单复盘列表）和 ``report_aggregator``（期间 TCA 报告）
的分工：

- ``report_aggregator``：route 级、全台、审计与排名；
- ``trader_service``：order 级、分页明细、单笔复盘；
- 本模块：order 级、**聚合摘要**、按期间/维度切片的执行简报。

口径复用（禁止第二套实现）：
- 作用域/加权/金额回退：``monitoring.report_measure``；
- 订单级异常：``trader_metrics.compute_anomaly_summary`` +
  ``monitoring.anomaly_query`` 的同一套阈值引擎；
- 时间范围：``monitoring.time_range``（与报告/CLI 共用 last 预设解析）。

数据缺口（组合/账户、TIF、撤销状态、未成交原因、有效价差、显性费用）一律
在 payload 的 ``data_availability`` 中显式披露，不伪造、不静默省略。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any, Optional

from data_access.config import Config
from data_access.storage.connection import AccessTier, ConnectionManager

from . import trader_models as tmod
from . import trader_query as tq
from .monitoring import _common
from .monitoring import report_measure as rm
from .monitoring import time_range
from .monitoring.anomaly_query import (
    ThresholdRules,
    evaluate_metrics,
    order_rule_values,
)
from . import trader_metrics as tm

#: 简报口径版本（与报告/交易员视图同步演进）
BRIEF_SPEC_VERSION = "2026.11.27"

#: 期间预设（custom 由显式 start/end 表达，不进入 time_range 的 last 白名单）
PERIOD_PRESETS: tuple[str, ...] = ("day", "week", "month", "quarter", "year")

#: 期间展示文案
PERIOD_LABELS: dict[str, str] = {
    "day": "每日",
    "week": "每周",
    "month": "每月",
    "quarter": "每季",
    "year": "每年",
    "custom": "自定义区间",
}

#: 单例连接管理器（测试可整体替换；只读连接，mode=ro）
DEFAULT_MANAGER = ConnectionManager()

#: 维度筛选参数名 → tca_route_summary 列（与 trader_query 同语义：任一路由命中）
_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("trader", "TraderName"),
    ("ticker", "equ_ticker"),
    ("exchange", "Exchange"),
    ("side", "Side"),
    ("strategy_type", "StrategyType"),
    ("algo", "algo"),
    ("broker", "Broker"),
)

#: 方向取值归一：上游 EMSX 实测为 ``B`` / ``S``，API 与前端统一用 ``BUY`` / ``SELL``。
#: 筛选同时接受两套写法（任一别名命中即算命中），避免「界面选买入、库里是 B」静默空结果。
_SIDE_ALIASES: dict[str, tuple[str, ...]] = {
    "BUY": ("B", "BUY"),
    "B": ("B", "BUY"),
    "SELL": ("S", "SELL"),
    "S": ("S", "SELL"),
}


def _normalize_side(value: Any) -> Optional[str]:
    """``B`` / ``S`` / ``BUY`` / ``SELL`` → ``BUY`` / ``SELL``；未知值原样保留。"""
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in ("B", "BUY"):
        return "BUY"
    if text in ("S", "SELL"):
        return "SELL"
    return str(value)


def _side_condition(values: Optional[tuple[str, ...]]) -> tuple[str, list[Any]]:
    """方向筛选 HAVING 片段：把 BUY/SELL 与 B/S 展开为同一组别名。"""
    if not values:
        return "", []
    tokens: list[str] = []
    for value in values:
        aliases = _SIDE_ALIASES.get(str(value).strip().upper(), (str(value),))
        for alias in aliases:
            if alias not in tokens:
                tokens.append(alias)
    marks = ", ".join(["?"] * len(tokens))
    return (
        f"SUM(CASE WHEN UPPER(r.Side) IN ({marks}) THEN 1 ELSE 0 END) > 0",
        list(tokens),
    )


#: 数据可得性声明（缺口必须可见，与 K1–K4 的处理方式一致）
DATA_AVAILABILITY: tuple[dict[str, str], ...] = (
    {
        "key": "portfolio",
        "label": "组合 / 账户维度",
        "status": "unavailable",
        "reason": "tca_route_summary 无 Portfolio / Account 列，需上游管道补字段",
    },
    {
        "key": "tif",
        "label": "TIF / 订单类型",
        "status": "unavailable",
        "reason": "汇总表无 TimeInForce 列；StrategyType/algo 已用于类型分布",
    },
    {
        "key": "order_status",
        "label": "撤销 / 拒单状态",
        "status": "unavailable",
        "reason": "TCA 汇总只含已路由订单；订单状态在 EMSX / 运营库，尚未接入",
    },
    {
        "key": "unfilled_reason",
        "label": "未成交原因分类",
        "status": "unavailable",
        "reason": "无订单状态与算法暂停事件；本简报不做无证据的事后推断",
    },
    {
        "key": "effective_spread",
        "label": "有效价差",
        "status": "unavailable",
        "reason": "无报价级数据（K2）；BDIB 价差代理不等同 effective spread",
    },
    {
        "key": "explicit_fees",
        "label": "显性费用 / 返佣 / 税费",
        "status": "unavailable",
        "reason": "价格偏离口径（K1），不含费用项",
    },
    {
        "key": "order_rule_coverage",
        "label": "订单级异常规则覆盖",
        "status": "partial",
        "reason": "订单级仅评估 pnl_vwap / 完成率 / overfill / ADV 参与率 4 条；"
                  "区间参与率、日内波动、价格移动见 Report → 异常路由明细",
    },
    {
        "key": "fx",
        "label": "USD 换算",
        "status": "partial",
        "reason": "非 USD 且缺汇率时该订单不计入 USD 合计（未换算条数随附披露）",
    },
)

#: 简报固定脚注
BRIEF_NOTES: tuple[str, ...] = (
    "委托金额 = Σ(RouteShares × 价格回退链 × 汇率)；成交金额 = Σ(fill × p_avg × 汇率)。",
    "成本符号沿用上游有符号口径：负 = 不利（跑输基准），正 = 有利。",
    "完成率 = Σfill / ΣRouteShares；完成分桶按订单级聚合后的完成率划分。",
    "多路由订单的交易员 / 方向 / 算法 / 券商 / 策略维度取成交股数最大路由（dominant route）。",
    "加权指标为成交额加权（fill × p_avg）；不可得显示「—」，不按 0 解读。",
    "机会成本沿用上游有符号原值；待处理订单按绝对规模排序，不改变符号，也不套用 arrival/IS 的红绿语义。",
)


class DataNotReadyError(Exception):
    """期间内无 TCA 汇总（预设 last=day 且无数据等）→ 路由层 503。"""


# ── 期间与筛选解析 ─────────────────────────────────────────────────────────


def _resolve_period(
    conn,
    start_date: Optional[str],
    end_date: Optional[str],
    last: Optional[str],
    *,
    today: Optional[date] = None,
) -> time_range.TimeRange:
    """解析期间（与报告/CLI 共用 ``time_range``；last=day 需库内已有数据）。"""
    latest = tq.query_latest_order_date(conn)
    try:
        return time_range.resolve_time_range(
            start_date, end_date, last, today=today, latest_data_date=latest,
        )
    except ValueError as exc:
        if "last day" in str(exc) or "无数据" in str(exc):
            raise DataNotReadyError(
                "tca_route_summary 无可用交易日（数据尚未生成）；"
                "数据更新维护的唯一写入方是独立仓库 EMSXDataPipeline。"
            ) from exc
        raise


def _parse_multi(raw: Optional[str]) -> Optional[tuple[str, ...]]:
    """逗号分隔多值 → 去空白去重元组（与交易员视图同一语义）。"""
    if not raw:
        return None
    values = tuple(dict.fromkeys(v.strip() for v in raw.split(",") if v.strip()))
    return values or None


def _filters(
    period: time_range.TimeRange,
    *,
    trader: Optional[str] = None,
    ticker: Optional[str] = None,
    exchange: Optional[str] = None,
    side: Optional[str] = None,
    strategy_type: Optional[str] = None,
    algo: Optional[str] = None,
    broker: Optional[str] = None,
) -> tmod.TraderFilters:
    """复用 ``TraderFilters`` 承载维度多值筛选（与交易员视图同语义）。"""
    return tmod.TraderFilters(
        start_date=period.start_date,
        end_date=period.end_date,
        trader=_parse_multi(trader),
        ticker=_parse_multi(ticker),
        exchange=_parse_multi(exchange),
        side=_parse_multi(side),
        strategy_type=_parse_multi(strategy_type),
        algo=_parse_multi(algo),
        broker=_parse_multi(broker),
    )


# ── SQL（订单级聚合 + USD 换算）────────────────────────────────────────────


def _fx_context(conn) -> tuple[str, str, str, list[Any]]:
    """返回 (CTE 前缀, LEFT JOIN, 有效汇率表达式, 需前置的参数)。

    换算规则的表达式本身来自 ``report_measure``（唯一实现）；本函数只决定
    「能否用 fill_bdib 回填汇率」。旧 schema 无 ``fx_rate`` 时不假装能换算：
    非 USD 订单的 USD 金额为 NULL，并在 payload 中披露未换算条数。
    """
    columns = _common.tca_summary_columns(conn)
    has_fx = "fx_rate" in columns
    # 回填需要 fill_bdib 同时具备三列；仅判表存在会把「表在但 schema 旧」误判为可回填，
    # 导致整条 SQL 失败而被降级成空简报（数字静默消失）。
    has_fill_bdib = (
        _common.table_exists(conn, "fill_bdib")
        and _common.has_column(conn, "fill_bdib", "fill_volume")
        and _common.has_column(conn, "fill_bdib", "fx_rate")
    )
    if has_fx and has_fill_bdib:
        effective = "COALESCE(r.fx_rate, _fbfx.fb_fx)"
        join = (
            " LEFT JOIN _fbfx"
            " ON _fbfx.OrderId = r.OrderId"
            " AND _fbfx.RouteId = r.RouteId"
            " AND _fbfx.fxf_oad = r.order_as_of_date"
        )
        return rm.fbfx_cte(), join, effective, []
    if has_fx:
        return "", "", "r.fx_rate", []
    # 无 fx 列：USD 按 1.0，其余币种 NULL（不虚高）；无 CTE 参数
    return "", "", "NULL", []


def _order_sql(conn, filters: tmod.TraderFilters) -> tuple[str, list[Any]]:
    """订单级聚合 SQL：一次扫描算出概览 / 成本 / 未成交所需列。"""
    columns = _common.tca_summary_columns(conn)
    price = rm.unfilled_price_expr(columns) or "NULL"
    cte, join, effective, _ = _fx_context(conn)
    fx = rm.usd_fx_expr(effective, "r.Currency")
    table = Config.TCA_ROUTE_SUMMARY_TABLE
    # side 走别名条件（B/S 与 BUY/SELL 等价），其余维度复用交易员视图的任一路由命中语义
    having, having_params = tq._dim_having(replace(filters, side=None))
    side_having, side_params = _side_condition(filters.side)
    if side_having:
        having = f"{having} AND {side_having}" if having else f" HAVING {side_having}"
        having_params = [*having_params, *side_params]

    # 维度头用 ROW_NUMBER 显式取「成交股数最大路由」（dominant route）：
    # 不用 SQLite 的裸列 + MAX() 语义 —— 本查询还有 MAX(par_rate) 等聚合，
    # 多个 max() 聚合时裸列可能来自任一极值行，会把交易员 / 算法头翻到其他路由。
    ranked = f"""
        _ranked AS (
            SELECT r.*, {fx} AS _fx,
                   ROW_NUMBER() OVER (
                       PARTITION BY r.OrderId, r.order_as_of_date
                       ORDER BY COALESCE(r.fill, -1) DESC, r.RouteId ASC
                   ) AS _rn
            FROM {table} r
            {join}
            WHERE r.order_as_of_date BETWEEN ? AND ?
        )
    """
    with_clause = (cte + ", " if cte else "WITH ") + ranked
    sql = f"""
        SELECT
            r.OrderId AS OrderId,
            r.order_as_of_date AS order_as_of_date,
            MAX(CASE WHEN r._rn = 1 THEN r.equ_ticker END) AS equ_ticker,
            MAX(CASE WHEN r._rn = 1 THEN r.Exchange END) AS exchange,
            MAX(CASE WHEN r._rn = 1 THEN r.Side END) AS side,
            MAX(CASE WHEN r._rn = 1 THEN r.StrategyType END) AS strategy_type,
            MAX(CASE WHEN r._rn = 1 THEN r.algo END) AS algo,
            MAX(CASE WHEN r._rn = 1 THEN r.Broker END) AS broker,
            MAX(CASE WHEN r._rn = 1 THEN r.TraderName END) AS trader_name,
            MAX(CASE WHEN r._rn = 1 THEN r.Currency END) AS currency,
            MAX(CASE WHEN r._rn = 1 THEN r.p_decision END) AS p_decision,
            MAX(CASE WHEN r._rn = 1 THEN r.p_arrival END) AS p_arrival,
            MAX(CASE WHEN r._rn = 1 THEN r.p_close END) AS p_close,
            MAX(CASE WHEN r._rn = 1 THEN r.LimitPrice END) AS limit_price,
            COUNT(*) AS route_count,
            COUNT(DISTINCT r.Side) AS n_side,
            COUNT(DISTINCT r.StrategyType) AS n_strategy,
            COUNT(DISTINCT r.algo) AS n_algo,
            COUNT(DISTINCT r.Broker) AS n_broker,
            COUNT(DISTINCT r.TraderName) AS n_trader,
            SUM(COALESCE(r.fill_count, 0)) AS fill_count,
            SUM(COALESCE(r.RouteShares, 0)) AS route_shares,
            SUM(COALESCE(r.fill, 0)) AS fill,
            SUM(r.Amount) AS amount_shares,
            SUM(r.opportunity_cost) AS opportunity_cost_local,
            SUM(r.delay_cost) AS delay_cost_local,
            SUM(r.trading_cost) AS trading_cost_local,
            SUM(r.wagner_is) AS wagner_is_local,
            MAX(r.par_rate) AS max_par_rate,
            MAX(r.order_duration_sec) AS order_duration_sec,
            {rm.weighted_avg_sql("arrival_cost_bps")} AS arrival_cost_bps,
            {rm.weighted_avg_sql("wagner_is_bps")} AS wagner_is_bps,
            {rm.weighted_avg_sql("pnl_vwap")} AS pnl_vwap,
            SUM(CASE WHEN r.fill IS NOT NULL AND r.p_avg IS NOT NULL
                     THEN r.fill * r.p_avg END) AS fill_notional_local,
            SUM(CASE WHEN r.fill IS NOT NULL AND r.p_avg IS NOT NULL
                     THEN r.fill * r.p_avg * r._fx END) AS fill_notional_usd,
            SUM(r.RouteShares * ({price}) * r._fx) AS order_notional_usd,
            SUM(CASE WHEN r.RouteShares > COALESCE(r.fill, 0)
                     THEN (r.RouteShares - COALESCE(r.fill, 0))
                          * ({price}) * r._fx ELSE 0 END) AS unfilled_notional_usd,
            SUM(CASE WHEN r.RouteShares > COALESCE(r.fill, 0)
                     THEN r.RouteShares - COALESCE(r.fill, 0) ELSE 0 END) AS unfilled_shares,
            SUM(CASE WHEN r.RouteShares > COALESCE(r.fill, 0)
                     AND ({price}) IS NULL THEN 1 ELSE 0 END) AS unpriced_routes,
            {rm.zero_fill_count_expr()} AS zero_fill_routes,
            SUM(CASE WHEN COALESCE(r.fill, 0) > r.RouteShares
                     THEN 1 ELSE 0 END) AS overfill_routes,
            SUM(COALESCE(r.opportunity_cost, 0) * r._fx) AS opportunity_cost_usd,
            SUM(COALESCE(r.delay_cost, 0) * r._fx) AS delay_cost_usd,
            SUM(COALESCE(r.trading_cost, 0) * r._fx) AS trading_cost_usd,
            SUM(COALESCE(r.wagner_is, 0) * r._fx) AS wagner_is_usd
        FROM _ranked r
        GROUP BY r.OrderId, r.order_as_of_date
        {having}
    """
    params: list[Any] = [filters.start_date, filters.end_date]
    if cte:
        # _fbfx 与 _ranked 各自消费一组日期参数（均为 BETWEEN ? AND ?）
        params = [filters.start_date, filters.end_date] + params
    params.extend(having_params)
    return with_clause + sql, params


def _query_orders(conn, filters: tmod.TraderFilters) -> list[dict[str, Any]]:
    """执行订单级聚合 SQL。

    查询失败**不**降级为空结果：静默 0 会把「SQL / schema 出错」伪装成
    「这段时间没有委托」，与「不可得必须可见」的约定冲突。表缺失由调用方
    先判定并给出 ``data_source_warning``，其余异常向上抛给路由层转 500。
    """
    sql, params = _order_sql(conn, filters)
    cursor = conn.execute(sql, params)
    names = [d[0] for d in cursor.description]
    rows = [dict(zip(names, row)) for row in cursor.fetchall()]
    for row in rows:
        _derive_row(row)
    return rows


def _derive_row(row: dict[str, Any]) -> None:
    """把 SQL 行补成 Python 聚合所需的派生字段（完成率 / 质量旗标）。"""
    route_shares = _float(row.get("route_shares"))
    fill = _float(row.get("fill")) or 0.0
    row["order_id"] = str(row.get("OrderId") or "")
    row["side"] = _normalize_side(row.get("side"))
    # 完成率唯一实现（与 trader_query / analyze-orders 共用，避免三套口径）
    row["completion"] = rm.completion_ratio(fill, route_shares)
    # 成交均价（本币）：成交金额 / 成交股数；零成交为 None。
    fill_notional_local = _float(row.get("fill_notional_local"))
    row["vwap"] = (
        fill_notional_local / fill if fill > 0 and fill_notional_local is not None else None
    )
    row["flag_overfill"] = 1 if route_shares is not None and fill > route_shares else 0
    amount = _float(row.get("amount_shares"))
    row["flag_amount_mismatch"] = (
        1
        if amount is not None and route_shares is not None
        and abs(amount - route_shares) > 0.005 * max(abs(amount), 1.0)
        else 0
    )
    row["flag_cost_missing"] = (
        1
        if row.get("arrival_cost_bps") is None
        or row.get("wagner_is_bps") is None
        or row.get("opportunity_cost_local") is None
        else 0
    )
    fill_count = _float(row.get("fill_count")) or 0.0
    row["flag_single_fill"] = 1 if fill_count < 2 else 0


# ── 聚合 ───────────────────────────────────────────────────────────────────


def _float(value: Any) -> Optional[float]:
    return _common.to_float(value)


def _int(value: Any) -> Optional[int]:
    return _common.to_int(value)


def _sum(values: list[Optional[float]]) -> Optional[float]:
    """可空求和：全空返回 None（不把「不可得」写成 0）。"""
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _weighted(rows: list[dict[str, Any]], field: str) -> Optional[float]:
    """成交额加权均值（权重 fill_notional_local；缺权重的行不参与）。"""
    return rm.weighted_mean(
        [_float(r.get(field)) for r in rows],
        [_float(r.get("fill_notional_local")) for r in rows],
    )


def _completion(rows: list[dict[str, Any]]) -> Optional[float]:
    fill = _sum([_float(r.get("fill")) for r in rows])
    shares = _sum([_float(r.get("route_shares")) for r in rows])
    return fill / shares if fill is not None and shares and shares > 0 else None


def _block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """一组订单的汇总块（买/卖、策略、交易员共用）。"""
    return {
        "orders": len(rows),
        "route_count": sum(_int(r.get("route_count")) or 0 for r in rows),
        "order_shares": _sum([_float(r.get("route_shares")) for r in rows]),
        "fill_shares": _sum([_float(r.get("fill")) for r in rows]),
        "order_notional_usd": _sum([_float(r.get("order_notional_usd")) for r in rows]),
        "fill_notional_usd": _sum([_float(r.get("fill_notional_usd")) for r in rows]),
        "unfilled_notional_usd": _sum(
            [_float(r.get("unfilled_notional_usd")) for r in rows]
        ),
        "completion": _completion(rows),
        "arrival_cost_bps": _weighted(rows, "arrival_cost_bps"),
        "wagner_is_bps": _weighted(rows, "wagner_is_bps"),
        "pnl_vwap": _weighted(rows, "pnl_vwap"),
        "opportunity_cost_usd": _sum(
            [_float(r.get("opportunity_cost_usd")) for r in rows]
        ),
        "delay_cost_usd": _sum([_float(r.get("delay_cost_usd")) for r in rows]),
        "trading_cost_usd": _sum([_float(r.get("trading_cost_usd")) for r in rows]),
    }


def _group(rows: list[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get(field) or "UNKNOWN")
        grouped.setdefault(key, []).append(row)
    return grouped


def _side_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """买卖拆分 + 跨方向订单计数（多路由方向不一致时单列）。"""
    result: dict[str, Any] = {}
    for side in ("BUY", "SELL"):
        side_rows = [r for r in rows if str(r.get("side") or "").upper() == side]
        result[side.lower()] = _block(side_rows)
    other = [r for r in rows if str(r.get("side") or "").upper() not in ("BUY", "SELL")]
    result["other"] = _block(other)
    result["mixed_orders"] = sum(
        1 for r in rows if (_int(r.get("n_side")) or 0) > 1
    )
    return result


_COMPLETION_BUCKETS: tuple[tuple[str, str], ...] = (
    ("complete", "完全成交"),
    ("overfill", "超成交（数据矛盾）"),
    ("partial", "部分成交"),
    ("zero", "零成交"),
)


def _bucket_key(row: dict[str, Any]) -> str:
    completion = _float(row.get("completion"))
    fill = _float(row.get("fill")) or 0.0
    if fill <= 0 or completion is None:
        return "zero"
    if completion > 1.0 + 1e-9:
        return "overfill"
    if completion >= 1.0 - 1e-9:
        return "complete"
    return "partial"


def _completion_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total_orders = len(rows)
    total_notional = _sum([_float(r.get("order_notional_usd")) for r in rows])
    buckets = []
    for key, label in _COMPLETION_BUCKETS:
        bucket_rows = [r for r in rows if _bucket_key(r) == key]
        block = _block(bucket_rows)
        buckets.append({
            "key": key,
            "label": label,
            "orders": block["orders"],
            "order_shares": block["order_shares"],
            "fill_shares": block["fill_shares"],
            "order_notional_usd": block["order_notional_usd"],
            "completion": block["completion"],
            "share_of_orders": (
                block["orders"] / total_orders if total_orders else None
            ),
            "share_of_notional": (
                block["order_notional_usd"] / total_notional
                if block["order_notional_usd"] is not None and total_notional
                else None
            ),
        })
    return buckets


def _dimension_rows(rows: list[dict[str, Any]], field: str, limit: int) -> list[dict[str, Any]]:
    """按维度分组并附占比；按订单数降序、金额降序取前 N。"""
    total_orders = len(rows)
    grouped = _group(rows, field)
    items = []
    for key, group_rows in grouped.items():
        block = _block(group_rows)
        items.append({
            "key": key,
            "label": key,
            "orders": block["orders"],
            "route_count": block["route_count"],
            "order_notional_usd": block["order_notional_usd"],
            "fill_notional_usd": block["fill_notional_usd"],
            "completion": block["completion"],
            "arrival_cost_bps": block["arrival_cost_bps"],
            "wagner_is_bps": block["wagner_is_bps"],
            "opportunity_cost_usd": block["opportunity_cost_usd"],
            "share_of_orders": block["orders"] / total_orders if total_orders else None,
        })
    items.sort(
        key=lambda item: (
            -(item["orders"] or 0),
            -(item["order_notional_usd"] or 0.0),
        )
    )
    return items[:limit]


def _top_orders(rows: list[dict[str, Any]], top_n: int) -> dict[str, list[dict[str, Any]]]:
    """待处理订单 Top N：成本最不利 / 未成交金额最大 / 机会成本最不利。"""

    def serialize(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "order_id": row.get("order_id"),
            "order_as_of_date": row.get("order_as_of_date"),
            "ticker": row.get("equ_ticker"),
            "exchange": row.get("exchange"),
            "side": row.get("side"),
            "strategy_type": row.get("strategy_type"),
            "algo": row.get("algo"),
            "broker": row.get("broker"),
            "trader_name": row.get("trader_name"),
            "route_count": _int(row.get("route_count")),
            "order_shares": _float(row.get("route_shares")),
            "fill_shares": _float(row.get("fill")),
            "completion": _float(row.get("completion")),
            "vwap": _float(row.get("vwap")),
            "arrival_cost_bps": _float(row.get("arrival_cost_bps")),
            "wagner_is_bps": _float(row.get("wagner_is_bps")),
            "pnl_vwap": _float(row.get("pnl_vwap")),
            "order_notional_usd": _float(row.get("order_notional_usd")),
            "fill_notional_usd": _float(row.get("fill_notional_usd")),
            "unfilled_shares": _float(row.get("unfilled_shares")),
            "unfilled_notional_usd": _float(row.get("unfilled_notional_usd")),
            "opportunity_cost_usd": _float(row.get("opportunity_cost_usd")),
        }

    arrival = sorted(
        (r for r in rows if _float(r.get("arrival_cost_bps")) is not None),
        key=lambda r: _float(r.get("arrival_cost_bps")) or 0.0,
    )[:top_n]
    unfilled = sorted(
        (r for r in rows
         if (_float(r.get("unfilled_notional_usd")) or 0.0) > 0),
        key=lambda r: _float(r.get("unfilled_notional_usd")) or 0.0,
        reverse=True,
    )[:top_n]
    # 机会成本的上游符号方向对不同方向不统一（实测 BUY/SELL 均出现正负混合），
    # 因此按**绝对规模**排序，避免把「符号解释」当成事实；原值照常展示。
    opportunity = sorted(
        (r for r in rows if _float(r.get("opportunity_cost_usd")) is not None),
        key=lambda r: abs(_float(r.get("opportunity_cost_usd")) or 0.0),
        reverse=True,
    )[:top_n]
    return {
        "by_arrival": [serialize(r) for r in arrival],
        "by_unfilled": [serialize(r) for r in unfilled],
        "by_opportunity": [serialize(r) for r in opportunity],
    }


def _anomaly(
    rows: list[dict[str, Any]],
    thresholds: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """订单级异常摘要（复用交易员视图同一套阈值引擎，不复制常量）。"""
    rules = ThresholdRules.from_payload(thresholds)
    return tm.compute_anomaly_summary(
        rows, lambda row: evaluate_metrics(order_rule_values(row), rules),
    )


def _coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fill_notional = [_float(r.get("fill_notional_usd")) for r in rows]
    order_notional = [_float(r.get("order_notional_usd")) for r in rows]
    fx_missing = sum(
        1
        for r in rows
        if (_float(r.get("fill_notional_local")) or 0.0) > 0
        and _float(r.get("fill_notional_usd")) is None
    )
    unpriced_orders = sum(
        1
        for r in rows
        if (_float(r.get("route_shares")) or 0.0) > 0
        and _float(r.get("order_notional_usd")) is None
    )
    return {
        "orders": len(rows),
        "symbols": len({str(r.get("equ_ticker")) for r in rows if r.get("equ_ticker")}),
        "traders": len({str(r.get("trader_name")) for r in rows if r.get("trader_name")}),
        "exchanges": sorted({str(r.get("exchange")) for r in rows if r.get("exchange")}),
        "route_count": sum(_int(r.get("route_count")) or 0 for r in rows),
        "fill_notional_usd": _sum(fill_notional),
        "order_notional_usd": _sum(order_notional),
        "fx_missing_orders": fx_missing,
        "order_notional_unpriced_orders": unpriced_orders,
        "unpriced_routes": sum(_int(r.get("unpriced_routes")) or 0 for r in rows),
    }


def _period_payload(period: time_range.TimeRange) -> dict[str, Any]:
    preset = period.preset or "custom"
    return {
        "start_date": period.start_date,
        "end_date": period.end_date,
        "preset": preset,
        "label": PERIOD_LABELS.get(preset, preset),
        "as_of_date": period.as_of_date,
    }


def _filters_payload(filters: tmod.TraderFilters) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, _ in _DIMENSIONS:
        values = getattr(filters, key)
        payload[key] = list(values) if values else []
    return payload


def build_brief(
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    last: Optional[str] = None,
    trader: Optional[str] = None,
    ticker: Optional[str] = None,
    exchange: Optional[str] = None,
    side: Optional[str] = None,
    strategy_type: Optional[str] = None,
    algo: Optional[str] = None,
    broker: Optional[str] = None,
    top_n: int = 10,
    today: Optional[date] = None,
    thresholds: Optional[dict[str, Any]] = None,
    mgr: Optional[ConnectionManager] = None,
) -> dict[str, Any]:
    """组装执行简报 payload（单次只读连接内完成）。"""
    manager = mgr or DEFAULT_MANAGER
    conn = manager.get_connection("fill_bdib", AccessTier.READ)
    table_ready = False
    try:
        period = _resolve_period(conn, start_date, end_date, last, today=today)
        filters = _filters(
            period,
            trader=trader, ticker=ticker, exchange=exchange, side=side,
            strategy_type=strategy_type, algo=algo, broker=broker,
        )
        table_ready = _common.tca_summary_exists(conn)
        rows = _query_orders(conn, filters) if table_ready else []
    finally:
        conn.close()

    coverage = _coverage(rows)
    overview = _block(rows)
    sides = _side_split(rows)
    zero_fill_orders = sum(1 for r in rows if _bucket_key(r) == "zero")
    payload: dict[str, Any] = {
        "spec_version": BRIEF_SPEC_VERSION,
        "generated_at": datetime.now().isoformat(),
        "period": _period_payload(period),
        "filters": _filters_payload(filters),
        "coverage": coverage,
        "overview": {
            **overview,
            "zero_fill_orders": zero_fill_orders,
            "order_notional_usd": coverage["order_notional_usd"],
            "fill_notional_usd": coverage["fill_notional_usd"],
        },
        "sides": sides,
        "completion_buckets": _completion_buckets(rows),
        "strategy_mix": _dimension_rows(rows, "strategy_type", 20),
        "algo_mix": _dimension_rows(rows, "algo", 20),
        "broker_mix": _dimension_rows(rows, "broker", 20),
        "top_traders": _dimension_rows(rows, "trader_name", 20),
        "top_orders": _top_orders(rows, max(1, top_n)),
        "anomaly": _anomaly(rows, thresholds),
        "data_availability": [dict(item) for item in DATA_AVAILABILITY],
        "notes": list(BRIEF_NOTES),
    }
    if not table_ready:
        payload["data_source_warning"] = (
            "tca_route_summary 表/视图不存在：本次简报为空，"
            "不等于期间内没有委托。请先运行数据管道 S5.5。"
        )
    return payload

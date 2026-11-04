"""交易员复盘台只读 SQL 层（方案 §3.3）。

全部参数化（? 占位符）；排序字段走白名单映射，禁止拼接用户输入。
聚合语义与 `TcaQueryService._aggregate_order`（analyze-orders）对齐：
货币成本 SUM、bps 成交额加权（权重 = fill × p_avg）、完成率 = Σfill/ΣRouteShares；
维度头取成交股数最大路由（dominant route，多值标 mixed，禁止 MIN() 取维度）。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from data_access.config import Config

logger = logging.getLogger(__name__)

#: 排序白名单：sort 枚举 → SQL 列（用户输入只允许命中键名，不进 SQL 文本）
SORT_COLUMNS: dict[str, str] = {
    "date": "order_as_of_date",
    "completion": "completion",
    "arrival_bps": "arrival_cost_bps",
    "opp_cost": "opportunity_cost",
    "notional": "notional",
    "route_count": "route_count",
}
#: 排序方向白名单
SORT_DIRS: tuple[str, ...] = ("asc", "desc")
#: 分页上限（§3.4.1：limit ≤ 200）
MAX_LIMIT = 200

#: 维度筛选参数名 → tca_route_summary 列（多路由任一路由命中即命中订单）
_DIM_COLUMNS: dict[str, str] = {
    "trader": "TraderName",
    "ticker": "equ_ticker",
    "side": "Side",
    "strategy_type": "StrategyType",
    "algo": "algo",
    "broker": "Broker",
}

#: 完成率分桶 → SQL 条件（作用于聚合后的 completion）
_BUCKET_SQL: dict[str, str] = {
    "lt50": "completion < 0.5",
    "50to80": "completion >= 0.5 AND completion < 0.8",
    "80to100": "completion >= 0.8 AND completion < 1.0",
    "eq100": "completion = 1.0",
    "gt100": "completion > 1.0",
}

#: 质量筛选 → SQL 条件（与 trader_metrics.quality_flags 同界）
_QUALITY_SQL: dict[str, str] = {
    "clean": (
        "flag_overfill = 0 AND flag_amount_mismatch = 0 AND flag_cost_missing = 0 "
        "AND flag_single_fill = 0 AND (max_par_rate IS NULL OR max_par_rate <= 1.0)"
    ),
    "overfill": "flag_overfill = 1",
    "cost_missing": "flag_cost_missing = 1",
    "par_suspect": "max_par_rate > 1.0",
    "single_fill": "flag_single_fill = 1",
}


def _dim_having(filters) -> tuple[str, list[Any]]:
    """维度多值过滤（任一路由命中）→ GROUP BY 后的 HAVING 条件。

    用 ``MAX(CASE WHEN col IN (...) THEN 1 END) = 1`` 表达「组内存在匹配路由」，
    指标仍按全部路由聚合（方案 §4.1）。
    """
    parts: list[str] = []
    params: list[Any] = []
    for name, column in _DIM_COLUMNS.items():
        raw = getattr(filters, name)
        # 直接构造 TraderFilters 时允许传字符串（仅一个值），归一为元组
        values = (raw,) if isinstance(raw, str) else raw
        if values:
            marks = ", ".join(["?"] * len(values))
            parts.append(f"MAX(CASE WHEN r.{column} IN ({marks}) THEN 1 ELSE 0 END) = 1")
            params.extend(values)
    return (" HAVING " + " AND ".join(parts)) if parts else "", params


def _agg_select() -> str:
    """agg 内层：单趟 GROUP BY 订单聚合 + 派生列（completion/notional/质量旗标）。

    bps 加权权重 = fill × p_avg（与 analyze-orders._weighted_bps 同口径）。
    维度头取 fill 最大路由（dominant）：借助 SQLite「单个 MAX 聚合时裸列取自
    该 max 行」的语义（MAX(r.fill) 与裸列同查），免去窗口函数与二次 JOIN；
    route_count / 多值计数为 GROUP BY 聚合（SQLite 不支持 COUNT(DISTINCT) OVER）。
    """
    return """
        SELECT r.OrderId, r.order_as_of_date,
               r.equ_ticker, r.Exchange AS exchange, r.Side AS side,
               r.StrategyType AS strategy_type, r.algo, r.Broker AS broker,
               r.TraderName AS trader_name,
               r.p_decision, r.p_arrival, r.p_close,
               r.LimitPrice AS limit_price, r.Currency AS currency,
               r.par_rate AS par_rate,
               MAX(r.fill) AS max_fill,
               COUNT(*) AS route_count,
               COUNT(DISTINCT r.StrategyType) AS n_strategy,
               COUNT(DISTINCT r.algo) AS n_algo,
               COUNT(DISTINCT r.Broker) AS n_broker,
               COUNT(DISTINCT r.TraderName) AS n_trader,
               SUM(COALESCE(r.fill_count, 0)) AS fill_count,
               SUM(COALESCE(r.RouteShares, 0)) AS route_shares,
               SUM(COALESCE(r.fill, 0)) AS fill,
               SUM(r.Amount) AS amount_shares,
               SUM(r.opportunity_cost) AS opportunity_cost,
               SUM(r.delay_cost) AS delay_cost,
               SUM(r.trading_cost) AS trading_cost,
               SUM(r.wagner_is) AS wagner_is,
               MAX(r.cost_cvar) AS cost_cvar,
               MAX(r.order_duration_sec) AS order_duration_sec,
               -- 210 §4.7：peer「成交速度」维度取入库的股/分钟口径（无需逐笔）
               MAX(r.exec_rate_shares_per_min) AS exec_rate_shares_per_min,
               MAX(r.par_rate) AS max_par_rate,
               SUM(CASE WHEN r.p_avg IS NOT NULL THEN r.fill * r.p_avg END)
                 / NULLIF(SUM(CASE WHEN r.p_avg IS NOT NULL THEN r.fill END), 0) AS vwap,
               SUM(CASE WHEN r.p_avg IS NOT NULL THEN r.fill * r.p_avg END) AS notional,
               SUM(CASE WHEN r.arrival_cost_bps IS NOT NULL
                         AND r.fill IS NOT NULL AND r.p_avg IS NOT NULL
                        THEN r.arrival_cost_bps * r.fill * r.p_avg END)
                 / NULLIF(SUM(CASE WHEN r.arrival_cost_bps IS NOT NULL
                         AND r.fill IS NOT NULL AND r.p_avg IS NOT NULL
                        THEN r.fill * r.p_avg END), 0) AS arrival_cost_bps,
               SUM(CASE WHEN r.wagner_is_bps IS NOT NULL
                         AND r.fill IS NOT NULL AND r.p_avg IS NOT NULL
                        THEN r.wagner_is_bps * r.fill * r.p_avg END)
                 / NULLIF(SUM(CASE WHEN r.wagner_is_bps IS NOT NULL
                         AND r.fill IS NOT NULL AND r.p_avg IS NOT NULL
                        THEN r.fill * r.p_avg END), 0) AS wagner_is_bps,
               -- 210 §4.11：订单级 pnl_vwap（按成交股数加权）供订单级阈值评估；
               -- pnl_vwap 是每股价差，权重用 fill 而非成交额（与路由级口径一致）
               SUM(CASE WHEN r.pnl_vwap IS NOT NULL AND r.fill IS NOT NULL
                        THEN r.pnl_vwap * r.fill END)
                 / NULLIF(SUM(CASE WHEN r.pnl_vwap IS NOT NULL AND r.fill IS NOT NULL
                        THEN r.fill END), 0) AS pnl_vwap
    """


def _outer_select() -> str:
    """外层：派生 completion 与质量旗标（与 trader_metrics.quality_flags 同界）。"""
    return """
        SELECT *,
               (n_strategy > 1 OR n_algo > 1 OR n_broker > 1 OR n_trader > 1) AS mixed,
               CASE WHEN route_shares > 0 THEN fill * 1.0 / route_shares END AS completion,
               CASE WHEN fill > route_shares THEN 1 ELSE 0 END AS flag_overfill,
               CASE WHEN amount_shares IS NOT NULL
                     AND ABS(amount_shares - route_shares)
                         > 0.005 * MAX(ABS(amount_shares), 1.0)
                    THEN 1 ELSE 0 END AS flag_amount_mismatch,
               CASE WHEN arrival_cost_bps IS NULL OR wagner_is_bps IS NULL
                     OR opportunity_cost IS NULL THEN 1 ELSE 0 END AS flag_cost_missing,
               CASE WHEN fill_count < 2 THEN 1 ELSE 0 END AS flag_single_fill
        FROM (
    """


def order_rows_sql(filters) -> tuple[str, list[Any]]:
    """订单列表 SQL（排序白名单 + 完成率桶 / 质量筛选 + 稳定 tie-break）。

    单趟 GROUP BY（无 CTE / 无窗口函数）：维度多值过滤用 HAVING 表达
    「任一路由命中」，维度头取 fill 最大路由（MAX(r.fill) 裸列语义）。
    """
    t = Config.TCA_ROUTE_SUMMARY_TABLE
    having, having_params = _dim_having(filters)
    order_filter = " AND r.OrderId = ?" if filters.order_id else ""
    params: list[Any] = [filters.start_date, filters.end_date]
    if filters.order_id:
        params.append(filters.order_id)
    params.extend(having_params)
    inner = f"""
        {_agg_select()}
          FROM {t} r
          WHERE r.order_as_of_date BETWEEN ? AND ?{order_filter}
          GROUP BY r.OrderId, r.order_as_of_date{having}
        )
        """
    where = ""
    if filters.completion_bucket:
        where += f" WHERE {_BUCKET_SQL[filters.completion_bucket]} AND completion IS NOT NULL"
    if filters.quality and filters.quality != "all":
        clause = _QUALITY_SQL[filters.quality]
        where += f" {'AND' if where else 'WHERE'} {clause}"
    column = SORT_COLUMNS[filters.sort]
    direction = "DESC" if filters.sort_dir == "desc" else "ASC"
    tail = f"{_outer_select()}{inner} AS agg_rows{where} ORDER BY {column} {direction}, OrderId ASC"
    return tail, params


def query_order_rows(conn, filters) -> list[dict[str, Any]]:
    """执行订单列表 SQL，返回聚合行 dict 列表（分页由 service 层切片）。"""
    sql, params = order_rows_sql(filters)
    try:
        cursor = conn.execute(sql, params)
    except Exception as exc:  # 表缺失/旧 schema → 空结果（009 降级）
        logger.warning("trader 订单查询失败（返回空列表）: %s", exc)
        return []
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def query_filter_options(
    conn,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    ticker_prefix: Optional[str] = None,
) -> dict[str, list[str]]:
    """筛选下拉（§3.4.5）：traders/strategy_types 逐查询；其余复用维度表。"""
    result = _dims_options(conn)
    result["traders"] = _distinct(conn, "TraderName", start_date, end_date)
    result["strategy_types"] = _distinct(conn, "StrategyType", start_date, end_date)
    result["symbols"] = _symbols(conn, start_date, end_date, ticker_prefix)
    return result


def _dims_options(conn) -> dict[str, list[str]]:
    """维度表下拉（缺失时回退空表，由 _distinct/_symbols 兜底补齐）。"""
    from CostView.src.monitoring.report_dims import get_filter_options

    try:
        return dict(get_filter_options(conn=conn) or {})
    except Exception as exc:
        logger.warning("维度表不可用，回退 DISTINCT: %s", exc)
        return {}


def _distinct(
    conn, column: str,
    start_date: Optional[str], end_date: Optional[str],
    limit: int = 200,
) -> list[str]:
    """tca_route_summary 的 DISTINCT 取值（可选日期范围，按值升序）。"""
    sql = f"SELECT DISTINCT {column} FROM {Config.TCA_ROUTE_SUMMARY_TABLE} WHERE {column} IS NOT NULL"
    params: list[Any] = []
    if start_date and end_date:
        sql += " AND order_as_of_date BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    sql += f" ORDER BY {column} ASC LIMIT ?"
    params.append(limit)
    try:
        return [str(r[0]) for r in conn.execute(sql, params).fetchall()]
    except Exception as exc:
        logger.warning("DISTINCT %s 失败（返回空）: %s", column, exc)
        return []


def _symbols(
    conn, start_date: Optional[str], end_date: Optional[str], prefix: Optional[str],
) -> list[str]:
    """ticker 自动补全：优先维度表全量，带前缀/无维度表时回退 DISTINCT LIKE。"""
    if not prefix:
        from CostView.src.monitoring.report_dims import get_filter_options

        try:
            options = get_filter_options(conn=conn) or {}
            if options.get("symbols"):
                return list(options["symbols"])
        except Exception:
            pass
    like = f"{prefix}%" if prefix else "%"
    sql = (
        f"SELECT DISTINCT equ_ticker FROM {Config.TCA_ROUTE_SUMMARY_TABLE} "
        "WHERE equ_ticker IS NOT NULL AND equ_ticker LIKE ?"
    )
    params: list[Any] = [like]
    if start_date and end_date:
        sql += " AND order_as_of_date BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    sql += " ORDER BY equ_ticker ASC LIMIT 200"
    try:
        return [str(r[0]) for r in conn.execute(sql, params).fetchall()]
    except Exception as exc:
        logger.warning("symbols 回退失败（返回空）: %s", exc)
        return []


def recent_trading_dates(conn, n: int = 5) -> list[str]:
    """最近 n 个有 TCA 汇总的交易日（升序；空表返回 []）。"""
    sql = (
        f"SELECT DISTINCT order_as_of_date FROM {Config.TCA_ROUTE_SUMMARY_TABLE} "
        "ORDER BY order_as_of_date DESC LIMIT ?"
    )
    try:
        dates = [str(r[0]) for r in conn.execute(sql, [n]).fetchall()]
    except Exception as exc:
        logger.warning("recent_trading_dates 失败（返回空）: %s", exc)
        return []
    return sorted(dates)


# ── 订单详情逐笔取数（PR-2；库/表缺失一律降级空列表，不抛错）───────────────


def _rows_or_empty(conn, sql: str, params: list[Any], label: str) -> list[dict[str, Any]]:
    """执行查询 → dict 行列表；异常（缺表/缺列）降级为空并记 warning。"""
    try:
        cursor = conn.execute(sql, params)
    except Exception as exc:
        logger.warning("%s 查询失败（降级空列表）: %s", label, exc)
        return []
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def query_order_routes(conn, order_id: str) -> list[dict[str, Any]]:
    """订单全部路由（tca_route_summary），按 RouteId 升序。"""
    return _rows_or_empty(
        conn,
        f"SELECT * FROM {Config.TCA_ROUTE_SUMMARY_TABLE} WHERE OrderId = ? "
        "ORDER BY RouteId",
        [order_id],
        "order routes",
    )


def query_order_fills(conn, order_id: str, order_as_of_date: str) -> list[dict[str, Any]]:
    """订单逐笔（processed_fills，清洗后权威逐笔），按成交时刻升序。"""
    return _rows_or_empty(
        conn,
        f"SELECT RouteId, FillId, exchange_exec_time, route_as_of_time, "
        f"FillPrice, FillShares, is_closing_auction, equ_ticker, Exchange "
        f"FROM {Config.PROCESSED_FILLS_TABLE} "
        f"WHERE OrderId = ? AND order_as_of_date = ? "
        "ORDER BY exchange_exec_time, FillId",
        [order_id, order_as_of_date],
        "order fills",
    )


def query_order_raw_fills(conn, order_id: str, order_as_of_date: str) -> list[dict[str, Any]]:
    """订单原始逐笔（raw_fills：Liquidity / NY 时间戳），按 FillId 升序。"""
    return _rows_or_empty(
        conn,
        f"SELECT RouteId, FillId, Liquidity, NyOrderCreateAsOfDateTime, "
        f"NyTranCreateAsOfDateTime, DateTimeOfFill "
        f"FROM {Config.RAW_FILLS_TABLE} "
        f"WHERE OrderId = ? AND order_as_of_date = ? "
        "ORDER BY FillId",
        [order_id, order_as_of_date],
        "order raw_fills",
    )


def query_order_bars(conn, equ_ticker: str, order_as_of_date: str) -> list[dict[str, Any]]:
    """订单日 raw_bdib 10s bar（按前导列点查，指南 §10.3），按时刻升序。"""
    return _rows_or_empty(
        conn,
        f"SELECT mkt_timestamp, close, open, volume FROM {Config.RAW_BDIB_TABLE} "
        f"WHERE equ_ticker = ? AND order_as_of_date = ? "
        "ORDER BY mkt_timestamp",
        [equ_ticker, order_as_of_date],
        "order bars",
    )


def _keys_where(keys: list[tuple[str, str]]) -> tuple[str, list[Any]]:
    """(OrderId, order_as_of_date) 键集 → OrderId IN（走 OrderId 前导索引）。

    OrderId 在 EMSX 内全局唯一，无需再按日期过滤；OR 式 (OrderId, date) 条件
    会让优化器退化为全表扫（raw_fills 千万级行，实测超预算）。
    """
    order_ids = list(dict.fromkeys(str(order_id) for order_id, _ in keys))
    marks = ", ".join(["?"] * len(order_ids))
    return f"OrderId IN ({marks})", order_ids


def query_page_fill_agg(conn, keys: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """列表当前页逐笔聚合（每订单一行）：span/速度/首笔竞价判定的最小数据。

    不拉全量逐笔 —— 30 天×50 行的性能预算（§6.2）靠这层聚合守住。
    """
    if not keys:
        return []
    where, params = _keys_where(keys)
    return _rows_or_empty(
        conn,
        f"SELECT OrderId, COUNT(*) AS fill_n, "
        f"MIN(exchange_exec_time) AS first_exec, MAX(exchange_exec_time) AS last_exec, "
        f"MIN(route_as_of_time) AS first_route_as_of, "
        f"MIN(is_closing_auction) AS all_auction "
        f"FROM {Config.PROCESSED_FILLS_TABLE} WHERE {where} GROUP BY OrderId",
        params,
        "page fill agg",
    )


def query_page_liquidity_agg(conn, keys: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """列表当前页 Liquidity×股数聚合（订单 × 原始取值；分类走 LIQUIDITY_MAP）。"""
    if not keys:
        return []
    where, params = _keys_where(keys)
    return _rows_or_empty(
        conn,
        f"SELECT OrderId, Liquidity, SUM(CAST(FillShares AS REAL)) AS shares "
        f"FROM {Config.RAW_FILLS_TABLE} WHERE {where} "
        "GROUP BY OrderId, Liquidity",
        params,
        "page liquidity agg",
    )


# ── 静态报告：交易员执行摘要（方案 §3.6.2 / §4.13 的静态版）─────────────────

#: 摘要表默认展示行数（按订单数取前 N 名；全量经 Trader Review 查看）
TRADER_SUMMARY_LIMIT = 10
#: 低完成率界（§4.13：``completion < 0.8``；与列表完成率桶 ``lt50``/``50to80`` 同界）
LOW_COMPLETION_THRESHOLD = 0.8


def _order_rows_sql(where_clause: str) -> str:
    """订单级聚合外壳：`_agg_select` 分组 + `_outer_select` 派生列。

    摘要 / peer 等多处消费方共用（``where_clause`` 含 ``WHERE`` 关键字），
    避免各自复制一遍 GROUP BY 与派生列外壳。
    """
    t = Config.TCA_ROUTE_SUMMARY_TABLE
    inner = f"""
        {_agg_select()}
          FROM {t} r
          {where_clause}
          GROUP BY r.OrderId, r.order_as_of_date
        )
        """
    return f"""{_outer_select()}{inner} AS agg_rows"""


def trader_summary_sql(where_clause: str) -> str:
    """交易员执行摘要 SQL（订单级聚合 → 按交易员分组；方案 §3.6.2）。

    复用订单列表的两段外壳（``_agg_select`` 订单聚合 + ``_outer_select`` 派生
    completion / 质量旗标），保证摘要与 Trader Review 列表**同一订单口径**，
    不另写一套聚合。``where_clause`` 由调用方给，**含 ``WHERE`` 关键字**（与
    ``report_aggregator._build_where`` 的返回约定一致，报告期 + 作用域，裸列）。

    输出列（每交易员一行）：

    - ``orders`` 订单数；``completion_measured_orders`` 有完成率的分母
    - ``low_completion_orders`` 完成率 < 0.8 的订单数
    - ``opp_dominant_orders`` / ``opp_measured_orders``：机会成本主导（§4.13 口径
      ``adverse(opp_bps) > adverse(arrival_bps)`` 且 ``completion<1``）/ 两者均非空
    - ``arrival_notional`` / ``arrival_cost_notional``：加权 arrival 的分子分母
      （权重 = 成交额 fill×p_avg，与报告 KPI 同源；均值为两者相除）
    - ``overfill_orders`` / ``cost_missing_orders`` / ``amount_mismatch_orders`` /
      ``single_fill_orders``：质量标记订单数（与列表徽章同界）

    ``opp_bps`` 按 §3.8 计：``opportunity_cost / (RouteShares × p_decision) × 10000``；
    异常订单数不在此 SQL（需阈值规则引擎），由报告层从异常明细按交易员归集。
    """
    orders = _order_rows_sql(where_clause)
    return f"""
        SELECT trader_name,
               COUNT(*) AS orders,
               SUM(CASE WHEN completion IS NOT NULL
                         AND completion < {LOW_COMPLETION_THRESHOLD}
                        THEN 1 ELSE 0 END) AS low_completion_orders,
               SUM(CASE WHEN completion IS NOT NULL THEN 1 ELSE 0 END)
                 AS completion_measured_orders,
               SUM(CASE WHEN completion < 1
                         AND opportunity_cost IS NOT NULL
                         AND p_decision IS NOT NULL AND route_shares > 0
                         AND arrival_cost_bps IS NOT NULL
                         AND -(opportunity_cost / (route_shares * p_decision) * 10000.0)
                             > -arrival_cost_bps
                        THEN 1 ELSE 0 END) AS opp_dominant_orders,
               SUM(CASE WHEN opportunity_cost IS NOT NULL
                         AND p_decision IS NOT NULL AND route_shares > 0
                         AND arrival_cost_bps IS NOT NULL
                        THEN 1 ELSE 0 END) AS opp_measured_orders,
               SUM(CASE WHEN arrival_cost_bps IS NOT NULL THEN notional END)
                 AS arrival_notional,
               SUM(CASE WHEN arrival_cost_bps IS NOT NULL
                        THEN arrival_cost_bps * notional END) AS arrival_cost_notional,
               SUM(flag_overfill) AS overfill_orders,
               SUM(flag_cost_missing) AS cost_missing_orders,
               SUM(flag_amount_mismatch) AS amount_mismatch_orders,
               SUM(flag_single_fill) AS single_fill_orders
          FROM ({orders}) AS order_rows
         GROUP BY trader_name
         ORDER BY orders DESC, trader_name ASC
        """


def query_trader_summary(
    conn, where_clause: str, params: list[Any],
) -> list[dict[str, Any]]:
    """执行摘要 SQL，返回**全部**交易员行（截断由调用方按订单数前 N 名做）。

    ``where_clause`` 含 ``WHERE`` 关键字（同上）。表缺失 / 旧 schema 失败时降级为
    空列表（与列表查询同策略，009）。
    """
    try:
        cursor = conn.execute(trader_summary_sql(where_clause), params)
    except Exception as exc:  # 表缺失/旧 schema → 空结果（009 降级）
        logger.warning("trader 执行摘要查询失败（返回空列表）: %s", exc)
        return []
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]

# ── 210 §4.7：同类 peer 样本（订单级，两级口径的 SQL 层）─────────────────────

#: 精确同类口径：窗口天数 / 最小样本（§4.7 n≥20 才出分位）
PEER_EXACT_WINDOW_DAYS = 180
PEER_EXACT_MIN_SAMPLE = 20
#: 宽口径（市场 + 方向 + 算法）：窗口天数 / 最小样本
PEER_WIDE_WINDOW_DAYS = 90
PEER_WIDE_MIN_SAMPLE = 50


def peer_orders_sql(where_clause: str) -> str:
    """同类订单聚合 SQL（与列表/摘要同一订单口径，不另写一套聚合）。

    ``where_clause`` 含 ``WHERE`` 关键字（同 ``trader_summary_sql`` 约定）。
    """
    return _order_rows_sql(where_clause)


def query_peer_orders(conn, where_clause: str, params: list[Any]) -> list[dict[str, Any]]:
    """执行同类订单聚合；失败（表缺失/旧 schema）降级为空列表。"""
    try:
        cursor = conn.execute(peer_orders_sql(where_clause), params)
    except Exception as exc:  # 009：缺表/旧 schema → 空样本（UI 显示「样本不足」）
        logger.warning("peer 样本查询失败（返回空列表）: %s", exc)
        return []
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


#: 延迟样本按 OrderId 分批（SQLite 变量上限 999；主键首列有索引，按 id 查是索引扫描）
PEER_LATENCY_CHUNK = 200


def query_peer_latency(
    conn, order_ids: list[str],
) -> list[dict[str, Any]]:
    """同类订单的「路由下达 → 首笔连续成交」原始时刻（§4.9 peer p90 用）。

    只按**已经选出的 peer 订单 id** 反查逐笔（主键 ``(OrderId, RouteId, FillId, 日期)``
    首列有索引），而不是按 ticker + 180 天窗口扫逐笔表 —— 实测后者对 `processed_fills`
    是整表扫描（2.6s@PFE 180 天），前者是索引点查。
    """
    if not order_ids:
        return []
    sql = f"""
        SELECT OrderId, order_as_of_date,
               MIN(route_as_of_time) AS route_first,
               MIN(CASE WHEN is_closing_auction = 0 THEN exchange_exec_time END)
                 AS first_continuous
          FROM {Config.PROCESSED_FILLS_TABLE}
         WHERE OrderId IN ({{marks}})
         GROUP BY OrderId, order_as_of_date
    """
    rows: list[dict[str, Any]] = []
    unique_ids = list(dict.fromkeys(order_ids))
    for start in range(0, len(unique_ids), PEER_LATENCY_CHUNK):
        chunk = unique_ids[start:start + PEER_LATENCY_CHUNK]
        marks = ", ".join(["?"] * len(chunk))
        try:
            cursor = conn.execute(sql.format(marks=marks), chunk)
        except Exception as exc:
            logger.warning("peer 延迟样本查询失败（返回空列表）: %s", exc)
            return rows
        columns = [d[0] for d in cursor.description]
        rows.extend(dict(zip(columns, row)) for row in cursor.fetchall())
    return rows


def query_latest_order_date(conn) -> Optional[str]:
    """库内最新 TCA 日期（peer 缓存 key 的一部分：管道跑批后缓存自动失效）。"""
    try:
        row = conn.execute(
            f"SELECT MAX(order_as_of_date) FROM {Config.TCA_ROUTE_SUMMARY_TABLE}",
        ).fetchone()
    except Exception as exc:
        logger.warning("最新 TCA 日期查询失败: %s", exc)
        return None
    return str(row[0]) if row and row[0] else None


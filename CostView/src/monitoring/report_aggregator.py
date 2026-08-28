"""TCA 可视化报告聚合服务 — tca_route_summary 的报表级聚合。

供独立 HTML 报告脚本与监控 API 的报告端点复用：
    KPI（route 数 / 总股数 / 成交额加权 pnl_vwap / 平均 par_rate / 平均 RPM）、
    pnl_vwap 分布直方图、按日加权走势、broker/algo 排行、PWP 五档均值曲线。

加权口径：成交额权重 = RouteShares * p_avg（仅三者均非 NULL 时计入）。
所有过滤条件参数化（? 占位符），指标名仅来自内部白名单常量。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager

from .metric_coverage import MetricCoverageService, validate_metrics
from .anomaly_query import (
    ThresholdRules,
    query_anomaly_routes,
)
from .report_dims import get_filter_options as _get_persisted_options

logger = logging.getLogger(__name__)

#: 直方图分桶数
_HISTOGRAM_BINS = 20
#: 排行输出上限
_RANKING_LIMIT = 20
#: PWP 档位（数值为百分比）
_PWP_RATE_LABELS = [("pwp_5", 5), ("pwp_10", 10), ("pwp_15", 15),
                    ("pwp_20", 20), ("pwp_25", 25)]
#: 小计价单位货币（GBp=便士、ILs=阿高洛、ZAr=分）：成交价以 1/100 本币计价，
#: USD 成交金额换算时需 ÷100（与 backend order_projections 的 GBP/ZAR ÷100 对齐）。
_MINOR_UNIT_CCYS: tuple[str, ...] = ("GBp", "ILs", "ZAr")


class TcaReportAggregator:
    """tca_route_summary 报告聚合器。"""

    def __init__(self, connection_manager: Optional[ConnectionManager] = None):
        self._mgr = connection_manager or ConnectionManager()
        #: fill_bdib 汇率回填临时表是否就绪（build_report 内一次性构建，4 个 fx 查询复用）
        self._fbfx_ready = False

    def build_report(
        self,
        start_date: str,
        end_date: str,
        *,
        broker: Optional[str] = None,
        algo: Optional[str] = None,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
        metrics: Optional[list[str]] = None,
        thresholds: Optional[dict[str, Any]] = None,
        min_fill_count: int = 10,
        min_notional_usd: float = 10000.0,
    ) -> dict[str, Any]:
        """组装报告聚合数据。

        broker/algo/symbol/exchange 支持逗号分隔多值（IN 匹配，前端多选）。
        metrics 控制附加的覆盖率小节统计口径（默认全部 38 个指标）。
        thresholds 控制 S6 异常路由明细的判定阈值（None/空 → 默认阈值）。
        markets 清单遵循 exchange 过滤（导出时按交易所整体过滤，市场概览同步收窄；
        无 exchange 时等价于忽略 exchange）。filter_options.exchanges 仍忽略 exchange
        过滤（供前端筛选下拉展示全部可选市场）。表不存在时返回带 data_source_warning 的空报告。
        """
        selected = validate_metrics(metrics)
        where, params = self._build_where(
            start_date, end_date, broker, algo, symbol, exchange,
        )
        where_no_exchange, params_no_exchange = self._build_where(
            start_date, end_date, broker, algo, symbol, None,
        )
        conn = self._mgr.get_connection("fill_bdib", AccessTier.READ)
        try:
            if not self._table_exists(conn):
                return self._empty_report(
                    start_date, end_date, broker, algo, symbol, exchange, selected,
                )
            # 报告期一次性构建 fill_bdib 汇率回填临时表，供下方 4 个 fx 查询复用
            self._prepare_fx_enrichment(conn, start_date, end_date)
            report = {
                "filters": self._filters_dict(
                    start_date, end_date, broker, algo, symbol, exchange, selected,
                ),
                # 市场概览遵循 exchange 过滤：导出时按交易所整体过滤时，
                # 该小节也仅展示所选交易所（无 exchange 时与 where_no_exchange 等价）。
                "markets": self._query_markets(conn, where, params),
                "filter_options": self._query_filter_options(conn, where_no_exchange, params_no_exchange),
                "market_notional_ranking": self._query_market_notional_ranking(
                    conn, where, params,
                ),
                "market_notional_trend": self._query_market_notional_trend(
                    conn, where, params,
                ),
                "kpi": self._query_kpi(conn, where, params),
                "daily_series": self._query_daily_series(conn, where, params),
                "rankings": {
                    "by_broker": self._query_rankings(conn, where, params, "Broker"),
                    "by_algo": self._query_rankings(conn, where, params, "algo"),
                },
                "pnl_vwap_histogram": self._query_pnl_histogram(conn, where, params),
                "pwp_curve": self._query_pwp_curve(conn, where, params),
                # 006: 决策基准 / 风险 / 完成率 / 冲击分解 / 异常明细
                "extra_kpis": self._query_extra_kpis(conn, where, params),
                "impact_breakdown": self._query_impact_breakdown(conn, where, params),
            }
        finally:
            conn.close()

        # 附加所选指标的覆盖率小节（复用覆盖率服务，口径与监控页一致）
        report["metric_coverage"] = MetricCoverageService(self._mgr).get_coverage(
            start_date, end_date, selected,
        )
        # S6 异常路由明细（阈值可参数化，默认同前端）
        rules = ThresholdRules.from_payload(thresholds)
        anomalies = query_anomaly_routes(
            self._mgr, start_date, end_date, rules,
            broker=broker, algo=algo, symbol=symbol, exchange=exchange,
            min_fill_count=min_fill_count, min_notional_usd=min_notional_usd,
        )
        report["anomaly"] = {
            "count": len(anomalies),
            "rows": [a.__dict__ for a in anomalies],
        }
        return report

    # ── 过滤条件 ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_where(
        start_date: str,
        end_date: str,
        broker: Optional[str],
        algo: Optional[str],
        symbol: Optional[str],
        exchange: Optional[str],
    ) -> tuple[str, list[Any]]:
        """构建 WHERE 子句与参数列表（全部 ? 绑定）。

        broker/algo/symbol/exchange 支持逗号分隔多值 → IN (...) 匹配；
        单个值等价于 = 匹配。
        """
        conditions = ["order_as_of_date BETWEEN ? AND ?"]
        params: list[Any] = [start_date, end_date]
        for column, value in (
            ("Broker", broker), ("algo", algo),
            ("equ_ticker", symbol), ("Exchange", exchange),
        ):
            values = TcaReportAggregator._split_values(value)
            if values:
                placeholders = ", ".join(["?"] * len(values))
                conditions.append(f"{column} IN ({placeholders})")
                params.extend(values)
        return "WHERE " + " AND ".join(conditions), params

    @staticmethod
    def _split_values(raw: Optional[str]) -> list[str]:
        """逗号分隔多值解析；None/空 → []；单值 → [单值]。"""
        if not raw:
            return []
        return [v.strip() for v in raw.split(",") if v.strip()]

    # ── fx 汇率回填（报告期一次性构建，消除 gap sentinel 导致的整组 NULL）──

    def _prepare_fx_enrichment(self, conn, start_date: str, end_date: str) -> None:
        """探测 fill_bdib 汇率回填可行性（不再建临时表）。

        背景（CostView-Report 优化）：原 ``_fx_sum_sql`` 的 gap sentinel 在「任一
        非 USD 路由缺汇率」时把整个市场（乃至整个 KPI）的 notional_usd 置 NULL，
        导致上季度报告仅 3 个市场能算 USD 金额、总成交金额无法计算。fill_bdib
        层 fx_rate 为 fill 级权威源（fx_null=0），此处按主键回填 tca_route_summary
        缺失的 fx_rate，使报告对缺失列具备弹性、无需依赖独立回填脚本。

        注意：本聚合器以 READ 只读事务运行，CREATE TEMP TABLE 被访问层拒绝；
        故改用 CTE（``WITH _fbfx AS (...)``，归类为 read 允许）在每条 fx 查询内
        联回填，避免临时表 DDL。此处仅探测可用性并置 ``_fbfx_ready`` 标志。
        """
        self._fbfx_ready = False
        if not self._has_column(conn, "fx_rate"):
            return
        try:
            has_fb = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fill_bdib' LIMIT 1"
            ).fetchone() is not None
        except Exception:
            has_fb = False
        self._fbfx_ready = bool(has_fb)

    def _fbfx_cte(self) -> str:
        """fill_bdib 汇率回填 CTE（替代临时表，READ 事务可用）。

        按 OrderId/RouteId/交易日 fill_volume 加权聚合 fx_rate，与 ``_fx_join``
        的主键约定一致（列名 OrderId/RouteId/fxf_oad/fb_fx）。
        """
        return (
            "WITH _fbfx AS ("
            "SELECT OrderId, RouteId, order_as_of_date AS fxf_oad, "
            "SUM(fill_volume * fx_rate) / NULLIF(SUM(fill_volume), 0) AS fb_fx "
            "FROM fill_bdib WHERE fx_rate IS NOT NULL "
            "AND order_as_of_date BETWEEN ? AND ? "
            "GROUP BY OrderId, RouteId, order_as_of_date) "
        )

    def _apply_fx(self, sql: str, params: list[Any]) -> tuple[str, list[Any]]:
        """若 fill_bdib 回填可用，将 CTE 前缀注入 SQL 并把日期参数前置。

        params 约定以 [start_date, end_date, *filters] 开头，CTE 的 BETWEEN
        复用前两个日期参数，主查询沿用全部参数。
        """
        if not self._fbfx_ready:
            return sql, params
        return self._fbfx_cte() + sql, [params[0], params[1]] + params

    def _fx_join(self) -> str:
        """fill_bdib 汇率回填 LEFT JOIN 片段（回填可用时生效）。"""
        if not self._fbfx_ready:
            return ""
        return (
            " LEFT JOIN _fbfx"
            " ON _fbfx.OrderId = tca_route_summary.OrderId"
            " AND _fbfx.RouteId = tca_route_summary.RouteId"
            " AND _fbfx.fxf_oad = tca_route_summary.order_as_of_date"
        )

    def _fx_usd_expr(self) -> str:
        """USD 成交金额表达式（含小计价单位货币 ÷100 修正）。

        有效汇率 = COALESCE(tca.fx_rate, fill_bdib 回填 fb_fx)（回填可用时）；
        USD/未知币种缺汇率按 1.0 兜底；非 USD 币种仍缺汇率时该 route 贡献 NULL
        （SUM 忽略，不虚高、亦不再整体置空）。
        """
        minor = "CASE WHEN Currency IN ('GBp', 'ILs', 'ZAr') THEN 0.01 ELSE 1.0 END"
        if self._fbfx_ready:
            eff = "COALESCE(fx_rate, _fbfx.fb_fx)"
        else:
            eff = "fx_rate"
        return (
            f"CASE WHEN {eff} IS NOT NULL THEN {eff} * {minor} "
            f"WHEN Currency IS NULL OR Currency = 'USD' THEN 1.0 "
            f"ELSE NULL END"
        )

    # ── 各小节查询 ───────────────────────────────────────────────

    def _query_markets(
        self, conn, where: str, params: list[Any],
    ) -> list[dict[str, Any]]:
        """可选市场清单：Exchange 去重，遵循传入 where（含 exchange 过滤时同步收窄）。

        每条含 Exchange 与 route 数，按 route 数降序。
        007: 增加 notional / notional_usd（每市场成交金额，USD 换算）。
        """
        has_fx = self._has_column(conn, "fx_rate")
        fx_sum = self._fx_usd_expr() if has_fx else "NULL"
        join = self._fx_join() if has_fx else ""
        sql = f"""
            SELECT COALESCE(Exchange, '(unknown)') AS exchange,
                   COUNT(*) AS route_count,
                   COALESCE(SUM(fill * p_avg), 0) AS notional,
                   SUM(fill * p_avg * ({fx_sum})) AS notional_usd
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}{join}
            {where}
            GROUP BY Exchange
            ORDER BY route_count DESC, exchange ASC
        """
        sql, params = self._apply_fx(sql, params)
        return [
            {
                "exchange": str(r[0]),
                "route_count": int(r[1]),
                "notional": float(r[2]),
                "notional_usd": self._to_float(r[3]),
            }
            for r in conn.execute(sql, params).fetchall()
        ]

    def _query_market_notional_ranking(
        self, conn, where: str, params: list[Any],
    ) -> list[dict[str, Any]]:
        """按市场的成交金额（美元）排名（008）：notional_usd 降序。

        每条含 Exchange 代码 / 中文显示名 / 本币与 USD 成交金额 / route 数。
        未配置中文名的 Exchange 用代码回退。
        """
        has_fx = self._has_column(conn, "fx_rate")
        fx_sum = self._fx_usd_expr() if has_fx else "NULL"
        join = self._fx_join() if has_fx else ""
        # 排序用有效成交额：有 fx_rate 列用 USD，否则回退本币（无 fx 时 USD 为 NULL）
        order_expr = f"COALESCE(SUM(fill * p_avg * ({fx_sum})), SUM(fill * p_avg))" if has_fx else "SUM(fill * p_avg)"
        sql = f"""
            SELECT COALESCE(Exchange, '(unknown)') AS exchange,
                    COUNT(*) AS route_count,
                    COALESCE(SUM(fill * p_avg), 0) AS notional,
                    SUM(fill * p_avg * ({fx_sum})) AS notional_usd
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}{join}
            {where}
            GROUP BY Exchange
            ORDER BY {order_expr} DESC, exchange ASC
        """
        sql, params = self._apply_fx(sql, params)
        return [
            {
                "exchange": str(r[0]),
                "name": Config.MARKET_ORDER.get(str(r[0]), str(r[0])),
                "route_count": int(r[1]),
                "notional": float(r[2]),
                "notional_usd": self._to_float(r[3]),
            }
            for r in conn.execute(sql, params).fetchall()
        ]

    def _query_market_notional_trend(
        self, conn, where: str, params: list[Any],
    ) -> list[dict[str, Any]]:
        """按市场的成交金额（美元）每日趋势（008）。

        返回 [{date, exchange, notional_usd}, ...] 按日期升序，供前端按市场拆线。
        市场仅列排名中存在的（有成交额的市场），未配置中文名用代码回退。
        """
        has_fx = self._has_column(conn, "fx_rate")
        fx_sum = self._fx_usd_expr() if has_fx else "NULL"
        join = self._fx_join() if has_fx else ""
        sql = f"""
            SELECT order_as_of_date AS date,
                   COALESCE(Exchange, '(unknown)') AS exchange,
                   SUM(fill * p_avg * ({fx_sum})) AS notional_usd
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}{join}
            {where}
            GROUP BY order_as_of_date, Exchange
            ORDER BY order_as_of_date ASC, exchange ASC
        """
        sql, params = self._apply_fx(sql, params)
        return [
            {
                "date": str(r[0]),
                "exchange": str(r[1]),
                "name": Config.MARKET_ORDER.get(str(r[1]), str(r[1])),
                "notional_usd": self._to_float(r[2]),
            }
            for r in conn.execute(sql, params).fetchall()
        ]

    def _query_filter_options(
        self, conn, where: str, params: list[Any],
    ) -> dict[str, list[str]]:
        """筛选选项：优先读持久化维度表（时间无关，daily_update 每日刷新）。

        返回 {brokers, algos, symbols, exchanges}，各按累计次数降序截断
        （控制 payload 大小）。维度表未初始化（首次部署尚未刷新）时回退
        原时间范围查询，保证功能可用。
        """
        persisted = _get_persisted_options(self._mgr, conn=conn)
        if persisted is not None:
            return persisted
        # 回退：维度表不可用，按原口径对明细表查询（忽略 exchange 过滤）
        result: dict[str, list[str]] = {}
        for dim, col, limit in (
            ("brokers", "Broker", 100),
            ("algos", "algo", 50),
            ("symbols", "equ_ticker", 200),
        ):
            try:
                sql = f"""
                    SELECT COALESCE({col}, '(unknown)') AS v, COUNT(*) AS n
                    FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
                    {where}
                    GROUP BY {col}
                    ORDER BY n DESC, v ASC
                    LIMIT {limit}
                """
                result[dim] = [str(r[0]) for r in conn.execute(sql, params).fetchall()]
            except Exception as exc:
                logger.debug("filter_options[%s] 查询失败: %s", dim, exc)
                result[dim] = []
        # 回退模式下的市场选项来自 markets 清单（与 _query_markets 同口径）
        result["exchanges"] = [m["exchange"] for m in self._query_markets(conn, where, params)]
        return result

    def _query_kpi(self, conn, where: str, params: list[Any]) -> dict[str, Any]:
        """KPI：route 数、总股数、加权 pnl_vwap、平均 par_rate / RPM。

        007: 增加总成交金额（本币 notional + USD notional + fx_rate 覆盖率）。
        - notional = SUM(fill × p_avg)（本币）
        - notional_usd = SUM(fill × p_avg × fx_rate × minor_unit_factor)（USD 换算，
          仅 USD/未知币种在 fx_rate 缺失时按 1.0 兜底；非 USD 币种缺失汇率时
          整组返回 NULL，Currency ∈ {GBp, ILs, ZAr} 时 ÷100，008）
        - fx_coverage = 有非 1.0 fx_rate 的路由数 / 总路由数（None 表示无 fx_rate 列）
        """
        has_fx = self._has_column(conn, "fx_rate")
        fx_sum = self._fx_usd_expr() if has_fx else "NULL"
        join = self._fx_join() if has_fx else ""
        # fx_coverage：拥有真实（非 1.0 兜底）tca.fx_rate 的路由占比，反映 fx 数据质量
        fx_cnt = (
            "SUM(CASE WHEN fx_rate IS NOT NULL AND fx_rate <> 1.0 THEN 1 ELSE 0 END)"
            if has_fx else "NULL"
        )
        sql = f"""
            SELECT COUNT(*) AS route_count,
                   COALESCE(SUM(RouteShares), 0) AS total_shares,
                    {self._weighted_avg_sql("pnl_vwap")} AS weighted_pnl_vwap,
                    AVG(par_rate) AS avg_par_rate,
                    AVG(RPM) AS avg_rpm,
                    COALESCE(SUM(fill * p_avg), 0) AS notional,
                    SUM(fill * p_avg * ({fx_sum})) AS notional_usd,
                    {fx_cnt} AS fx_non_default_count
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}{join}
            {where}
        """
        sql, params = self._apply_fx(sql, params)
        row = conn.execute(sql, params).fetchone()
        route_count = int(row[0])
        fx_non_default = row[7]
        fx_coverage = None
        if fx_non_default is not None:
            fx_coverage = round(fx_non_default / route_count, 4) if route_count else None
        return {
            "route_count": route_count,
            "total_route_shares": float(row[1]),
            "weighted_pnl_vwap": self._to_float(row[2]),
            "avg_par_rate": self._to_float(row[3]),
            "avg_rpm": self._to_float(row[4]),
            "notional": float(row[5]),
            "notional_usd": self._to_float(row[6]),
            "fx_coverage": fx_coverage,
        }

    def _query_daily_series(
        self, conn, where: str, params: list[Any],
    ) -> list[dict[str, Any]]:
        """按日加权 pnl_vwap / 平均 par_rate 走势。"""
        sql = f"""
            SELECT order_as_of_date, COUNT(*) AS route_count,
                   {self._weighted_avg_sql("pnl_vwap")} AS weighted_pnl_vwap,
                   AVG(par_rate) AS avg_par_rate
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            {where}
            GROUP BY order_as_of_date ORDER BY order_as_of_date
        """
        return [
            {
                "date": str(r[0]),
                "route_count": int(r[1]),
                "weighted_pnl_vwap": self._to_float(r[2]),
                "avg_par_rate": self._to_float(r[3]),
            }
            for r in conn.execute(sql, params).fetchall()
        ]

    def _query_rankings(
        self, conn, where: str, params: list[Any], dimension: str,
    ) -> list[dict[str, Any]]:
        """broker / algo 排行（按成交额加权 pnl_vwap 升序，成本从优到劣）。"""
        sql = f"""
            SELECT COALESCE({dimension}, '(unknown)') AS name,
                   COUNT(*) AS route_count,
                   {self._weighted_avg_sql("pnl_vwap")} AS weighted_pnl_vwap,
                   AVG(par_rate) AS avg_par_rate
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            {where}
            GROUP BY {dimension}
            ORDER BY weighted_pnl_vwap IS NULL, weighted_pnl_vwap ASC
            LIMIT {_RANKING_LIMIT}
        """
        return [
            {
                "name": str(r[0]),
                "route_count": int(r[1]),
                "weighted_pnl_vwap": self._to_float(r[2]),
                "avg_par_rate": self._to_float(r[3]),
            }
            for r in conn.execute(sql, params).fetchall()
        ]

    def _query_pnl_histogram(
        self, conn, where: str, params: list[Any],
    ) -> list[dict[str, Any]]:
        """pnl_vwap 分布直方图（numpy 等宽分桶）。"""
        sql = f"""
            SELECT pnl_vwap FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            {where} AND pnl_vwap IS NOT NULL
        """
        values = [float(r[0]) for r in conn.execute(sql, params).fetchall()]
        if not values:
            return []
        counts, edges = np.histogram(np.array(values), bins=_HISTOGRAM_BINS)
        return [
            {"lower": round(float(edges[i]), 4), "upper": round(float(edges[i + 1]), 4),
             "count": int(counts[i])}
            for i in range(len(counts))
        ]

    def _query_pwp_curve(
        self, conn, where: str, params: list[Any],
    ) -> list[dict[str, Any]]:
        """PWP 五档位均值曲线。"""
        avgs = ", ".join(f"AVG({col})" for col, _ in _PWP_RATE_LABELS)
        sql = f"SELECT {avgs} FROM {Config.TCA_ROUTE_SUMMARY_TABLE} {where}"
        row = conn.execute(sql, params).fetchone()
        return [
            {"rate": rate, "avg_pwp": self._to_float(row[i])}
            for i, (_, rate) in enumerate(_PWP_RATE_LABELS)
        ]

    def _query_extra_kpis(self, conn, where: str, params: list[Any]) -> dict[str, Any]:
        """决策基准 / 实现短缺 / 风险 / 完成率 聚合（006 增补）。

        对齐文献 D1（决策基准 + 市场时间基准并存）与 B2-3（风险维度）：
        - arrival_cost_bps / wagner_is_bps：成交额加权
        - cost_stddev / cost_cvar / cost_p95：成交额加权
        - avg_fill：平均完成率
        """
        weighted = lambda m: self._weighted_avg_sql(m)  # noqa: E731
        sql = f"""
            SELECT
                {weighted("arrival_cost_bps")} AS arrival_cost_bps,
                {weighted("wagner_is_bps")} AS wagner_is_bps,
                {weighted("cost_stddev")} AS cost_stddev,
                {weighted("cost_cvar")} AS cost_cvar,
                {weighted("cost_p95")} AS cost_p95,
                AVG(fill / NULLIF(RouteShares, 0)) AS avg_fill
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            {where}
        """
        row = conn.execute(sql, params).fetchone()
        return {
            "arrival_cost_bps": self._to_float(row[0]),
            "wagner_is_bps": self._to_float(row[1]),
            "cost_stddev": self._to_float(row[2]),
            "cost_cvar": self._to_float(row[3]),
            "cost_p95": self._to_float(row[4]),
            "avg_fill": self._to_float(row[5]),
        }

    def _query_impact_breakdown(self, conn, where: str, params: list[Any]) -> dict[str, Any]:
        """市场冲击分解（B2-2）：暂时冲击 5/10/30min + 永久冲击 聚合。"""
        weighted = lambda m: self._weighted_avg_sql(m)  # noqa: E731
        sql = f"""
            SELECT
                {weighted("temp_impact_5min_bps")} AS t5,
                {weighted("temp_impact_10min_bps")} AS t10,
                {weighted("temp_impact_30min_bps")} AS t30,
                {weighted("perm_impact_bps")} AS perm,
                {weighted("close_cost_bps")} AS close_cost
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            {where}
        """
        row = conn.execute(sql, params).fetchone()
        return {
            "temp_impact_5min_bps": self._to_float(row[0]),
            "temp_impact_10min_bps": self._to_float(row[1]),
            "temp_impact_30min_bps": self._to_float(row[2]),
            "perm_impact_bps": self._to_float(row[3]),
            "close_cost_bps": self._to_float(row[4]),
        }

    # ── 工具函数 ─────────────────────────────────────────────────────────

    @staticmethod
    def _weighted_avg_sql(metric: str) -> str:
        """成交额加权均值 SQL 片段（metric 为内部白名单值，无注入风险）。"""
        cond = f"{metric} IS NOT NULL AND p_avg IS NOT NULL AND RouteShares IS NOT NULL"
        return (
            f"SUM(CASE WHEN {cond} THEN {metric} * RouteShares * p_avg END) / "
            f"NULLIF(SUM(CASE WHEN {cond} THEN RouteShares * p_avg END), 0)"
        )

    @staticmethod
    def _table_exists(conn) -> bool:
        cursor = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            [Config.TCA_ROUTE_SUMMARY_TABLE],
        )
        return cursor.fetchone() is not None

    @staticmethod
    def _has_column(conn, column: str) -> bool:
        """tca_route_summary 是否含指定列（幂等兼容旧 schema）。"""
        try:
            rows = conn.execute(
                f"PRAGMA table_info({Config.TCA_ROUTE_SUMMARY_TABLE})"
            ).fetchall()
        except Exception:
            return False
        return any(str(r[1]).lower() == column.lower() for r in rows)

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        """数值安全转换，None/NaN → None。"""
        if value is None:
            return None
        result = float(value)
        return result if result == result else None

    @staticmethod
    def _filters_dict(
        start_date: str, end_date: str, broker: Optional[str], algo: Optional[str],
        symbol: Optional[str], exchange: Optional[str], metrics: list[str],
    ) -> dict[str, Any]:
        return {
            "start_date": start_date, "end_date": end_date,
            "broker": broker, "algo": algo, "symbol": symbol, "exchange": exchange,
            "metrics": metrics,
        }

    def _empty_report(
        self, start_date: str, end_date: str, broker: Optional[str],
        algo: Optional[str], symbol: Optional[str], exchange: Optional[str],
        selected: list[str],
    ) -> dict[str, Any]:
        return {
            "filters": self._filters_dict(
                start_date, end_date, broker, algo, symbol, exchange, selected,
            ),
            "markets": [],
            "filter_options": {"brokers": [], "algos": [], "symbols": [], "exchanges": []},
            "market_notional_ranking": [],
            "market_notional_trend": [],
            "kpi": None,
            "daily_series": [],
            "rankings": {"by_broker": [], "by_algo": []},
            "pnl_vwap_histogram": [],
            "pwp_curve": [],
            "extra_kpis": None,
            "impact_breakdown": None,
            "anomaly": {"count": 0, "rows": []},
            "metric_coverage": None,
            "data_source_warning": "tca_route_summary 不存在 — 请先运行管道 S5.5",
        }

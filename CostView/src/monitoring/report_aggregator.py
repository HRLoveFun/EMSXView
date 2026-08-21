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

logger = logging.getLogger(__name__)

#: 直方图分桶数
_HISTOGRAM_BINS = 20
#: 排行输出上限
_RANKING_LIMIT = 20
#: PWP 档位（数值为百分比）
_PWP_RATE_LABELS = [("pwp_5", 5), ("pwp_10", 10), ("pwp_15", 15),
                    ("pwp_20", 20), ("pwp_25", 25)]


class TcaReportAggregator:
    """tca_route_summary 报告聚合器。"""

    def __init__(self, connection_manager: Optional[ConnectionManager] = None):
        self._mgr = connection_manager or ConnectionManager()

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
    ) -> dict[str, Any]:
        """组装报告聚合数据。

        metrics 控制附加的覆盖率小节统计口径（默认全部 38 个指标）。
        thresholds 控制 S6 异常路由明细的判定阈值（None/空 → 默认阈值）。
        表不存在时返回带 data_source_warning 的空报告。
        """
        selected = validate_metrics(metrics)
        where, params = self._build_where(
            start_date, end_date, broker, algo, symbol, exchange,
        )
        conn = self._mgr.get_connection("fill_bdib", AccessTier.READ)
        try:
            if not self._table_exists(conn):
                return self._empty_report(
                    start_date, end_date, broker, algo, symbol, exchange, selected,
                )
            report = {
                "filters": self._filters_dict(
                    start_date, end_date, broker, algo, symbol, exchange, selected,
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
        )
        report["anomaly"] = {
            "count": len(anomalies),
            "rows": [a.__dict__ for a in anomalies],
        }
        report["anomaly"]["critical_count"] = sum(
            1 for r in anomalies if r.severity == "critical"
        )
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
        """构建 WHERE 子句与参数列表（全部 ? 绑定）。"""
        conditions = ["order_as_of_date BETWEEN ? AND ?"]
        params: list[Any] = [start_date, end_date]
        for column, value in (
            ("Broker", broker), ("algo", algo),
            ("equ_ticker", symbol), ("Exchange", exchange),
        ):
            if value:
                conditions.append(f"{column} = ?")
                params.append(value)
        return "WHERE " + " AND ".join(conditions), params

    # ── 各小节查询 ───────────────────────────────────────────────────────

    def _query_kpi(self, conn, where: str, params: list[Any]) -> dict[str, Any]:
        """KPI：route 数、总股数、加权 pnl_vwap、平均 par_rate / RPM。"""
        sql = f"""
            SELECT COUNT(*) AS route_count,
                   COALESCE(SUM(RouteShares), 0) AS total_shares,
                   {self._weighted_avg_sql("pnl_vwap")} AS weighted_pnl_vwap,
                   AVG(par_rate) AS avg_par_rate,
                   AVG(RPM) AS avg_rpm
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            {where}
        """
        row = conn.execute(sql, params).fetchone()
        return {
            "route_count": int(row[0]),
            "total_route_shares": float(row[1]),
            "weighted_pnl_vwap": self._to_float(row[2]),
            "avg_par_rate": self._to_float(row[3]),
            "avg_rpm": self._to_float(row[4]),
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
            "kpi": None,
            "daily_series": [],
            "rankings": {"by_broker": [], "by_algo": []},
            "pnl_vwap_histogram": [],
            "pwp_curve": [],
            "extra_kpis": None,
            "impact_breakdown": None,
            "anomaly": {"count": 0, "critical_count": 0, "rows": []},
            "metric_coverage": None,
            "data_source_warning": "tca_route_summary 不存在 — 请先运行管道 S5.5",
        }

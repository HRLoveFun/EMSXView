"""指标覆盖率服务 — tca_route_summary 38 项计算指标的非 NULL 率聚合。

按 order_as_of_date（可选按 Exchange 分层）统计各计算指标的覆盖率，
用于区分"BDIB 数据缺失导致的 NULL"与"有数据但计算异常"。
聚合全部在 SQL 侧完成（GROUP BY + SUM(CASE WHEN ...)），避免 Python 逐行遍历。

003-tca-core-benchmarks: 白名单由 18 项扩展至 38 项，新增 Phase 0/1 的
到达价/收盘价基准、Wagner IS 分解、成本风险、市场冲击等 20 项指标。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager

logger = logging.getLogger(__name__)

#: 38 项计算指标白名单（与 tca_route_metrics._OUTPUT_COLUMNS[17:] 保持一致；
#: 003-tca-core-benchmarks 由 18 项扩展至 38 项，新增 Phase 0/1 的 20 项指标）
COMPUTED_METRICS: tuple[str, ...] = (
    # 原有 18 项
    "fill_count", "fill", "fill_continuous", "fill_close",
    "par_rate", "par_rate_continuous", "par_rate_close",
    "p_avg", "p_avg_continuous",
    "pnl_vwap", "pnl_vwap_continuous",
    "RPM", "RPM_continuous",
    "pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25",
    # 003-tca-core-benchmarks: Phase 0 核心基准（5）
    "p_arrival", "p_close", "arrival_cost_bps", "close_cost_bps",
    "opportunity_cost",
    # 003-tca-core-benchmarks: Phase 1 Wagner IS / 风险 / 冲击（15）
    "p_decision", "delay_cost", "trading_cost", "wagner_is", "wagner_is_bps",
    "cost_stddev", "cost_p95", "cost_cvar",
    "order_duration_sec", "exec_rate_shares_per_min",
    "temp_impact_5min_bps", "temp_impact_10min_bps", "temp_impact_30min_bps",
    "perm_impact_bps", "recovery_truncated",
)

#: 依赖 BDIB 行情的指标（BDIB 缺失时这些指标为 NULL 属预期行为）
BDIB_DEPENDENT_METRICS: frozenset[str] = frozenset({
    # 原有 BDIB 依赖项
    "par_rate", "par_rate_continuous", "par_rate_close",
    "pnl_vwap", "pnl_vwap_continuous",
    "pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25",
    # 003-tca-core-benchmarks: 到达价/决策价/收盘价/冲击均依赖 BDIB bar
    "p_arrival", "p_close", "arrival_cost_bps", "close_cost_bps",
    "opportunity_cost",
    "p_decision", "delay_cost", "trading_cost", "wagner_is", "wagner_is_bps",
    "temp_impact_5min_bps", "temp_impact_10min_bps", "temp_impact_30min_bps",
    "perm_impact_bps",
})


def validate_metrics(metrics: Optional[list[str]]) -> list[str]:
    """校验并规范化指标子集；None/空列表表示全部 38 个指标。

    Raises:
        ValueError: 含白名单外的指标名。
    """
    if not metrics:
        return list(COMPUTED_METRICS)
    unknown = [m for m in metrics if m not in COMPUTED_METRICS]
    if unknown:
        raise ValueError(
            f"未知指标 {unknown}，可选: {list(COMPUTED_METRICS)}"
        )
    # 保持白名单顺序输出，便于前端列序稳定
    return [m for m in COMPUTED_METRICS if m in set(metrics)]


class MetricCoverageService:
    """tca_route_summary 指标覆盖率聚合服务。"""

    def __init__(self, connection_manager: Optional[ConnectionManager] = None):
        self._mgr = connection_manager or ConnectionManager()

    def get_coverage(
        self,
        start_date: str,
        end_date: str,
        metrics: Optional[list[str]] = None,
        group_by_exchange: bool = False,
    ) -> dict[str, Any]:
        """按日期（可选 ×Exchange）统计各指标非 NULL 率。

        Returns:
            {
                "start_date":..., "end_date":..., "metrics": [...],
                "bdib_dependent_metrics": [...],
                "group_by_exchange": bool,
                "rows": [{"date", "exchange", "total_routes",
                          "coverage": {m: pct}, "null_counts": {m: n}}],
            }
            表不存在时 rows 为空并附 data_source_warning。
        """
        selected = validate_metrics(metrics)
        conn = self._mgr.get_connection("fill_bdib", AccessTier.READ)
        try:
            if not self._table_exists(conn):
                return self._empty_result(
                    start_date, end_date, selected, group_by_exchange,
                    warning="tca_route_summary 不存在 — 请先运行管道 S5.5",
                )
            rows = self._query_coverage(
                conn, start_date, end_date, selected, group_by_exchange,
            )
        finally:
            conn.close()

        return {
            "start_date": start_date,
            "end_date": end_date,
            "metrics": selected,
            "bdib_dependent_metrics": [m for m in selected if m in BDIB_DEPENDENT_METRICS],
            "group_by_exchange": group_by_exchange,
            "rows": rows,
        }

    def _query_coverage(
        self,
        conn,
        start_date: str,
        end_date: str,
        selected: list[str],
        group_by_exchange: bool,
    ) -> list[dict[str, Any]]:
        """单条聚合 SQL 完成全部指标的覆盖率统计。"""
        metric_aggs = ", ".join(
            f"SUM(CASE WHEN {m} IS NOT NULL THEN 1 ELSE 0 END) AS nn_{m}"
            for m in selected
        )
        group_cols = "order_as_of_date, Exchange" if group_by_exchange else "order_as_of_date"
        sql = f"""
            SELECT {group_cols}, COUNT(*) AS total_routes, {metric_aggs}
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            WHERE order_as_of_date BETWEEN ? AND ?
            GROUP BY {group_cols}
            ORDER BY {group_cols}
        """
        cursor = conn.execute(sql, [start_date, end_date])
        columns = [desc[0] for desc in cursor.description]
        return [
            self._row_to_coverage(dict(zip(columns, row)), selected, group_by_exchange)
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _row_to_coverage(
        row: dict[str, Any],
        selected: list[str],
        group_by_exchange: bool,
    ) -> dict[str, Any]:
        """把聚合行转换为 {coverage, null_counts} 结构。"""
        total = int(row["total_routes"])
        coverage: dict[str, Optional[float]] = {}
        null_counts: dict[str, int] = {}
        for m in selected:
            nn = int(row[f"nn_{m}"] or 0)
            null_counts[m] = total - nn
            coverage[m] = round(nn / total * 100.0, 2) if total > 0 else None
        return {
            "date": row["order_as_of_date"],
            "exchange": row.get("Exchange") if group_by_exchange else None,
            "total_routes": total,
            "coverage": coverage,
            "null_counts": null_counts,
        }

    @staticmethod
    def _table_exists(conn) -> bool:
        cursor = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            [Config.TCA_ROUTE_SUMMARY_TABLE],
        )
        return cursor.fetchone() is not None

    @staticmethod
    def _empty_result(
        start_date: str,
        end_date: str,
        selected: list[str],
        group_by_exchange: bool,
        warning: str,
    ) -> dict[str, Any]:
        return {
            "start_date": start_date,
            "end_date": end_date,
            "metrics": selected,
            "bdib_dependent_metrics": [m for m in selected if m in BDIB_DEPENDENT_METRICS],
            "group_by_exchange": group_by_exchange,
            "rows": [],
            "data_source_warning": warning,
        }

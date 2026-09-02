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

#: 38 项指标为 NULL 时的结构性原因分类。
#: 含义: "source"=源值层始终非空(无 NULL); "closing_auction"=全收盘竞价成交时 NULL(期望内);
#: "single_fill"=单笔/同刻成交时 NULL(期望内); "bdib_cutoff"=盘中窗口边缘未命中(残余, 纯竞价
#: 路由已由末 bar 语义对齐修复); "bdib_missing"=该 ticker/date 完全无 BDIB bars(真缺口);
#: "next_day_close"=缺次日 daily_close; "fx"=缺 fx_rate 回补。
#: 注: BDIB bar 时间戳为区间起点语义，末 bar 覆盖 [timestamp, 收盘竞价结束) 并包含
#: 竞价时段成交量 —— 纯竞价路由的 par_rate/pnl_vwap/par_rate_close 分母取末 bar
#: （tca_route_metrics._is_auction_fill / _last_bar_window），不再因时间点错位成 NULL。
METRIC_NULL_REASON: dict[str, str] = {
    # 原有 18 项
    "fill_count": "source", "fill": "source", "fill_continuous": "source", "fill_close": "source",
    "par_rate": "bdib_cutoff", "par_rate_continuous": "closing_auction", "par_rate_close": "bdib_cutoff",
    "p_avg": "source", "p_avg_continuous": "closing_auction",
    "pnl_vwap": "bdib_cutoff", "pnl_vwap_continuous": "closing_auction",
    "RPM": "source", "RPM_continuous": "closing_auction",
    "pwp_5": "bdib_cutoff", "pwp_10": "bdib_cutoff", "pwp_15": "bdib_cutoff",
    "pwp_20": "bdib_cutoff", "pwp_25": "bdib_cutoff",
    # Phase 0
    "p_arrival": "bdib_missing", "p_close": "bdib_missing",
    "arrival_cost_bps": "bdib_missing", "close_cost_bps": "bdib_missing",
    "opportunity_cost": "bdib_missing",
    # Phase 1
    "p_decision": "bdib_missing", "delay_cost": "bdib_missing", "trading_cost": "bdib_missing",
    "wagner_is": "bdib_missing", "wagner_is_bps": "bdib_missing",
    "cost_stddev": "single_fill", "cost_p95": "single_fill", "cost_cvar": "single_fill",
    "order_duration_sec": "single_fill", "exec_rate_shares_per_min": "single_fill",
    "temp_impact_5min_bps": "bdib_cutoff", "temp_impact_10min_bps": "bdib_cutoff",
    "temp_impact_30min_bps": "bdib_cutoff",
    "perm_impact_bps": "next_day_close", "recovery_truncated": "source",
    # 007
    "fx_rate": "fx",
}
#: 期望内 NULL 豁免集合（closing_auction + single_fill 类指标，SLA 中应排除）
EXPECTED_NULL_METRICS: frozenset[str] = frozenset({
    m for m, r in METRIC_NULL_REASON.items() if r in ("closing_auction", "single_fill")
})

#: SLA 覆盖率的分母口径：按 NULL 原因剔除"结构内必然 NULL"的路由。
#:   closing_auction → 分母剔除纯竞价路由（fill_close >= fill，无连续执行过程，
#:                     continuous 类指标必然 NULL）；single_fill → 分母 = fill_count>=2
#:   （单笔/同刻成交的方差/时长无法定义）；其余原因 → 分母 = 全部路由。
SLA_DENOMINATOR_BY_REASON: dict[str, str] = {
    "closing_auction": "non_pure_auction",
    "single_fill": "multi_fill",
    "source": "total",
    "bdib_cutoff": "total",
    "bdib_missing": "total",
    "next_day_close": "total",
    "fx": "total",
}


def metric_null_reasons(metrics: Optional[list[str]] = None) -> dict[str, str]:
    """返回所选指标的 NULL 原因分类映射。"""
    selected = validate_metrics(metrics) if metrics else list(COMPUTED_METRICS)
    return {m: METRIC_NULL_REASON[m] for m in selected}


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
                          "coverage": {m: pct},          # 原始口径（分母剔除白名单外交易所）
                          "sla_coverage": {m: pct},      # SLA 口径（再剔除 closing_auction/single_fill 结构内 NULL）
                          "null_counts": {m: n}}],
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
            "null_reasons": metric_null_reasons(selected),
            "expected_null_metrics": sorted(EXPECTED_NULL_METRICS),
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
        """单条聚合 SQL 完成全部指标的覆盖率统计。

        分母口径与 bdib_health 对齐：白名单（Config.BDIB_EXCHANGE）外交易所
        本就不拉 BDIB、指标必然 NULL，计入分母会虚降覆盖率观感（out-of-scope
        非数据缺失）。同时聚合纯竞价/多笔路由计数，供 SLA 覆盖率剔除结构内 NULL。
        """
        metric_aggs = ", ".join(
            f"SUM(CASE WHEN {m} IS NOT NULL THEN 1 ELSE 0 END) AS nn_{m}"
            for m in selected
        )
        group_cols = "order_as_of_date, Exchange" if group_by_exchange else "order_as_of_date"
        whitelist = tuple(
            str(e).strip().upper() for e in Config.BDIB_EXCHANGE if str(e).strip()
        )
        where = "order_as_of_date BETWEEN ? AND ?"
        params: list[Any] = [start_date, end_date]
        if whitelist:
            placeholders = ", ".join(["?"] * len(whitelist))
            where += f" AND UPPER(Exchange) IN ({placeholders})"
            params.extend(whitelist)
        sql = f"""
            SELECT {group_cols}, COUNT(*) AS total_routes,
                SUM(CASE WHEN fill > 0 AND fill_close >= fill THEN 1 ELSE 0 END) AS pure_auction,
                SUM(CASE WHEN fill_count >= 2 THEN 1 ELSE 0 END) AS multi_fill,
                {metric_aggs}
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            WHERE {where}
            GROUP BY {group_cols}
            ORDER BY {group_cols}
        """
        cursor = conn.execute(sql, params)
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
        """把聚合行转换为 {coverage, sla_coverage, null_counts} 结构。"""
        total = int(row["total_routes"])
        pure_auction = int(row.get("pure_auction") or 0)
        multi_fill = int(row.get("multi_fill") or 0)
        coverage: dict[str, Optional[float]] = {}
        sla_coverage: dict[str, Optional[float]] = {}
        null_counts: dict[str, int] = {}
        for m in selected:
            nn = int(row[f"nn_{m}"] or 0)
            null_counts[m] = total - nn
            coverage[m] = round(nn / total * 100.0, 2) if total > 0 else None
            reason = METRIC_NULL_REASON.get(m)
            denom_key = SLA_DENOMINATOR_BY_REASON.get(reason, "total")
            denom = {"total": total, "non_pure_auction": total - pure_auction,
                     "multi_fill": multi_fill}[denom_key]
            sla_coverage[m] = round(nn / denom * 100.0, 2) if denom > 0 else None
        return {
            "date": row["order_as_of_date"],
            "exchange": row.get("Exchange") if group_by_exchange else None,
            "total_routes": total,
            "coverage": coverage,
            "sla_coverage": sla_coverage,
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
            "null_reasons": metric_null_reasons(selected),
            "expected_null_metrics": sorted(EXPECTED_NULL_METRICS),
            "group_by_exchange": group_by_exchange,
            "rows": [],
            "data_source_warning": warning,
        }

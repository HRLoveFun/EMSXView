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

from data_access.config import Config
from data_access.storage.connection import AccessTier, ConnectionManager

from . import report_measure as rm

logger = logging.getLogger(__name__)

#: 38 项计算指标白名单（与上游数据契约 platform_data/contracts/tca_contracts.py::
#: TcaRouteSummary 的计算列保持一致；实际列计算在唯一写入方独立仓库 EMSXDataPipeline
#: 的 tca_route_metrics.py，本仓库只读消费、不 import；
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
#: "next_day_close"=缺次日 daily_close; "conditional"=条件性写入列(非"始终非空")。
#: 注: BDIB bar 时间戳为区间起点语义，末 bar 覆盖 [timestamp, 收盘竞价结束) 并包含
#: 竞价时段成交量 —— 纯竞价路由的 par_rate/pnl_vwap/par_rate_close 分母取末 bar
#: （写入方 tca_route_metrics._is_auction_fill / _last_bar_window），不再因时间点错位成 NULL。
#: 键集合必须与 COMPUTED_METRICS 完全一致（由 test_report_metrics 断言）。
#: 注: fx_rate 不在 COMPUTED_METRICS 内，故亦不在此表 —— fx 数据质量由 KPI 卡片
#: 的 fx_coverage（换算成功率）单独承载，避免两处口径分离。
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
    "perm_impact_bps": "next_day_close",
    # 跨日恢复标记：由写入方条件性置 1（默认 0），非"始终非空"语义，单列一类
    "recovery_truncated": "conditional",
}
#: 期望内 NULL 豁免集合（closing_auction + single_fill 类指标，SLA 中应排除）
EXPECTED_NULL_METRICS: frozenset[str] = frozenset({
    m for m, r in METRIC_NULL_REASON.items() if r in ("closing_auction", "single_fill")
})

#: SLA 覆盖率的分母口径：按 NULL 原因剔除"结构内必然 NULL"的路由。
#:   closing_auction → 分母剔除纯竞价路由（fill_close >= fill 或零成交，无连续执行
#:                     过程，continuous 类指标必然 NULL；零成交路由（fill 为
#:                     0/NULL）的 continuous 指标同为结构内必然 NULL，一并豁免，
#:                     此前仅按 fill > 0 AND fill_close >= fill 判定而漏掉零成交）；
#:   single_fill → 分母 = fill_count>=2（单笔/同刻成交的方差/时长无法定义）；
#:   bdib_missing → 分母剔除「BDIB 缺口路由」（有成交但核心 BDIB 依赖指标全 NULL，
#:                   见 BDIB_GAP_PROBE_METRICS）—— 无行情时到达价/收盘价类指标
#:                   与 closing_auction 同为"结构内必然"，不豁免会让 SLA 口径
#:                   随管道缺口波动，与原始口径失去区分度；
#:   其余原因 → 分母 = 全部路由。
SLA_DENOMINATOR_BY_REASON: dict[str, str] = {
    "closing_auction": "non_pure_auction",
    "single_fill": "multi_fill",
    "source": "total",
    "conditional": "total",
    "bdib_cutoff": "total",
    "bdib_missing": "non_bdib_gap",
    "next_day_close": "total",
}

#: BDIB 缺口路由探针（SLA 分母用）：有成交但四项核心 BDIB 依赖指标全 NULL 的路由，
#: 视为「该 ticker/date 完全无 BDIB 行情」的结构缺数。探针在 tca 表内自洽计算，
#: 无需跨服务注入健康扫描结果（健康扫描为重 IO 且与覆盖率查询独立缓存）。
BDIB_GAP_PROBE_METRICS: tuple[str, ...] = ("par_rate", "pnl_vwap", "p_arrival", "p_close")


def metric_null_reasons(metrics: Optional[list[str]] = None) -> dict[str, str]:
    """返回所选指标的 NULL 原因分类映射（未登记指标按 'source' 兜底）。"""
    selected = validate_metrics(metrics) if metrics else list(COMPUTED_METRICS)
    return {m: METRIC_NULL_REASON.get(m, "source") for m in selected}


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


def _consistency_pct(total: int, bad: int) -> Optional[float]:
    """一致性百分比 = (1 - 异常数 / 总数) × 100（无样本时 None）。"""
    if total <= 0:
        return None
    return round((1.0 - bad / total) * 100.0, 2)


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
        scope: Optional[rm.ReportScope] = None,
    ) -> dict[str, Any]:
        """按日期（可选 ×Exchange）统计各指标非 NULL 率。

        scope 为报告作用域（None → 默认 BDIB 白名单口径），与 KPI / 异常 / 健康扫描
        共用同一分母：白名单外市场本就不拉 BDIB、指标必然 NULL；用户按市场过滤时
        （scope = 用户口径）覆盖率同步收窄，报告内两处数字因此可对账。

        Returns:
            {
                "start_date":..., "end_date":..., "metrics": [...],
                "bdib_dependent_metrics": [...],
                "group_by_exchange": bool, "scope": {...},
                "rows": [{"date", "exchange", "total_routes",
                          "coverage": {m: pct},          # 原始口径（分母剔除白名单外交易所）
                          "sla_coverage": {m: pct},      # SLA 口径（再剔除 closing_auction/single_fill 结构内 NULL）
                          "null_counts": {m: n}}],
            }
            表不存在时 rows 为空并附 data_source_warning。
        """
        selected = validate_metrics(metrics)
        resolved = scope or rm.resolve_scope(None)
        conn = None
        consistency: Optional[dict[str, Any]] = None
        try:
            conn = self._mgr.get_connection("fill_bdib", AccessTier.READ)
            if not self._table_exists(conn):
                return self._empty_result(
                    start_date, end_date, selected, group_by_exchange, resolved,
                    warning="tca_route_summary 不存在 — 请先运行管道 S5.5",
                )
            rows = self._query_coverage(
                conn, start_date, end_date, selected, group_by_exchange, resolved,
            )
            consistency = self._query_consistency(conn, start_date, end_date, resolved)
        except FileNotFoundError:
            # 只读模式下 fill_bdib.db 缺失 → 空覆盖率（与表缺失同语义, 009）
            return self._empty_result(
                start_date, end_date, selected, group_by_exchange, resolved,
                warning="tca_route_summary 不存在 — 请先运行管道 S5.5",
            )
        finally:
            if conn is not None:
                conn.close()

        overall = MetricCoverageService._overall_coverage(rows)
        for row in rows:
            row.pop("_sla_raw", None)
        return {
            "start_date": start_date,
            "end_date": end_date,
            "metrics": selected,
            "bdib_dependent_metrics": [m for m in selected if m in BDIB_DEPENDENT_METRICS],
            "null_reasons": metric_null_reasons(selected),
            "expected_null_metrics": sorted(EXPECTED_NULL_METRICS),
            "group_by_exchange": group_by_exchange,
            "scope": resolved.to_payload(),
            "overall": overall,
            "consistency": consistency,
            "rows": rows,
        }

    def _query_coverage(
        self,
        conn,
        start_date: str,
        end_date: str,
        selected: list[str],
        group_by_exchange: bool,
        scope: rm.ReportScope,
    ) -> list[dict[str, Any]]:
        """单条聚合 SQL 完成全部指标的覆盖率统计。

        分母口径与 bdib_health / KPI / 异常明细一致（report_measure 作用域唯一实现）：
        白名单外交易所本就不拉 BDIB、指标必然 NULL，计入分母会虚降覆盖率观感
        （out-of-scope 非数据缺失）。同时聚合纯竞价/多笔/BDIB 缺口路由计数，供
        SLA 覆盖率剔除结构内 NULL（分母口径见 SLA_DENOMINATOR_BY_REASON）。
        """
        metric_aggs = ", ".join(
            f"SUM(CASE WHEN {m} IS NOT NULL THEN 1 ELSE 0 END) AS nn_{m}"
            for m in selected
        )
        # 纯竞价判定把零成交（fill 为 0/NULL）一并豁免：该情形下 continuous 类
        # 指标同为结构内必然 NULL，留在分母会让 SLA 口径混入与质量无关的缺数
        probe_all_null = " AND ".join(
            f"{m} IS NULL" for m in BDIB_GAP_PROBE_METRICS
        )
        group_cols = "order_as_of_date, Exchange" if group_by_exchange else "order_as_of_date"
        where, params = self._scope_where(start_date, end_date, scope)
        sql = f"""
            SELECT {group_cols}, COUNT(*) AS total_routes,
                SUM(CASE WHEN COALESCE(fill, 0) = 0 OR fill_close >= fill
                         THEN 1 ELSE 0 END) AS pure_auction,
                SUM(CASE WHEN fill_count >= 2 THEN 1 ELSE 0 END) AS multi_fill,
                SUM(CASE WHEN COALESCE(fill, 0) > 0 AND {probe_all_null}
                         THEN 1 ELSE 0 END) AS bdib_gap,
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
    def _scope_where(
        start_date: str, end_date: str, scope: Optional[rm.ReportScope] = None,
    ) -> tuple[str, list[Any]]:
        """覆盖率 / 一致性共享的过滤范围：日期区间 + 作用域（默认 BDIB 白名单）。

        作用域由 report_measure 唯一实现，与 KPI / 异常明细 / 健康扫描同源：
        白名单外交易所本就不拉 BDIB、指标必然 NULL，计入分母会虚降覆盖率观感。
        """
        condition, values = rm.scope_condition(scope or rm.resolve_scope(None))
        where = "order_as_of_date BETWEEN ? AND ?"
        if condition:
            return f"{where} AND {condition}", [start_date, end_date, *values]
        return where, [start_date, end_date]

    @staticmethod
    def _query_consistency(
        conn, start_date: str, end_date: str, scope: Optional[rm.ReportScope] = None,
    ) -> dict[str, Any]:
        """数据一致性探针（013 + P1-a）：overfill / 订单参与率越界 / 金额列同源性。

        与异常判定（overfill_pct / order_par_gt100 规则）同源，但此处给出整体
        比例，不受异常清单截断影响，供报告头「数据质量提示」区展示。
        订单级聚合（(OrderId, order_as_of_date, Exchange) 求和）与异常明细共用
        report_measure 的唯一实现，避免两处口径分叉；分母同作用域。
        D7：Amount（写入方预置列）与 KPI 的 fill × p_avg 成交额口径做同一性
        校验（0.5% 相对容差覆盖舍入与最小价位跳动），仅披露不替换 —— Amount
        是异常表展示的权威列。D17：order_par >200% 单独分档（critical 档，
        疑重复记账），使提示区能区分「越界」与「几乎必然数据矛盾」的规模。
        """
        where, params = MetricCoverageService._scope_where(start_date, end_date, scope)
        # D7 容差：|Amount - fill×p_avg| > 0.5% × max(|fill×p_avg|, 1)
        _AMOUNT_TOLERANCE = 0.005
        route_row = conn.execute(
            f"""
            SELECT COUNT(*) AS total_routes,
                   SUM(CASE WHEN fill IS NOT NULL AND RouteShares IS NOT NULL
                            AND RouteShares > 0 AND fill > RouteShares
                            THEN 1 ELSE 0 END) AS overfill_routes,
                   SUM(CASE WHEN Amount IS NOT NULL AND fill IS NOT NULL
                            AND p_avg IS NOT NULL THEN 1 ELSE 0 END) AS amount_check_total,
                   SUM(CASE WHEN Amount IS NOT NULL AND fill IS NOT NULL
                            AND p_avg IS NOT NULL
                            AND ABS(Amount - fill * p_avg)
                                > {_AMOUNT_TOLERANCE} * MAX(ABS(fill * p_avg), 1.0)
                            THEN 1 ELSE 0 END) AS amount_mismatch_routes
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            WHERE {where}
            """,
            params,
        ).fetchone()
        order_par = rm.order_par_aggregate_sql(where, alias="order_par")
        order_row = conn.execute(
            f"""
            SELECT COUNT(*) AS total_orders,
                   SUM(CASE WHEN par_sum > 1.0 THEN 1 ELSE 0 END) AS gt100_orders,
                   SUM(CASE WHEN par_sum > {rm.ORDER_PAR_CRITICAL_SUM}
                            THEN 1 ELSE 0 END) AS gt200_orders
            FROM {order_par}
            """,
            params,
        ).fetchone()
        total_routes = int(route_row[0] or 0)
        overfill_routes = int(route_row[1] or 0)
        amount_check_total = int(route_row[2] or 0)
        amount_mismatch_routes = int(route_row[3] or 0)
        total_orders = int(order_row[0] or 0)
        gt100_orders = int(order_row[1] or 0)
        gt200_orders = int(order_row[2] or 0)
        return {
            "total_routes": total_routes,
            "overfill_routes": overfill_routes,
            "completion_consistency_pct": _consistency_pct(total_routes, overfill_routes),
            "total_orders": total_orders,
            "order_par_gt100_orders": gt100_orders,
            "order_par_gt200_orders": gt200_orders,
            "order_par_consistency_pct": _consistency_pct(total_orders, gt100_orders),
            # D7：金额列同源性（可校验路由 = Amount 与 fill×p_avg 均非 NULL）
            "amount_check_routes": amount_check_total,
            "amount_mismatch_routes": amount_mismatch_routes,
            "amount_consistency_pct": _consistency_pct(
                amount_check_total, amount_mismatch_routes,
            ),
        }

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
        bdib_gap = int(row.get("bdib_gap") or 0)
        coverage: dict[str, Optional[float]] = {}
        sla_coverage: dict[str, Optional[float]] = {}
        null_counts: dict[str, int] = {}
        # 内部字段：各指标的 (非 NULL 数, SLA 分母)，供整体覆盖率汇总后剔除
        sla_raw: dict[str, tuple[int, int]] = {}
        for m in selected:
            nn = int(row[f"nn_{m}"] or 0)
            null_counts[m] = total - nn
            coverage[m] = round(nn / total * 100.0, 2) if total > 0 else None
            reason = METRIC_NULL_REASON.get(m)
            denom_key = SLA_DENOMINATOR_BY_REASON.get(reason, "total")
            denom = {"total": total, "non_pure_auction": total - pure_auction,
                     "multi_fill": multi_fill,
                     "non_bdib_gap": total - bdib_gap}[denom_key]
            sla_coverage[m] = round(nn / denom * 100.0, 2) if denom > 0 else None
            sla_raw[m] = (nn, denom)
        return {
            "date": row["order_as_of_date"],
            "exchange": row.get("Exchange") if group_by_exchange else None,
            "total_routes": total,
            # BDIB 缺口路由数（SLA 分母豁免规模）：随行披露使豁免可见、可审计
            # （探针的边界情形——bdib_cutoff 残余被误豁免——的规模由此可观测）
            "bdib_gap_routes": bdib_gap,
            "coverage": coverage,
            "sla_coverage": sla_coverage,
            "null_counts": null_counts,
            "_sla_raw": sla_raw,
        }

    @staticmethod
    def _overall_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
        """全区间整体覆盖率（全部 日期×指标 单元格汇总后的一次性比率）。

        原始口径：Σ非NULL / Σ总路由数；SLA 口径：Σ非NULL / ΣSLA 分母
        （已剔除结构性必然 NULL）。供报告头 KPI 展示，避免只看单日跳动。
        """
        nn_total = denom_total = 0
        sla_nn_total = sla_denom_total = 0
        for row in rows:
            total = int(row["total_routes"])
            sla_raw = row.get("_sla_raw") or {}
            for m, null_count in (row.get("null_counts") or {}).items():
                nn_total += total - int(null_count)
                denom_total += total
                nn, denom = sla_raw.get(m, (0, 0))
                sla_nn_total += nn
                sla_denom_total += denom
        return {
            "coverage": (
                round(nn_total / denom_total * 100.0, 2) if denom_total else None
            ),
            "sla_coverage": (
                round(sla_nn_total / sla_denom_total * 100.0, 2)
                if sla_denom_total else None
            ),
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
        scope: rm.ReportScope,
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
            "scope": scope.to_payload(),
            "overall": None,
            "consistency": None,
            "rows": [],
            "data_source_warning": warning,
        }

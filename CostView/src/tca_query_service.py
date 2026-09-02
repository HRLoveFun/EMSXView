"""TCA Query Service — orchestrator for Transaction Cost Analysis.

All SQL parameters are bound via ? placeholders (never f-string interpolation
of user input) to prevent SQL injection.

Delegates heavy lifting to sub-modules:
    tca_utils.py         — pure functions (date/time, numeric, cohort bucketing, scorecard)
    tca_query_builder.py — SQL query functions

Type definitions live in platform_data/contracts/tca_contracts.py
and are re-exported here for caller convenience.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

from platform_data.contracts import (
    SCORECARD_COHORTS,
    ScorecardFilters,
    ScorecardReport,
    TcaFilters,
    TcaOrderAggregate,
    TcaReport,
    TcaRouteSummary,
)
from DataPipeline.storage.connection import AccessTier, ConnectionManager
from DataPipeline.config import Config

from .tca_utils import (
    aggregate_cohorts as _aggregate_cohorts,
    filters_to_dict as _filters_to_dict,
    resolve_date_defaults as _resolve_date_defaults,
    scorecard_filters_to_dict as _scorecard_filters_to_dict,
)

from .tca_query_builder import (
    get_tca_route_summaries as _get_tca_route_summaries,
    get_time_series as _get_time_series,
)

logger = logging.getLogger(__name__)


class TcaQueryService:
    """Builds dynamic parameterized TCA queries and assembles TcaReports."""

    def __init__(
        self,
        connection_manager: Optional[ConnectionManager] = None,
        proc_fills_db_path: Optional[str] = None,
        fill_bdib_db_path: Optional[str] = None,
        raw_bdib_db_path: Optional[str] = None,
        raw_fills_db_path: Optional[str] = None,
    ):
        if connection_manager is not None:
            self._mgr = connection_manager
        elif any([proc_fills_db_path, fill_bdib_db_path, raw_bdib_db_path, raw_fills_db_path]):
            overrides: dict[str, Path] = {}
            if proc_fills_db_path:
                overrides["processed_fills"] = Path(proc_fills_db_path)
            if fill_bdib_db_path:
                overrides["fill_bdib"] = Path(fill_bdib_db_path)
            if raw_bdib_db_path:
                overrides["raw_bdib"] = Path(raw_bdib_db_path)
            if raw_fills_db_path:
                overrides["raw_fills"] = Path(raw_fills_db_path)
            self._mgr = ConnectionManager(path_overrides=overrides)
        else:
            self._mgr = ConnectionManager()

    def has_data_for_date(self, date_str: str) -> bool:
        """tca_route_summary 在指定日期（YYYYMMDD）是否有数据。

        用于 analyze 端点在"默认日期"场景下探测数据是否已生成，
        表不存在或无记录均返回 False。

        009-external-data-store：只读连接在库文件缺失时抛 FileNotFoundError，
        与表缺失同样降级为 False。
        """
        conn = None
        try:
            conn = self._mgr.get_connection("fill_bdib", AccessTier.READ)
            cursor = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
                [Config.TCA_ROUTE_SUMMARY_TABLE],
            )
            if cursor.fetchone() is None:
                return False
            row = conn.execute(
                f"SELECT 1 FROM {Config.TCA_ROUTE_SUMMARY_TABLE} "
                "WHERE order_as_of_date = ? LIMIT 1",
                [date_str],
            ).fetchone()
            return row is not None
        except Exception as exc:
            logger.warning("探测 tca_route_summary 数据失败(%s): %s", date_str, exc)
            return False
        finally:
            if conn is not None:
                conn.close()

    def build_tca_report(self, filters: TcaFilters) -> TcaReport:
        """Assemble a complete TcaReport for the given filters.

        主路径：从 tca_route_summary 表直读 34 字段 per-route 数据。
        如果该表不存在或为空，返回 data_source_warning 提示运行 pipeline S5.5。
        """
        filters = _resolve_date_defaults(filters)

        rows, total = _get_tca_route_summaries(self._mgr, filters)
        if not rows:
            return TcaReport(
                filters=_filters_to_dict(filters),
                total_orders=0, offset=filters.offset, limit=filters.limit,
                orders=[],
                data_source_warning=(
                    "tca_route_summary is empty — pipeline stage 5.5 has not yet run. "
                    "Trigger an update via POST /api/tca/trigger-update."
                ),
            )

        # 为图表保留 fallback 时序数据
        route_keys = [(r["OrderId"], r["RouteId"], r["order_as_of_date"]) for r in rows]
        time_series_map = _get_time_series(self._mgr, route_keys)

        orders = self._assemble_report(rows, time_series_map)

        return TcaReport(
            filters=_filters_to_dict(filters),
            total_orders=total, offset=filters.offset, limit=filters.limit,
            orders=orders,
        )

    def build_scorecard(self, filters: ScorecardFilters) -> ScorecardReport:
        """Build broker/strategy cohort scorecard over completed TCA routes."""
        cohort = (filters.cohort or "broker_strategy").strip().lower()
        if cohort not in SCORECARD_COHORTS:
            raise ValueError(
                f"Unsupported scorecard cohort {cohort!r}; "
                f"expected one of {SCORECARD_COHORTS}"
            )
        min_sample = max(1, int(filters.min_sample_size or 1))
        max_routes = max(1, int(filters.max_orders or 2000))

        page_size = min(500, max_routes)
        collected: list[TcaRouteSummary] = []
        warning: Optional[str] = None
        capped = False
        offset = 0
        while True:
            base_filters = TcaFilters(
                order_ids=filters.order_ids, algo=filters.algo,
                start_date=filters.start_date, end_date=filters.end_date,
                broker=filters.broker, symbol=filters.symbol,
                aggregation="per_order", limit=page_size, offset=offset,
            )
            page = self.build_tca_report(base_filters)
            if page.data_source_warning and not collected:
                warning = page.data_source_warning
            collected.extend(page.orders)
            if len(collected) >= max_routes:
                collected = collected[:max_routes]
                if page.total_orders > max_routes:
                    capped = True
                break
            if len(collected) >= page.total_orders or not page.orders:
                break
            offset += page.limit

        filters_dict = _scorecard_filters_to_dict(filters)
        if warning and not collected:
            return ScorecardReport(
                filters=filters_dict, cohort=cohort,
                min_sample_size=min_sample, total_orders_considered=0,
                total_orders_capped=False, cohorts=[],
                data_source_warning=warning,
            )

        cohorts = _aggregate_cohorts(collected, cohort, min_sample)
        return ScorecardReport(
            filters=filters_dict, cohort=cohort,
            min_sample_size=min_sample,
            total_orders_considered=len(collected),
            total_orders_capped=capped, cohorts=cohorts,
            data_source_warning=warning,
        )

    def build_order_report(self, filters: TcaFilters) -> list[TcaOrderAggregate]:
        """将路由级 TCA 结果聚合为 order 级汇总（003-tca-core-benchmarks）。

        聚合规则（见 specs/003-tca-core-benchmarks/plan.md §3.2）:
        - 货币成本: SUM
        - 价格基准: 最早 route（按 order_as_of_date + RouteId 排序稳定取首）
        - bps 绩效: 成交额加权平均 (权重 = fill × p_avg)
        - 完成率: Σfill / Σroute_shares
        - 风险: order 取 max（保守）
        - 时点: min(route 历时) / 最大成交额 route 的历时

        仅当 TCA_ORDER_AGG_ENABLED 开启时聚合（否则返回空列表）。
        """
        if not Config.TCA_ORDER_AGG_ENABLED:
            return []

        filters = _resolve_date_defaults(filters)
        rows, _ = _get_tca_route_summaries(self._mgr, filters)
        if not rows:
            return []

        # 按 (OrderId, order_as_of_date) 分组
        groups: dict[tuple[str, str], list[dict]] = {}
        for r in rows:
            key = (r["OrderId"], r["order_as_of_date"])
            groups.setdefault(key, []).append(r)

        aggregates: list[TcaOrderAggregate] = []
        for (order_id, oad), routes in groups.items():
            aggregates.append(self._aggregate_order(order_id, oad, routes))
        return aggregates

    @staticmethod
    def _aggregate_order(order_id: str, oad: str, routes: list[dict]) -> TcaOrderAggregate:
        """按聚合策略合并单订单的多条 route。"""
        def _num(v) -> Optional[float]:
            if v is None:
                return None
            try:
                f = float(v)
                return f if f == f else None  # 清理 NaN
            except (TypeError, ValueError):
                return None

        def _first(attr: str) -> Optional[Any]:
            for r in routes:
                v = r.get(attr)
                if v is not None:
                    return v
            return None

        # 货币成本 SUM
        def _sum(attr: str) -> Optional[float]:
            vals = [_num(r.get(attr)) for r in routes]
            vals = [v for v in vals if v is not None]
            return sum(vals) if vals else None

        # 成交额加权 bps
        def _weighted_bps(attr: str) -> Optional[float]:
            num_w = 0.0
            den_w = 0.0
            for r in routes:
                bps = _num(r.get(attr))
                fill = _num(r.get("fill"))
                pavg = _num(r.get("p_avg"))
                if bps is None or fill is None or pavg is None:
                    continue
                w = fill * pavg
                if w > 0:
                    num_w += bps * w
                    den_w += w
            return (num_w / den_w) if den_w > 0 else None

        route_shares = sum(
            (_num(r.get("RouteShares")) or 0) for r in routes
        )
        fill = sum((_num(r.get("fill")) or 0) for r in routes)

        # 风险：order 取 max（保守）
        def _max(attr: str) -> Optional[float]:
            vals = [_num(r.get(attr)) for r in routes]
            vals = [v for v in vals if v is not None]
            return max(vals) if vals else None

        return TcaOrderAggregate(
            OrderId=order_id,
            order_as_of_date=oad,
            equ_ticker=_first("equ_ticker"),
            Exchange=_first("Exchange"),
            Side=_first("Side"),
            Broker=_first("Broker"),
            algo=_first("algo"),
            TraderName=_first("TraderName"),
            route_count=len(routes),
            fill_count=sum((_num(r.get("fill_count")) or 0) for r in routes),
            delay_cost=_sum("delay_cost"),
            trading_cost=_sum("trading_cost"),
            opportunity_cost=_sum("opportunity_cost"),
            wagner_is=_sum("wagner_is"),
            p_arrival=_first("p_arrival"),
            p_decision=_first("p_decision"),
            p_close=_first("p_close"),
            arrival_cost_bps=_weighted_bps("arrival_cost_bps"),
            close_cost_bps=_weighted_bps("close_cost_bps"),
            wagner_is_bps=_weighted_bps("wagner_is_bps"),
            temp_impact_5min_bps=_weighted_bps("temp_impact_5min_bps"),
            temp_impact_10min_bps=_weighted_bps("temp_impact_10min_bps"),
            temp_impact_30min_bps=_weighted_bps("temp_impact_30min_bps"),
            perm_impact_bps=_weighted_bps("perm_impact_bps"),
            fill=fill if fill > 0 else None,
            route_shares=route_shares if route_shares > 0 else None,
            par_rate=(fill / route_shares) if route_shares > 0 else None,
            cost_stddev=_max("cost_stddev"),
            cost_p95=_max("cost_p95"),
            cost_cvar=_max("cost_cvar"),
            order_duration_sec=_max("order_duration_sec"),
            exec_rate_shares_per_min=(
                (fill / max(_max("order_duration_sec") or 1, 1) * 60.0)
                if _max("order_duration_sec")
                else None
            ),
            recovery_truncated=max((_num(r.get("recovery_truncated")) or 0) for r in routes) if routes else None,
        )

    def _assemble_report(
        self, route_rows: list[dict], time_series_map: dict,
    ) -> list[TcaRouteSummary]:
        """将 tca_route_summary 行转换为 TcaRouteSummary 对象。"""
        summaries: list[TcaRouteSummary] = []
        for r in route_rows:
            key = (r["OrderId"], r["RouteId"], r["order_as_of_date"])
            ts = time_series_map.get(key, [])
            summaries.append(self._row_to_route_summary(r, ts))
        return summaries

    def _row_to_route_summary(self, row: dict, time_series: list[dict]) -> TcaRouteSummary:
        """把数据库行映射为 TcaRouteSummary 数据类。"""
        # 将数据库行中的字段名直接映射到 TcaRouteSummary；时序数据作为额外字段
        # 附加在返回的 dict 中供前端使用（不在数据类定义内）。
        data = {k: row.get(k) for k in TcaRouteSummary.__dataclass_fields__}
        # 清理 NaN
        for k, v in data.items():
            if isinstance(v, float) and v != v:
                data[k] = None
        # 时序数据作为额外字段注入
        data["time_series"] = time_series
        return TcaRouteSummary(**data)

    # ── Connection helpers ──────────────────────────────────────────────────

    def _proc_fills_conn(self):
        return self._mgr.get_connection("processed_fills", AccessTier.READ, row_factory=sqlite3.Row)

    def _fill_bdib_conn(self):
        return self._mgr.get_connection("fill_bdib", AccessTier.READ)

    def _raw_bdib_conn(self):
        return self._mgr.get_connection("raw_bdib", AccessTier.READ, row_factory=sqlite3.Row)

    def _raw_fills_conn(self):
        return self._mgr.get_connection("raw_fills", AccessTier.READ)

    @staticmethod
    def _table_exists(conn, table_name: str) -> bool:
        cursor = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ? LIMIT 1",
            [table_name],
        )
        return cursor.fetchone() is not None


# 兼容旧导入：TcaOrderSummary/TcaRouteDetail 仍可访问
from platform_data.contracts import TcaOrderSummary, TcaRouteDetail  # noqa: E402,F401

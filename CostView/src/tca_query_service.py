"""TCA Query Service — orchestrator for Transaction Cost Analysis.

All SQL parameters are bound via ? placeholders (never f-string interpolation
of user input) to prevent SQL injection.

Delegates heavy lifting to sub-modules:
    tca_utils.py         — pure functions (date/time, numeric, cohort bucketing, scorecard)
    tca_query_builder.py — SQL query functions
    tca_fallback.py      — raw-BDIB backfill for missing fill_bdib data

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
    get_tca_route_summaries_by_keys as _get_tca_route_summaries_by_keys,
    get_time_series as _get_time_series,
)

from .tca_fallback import (
    get_route_metric_fallbacks as _get_route_metric_fallbacks,
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

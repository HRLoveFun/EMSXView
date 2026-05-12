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
    TcaOrderSummary,
    TcaReport,
    TcaRouteDetail,
)
from DataPipeline.storage.connection import AccessTier, ConnectionManager
from DataPipeline.config import Config

from .tca_utils import (
    aggregate_cohorts as _aggregate_cohorts,
    filters_to_dict as _filters_to_dict,
    mean_numeric as _mean_numeric,
    resolve_date_defaults as _resolve_date_defaults,
    scorecard_filters_to_dict as _scorecard_filters_to_dict,
)

from .tca_query_builder import (
    get_market_context as _get_market_context,
    get_matching_routes as _get_matching_routes,
    get_order_fill_stats as _get_order_fill_stats,
    get_tca_metrics as _get_tca_metrics,
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
        """Assemble a complete TcaReport for the given filters."""
        filters = _resolve_date_defaults(filters)

        route_rows, total_orders = _get_matching_routes(self._mgr, filters)
        if not route_rows:
            return TcaReport(
                filters=_filters_to_dict(filters),
                total_orders=0, offset=filters.offset, limit=filters.limit,
                orders=[], data_source_warning=None,
            )

        route_keys = [(r["order_id"], r["route_id"], r["order_as_of_date"]) for r in route_rows]
        tca_metrics = _get_tca_metrics(self._mgr, route_keys)

        if not tca_metrics:
            return TcaReport(
                filters=_filters_to_dict(filters),
                total_orders=total_orders, offset=filters.offset, limit=filters.limit,
                orders=[],
                data_source_warning=(
                    "fill_bdib.db is empty — pipeline stages 5 & 6 have not yet run. "
                    "Trigger an update via POST /api/tca/trigger-update."
                ),
            )

        time_series_map = _get_time_series(self._mgr, route_keys)
        tickers_and_dates = {
            (r["equ_ticker"], r["order_as_of_date"])
            for r in route_rows if r.get("equ_ticker")
        }
        market_ctx = _get_market_context(self._mgr, tickers_and_dates, route_rows, time_series_map)

        order_ids = list({r["order_id"] for r in route_rows})
        fill_stats = _get_order_fill_stats(self._mgr, order_ids)

        fallback_metrics, fallback_series = _get_route_metric_fallbacks(
            self._mgr, route_rows, tca_metrics,
        )
        for key, computed in fallback_metrics.items():
            existing = tca_metrics.setdefault(key, {})
            for field_name, field_value in computed.items():
                if existing.get(field_name) is None and field_value is not None:
                    existing[field_name] = field_value
        for key, series in fallback_series.items():
            if not time_series_map.get(key):
                time_series_map[key] = series

        orders = self._assemble_report(
            route_rows, tca_metrics, market_ctx, fill_stats, time_series_map,
        )

        return TcaReport(
            filters=_filters_to_dict(filters),
            total_orders=total_orders, offset=filters.offset, limit=filters.limit,
            orders=orders,
        )

    def build_scorecard(self, filters: ScorecardFilters) -> ScorecardReport:
        """Build broker/strategy cohort scorecard over completed TCA orders."""
        cohort = (filters.cohort or "broker_strategy").strip().lower()
        if cohort not in SCORECARD_COHORTS:
            raise ValueError(
                f"Unsupported scorecard cohort {cohort!r}; "
                f"expected one of {SCORECARD_COHORTS}"
            )
        min_sample = max(1, int(filters.min_sample_size or 1))
        max_orders = max(1, int(filters.max_orders or 2000))

        page_size = min(500, max_orders)
        collected: list[TcaOrderSummary] = []
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
            if len(collected) >= max_orders:
                collected = collected[:max_orders]
                if page.total_orders > max_orders:
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
        self, route_rows: list[dict], tca_metrics: dict,
        market_ctx: dict, fill_stats: dict, time_series_map: dict,
    ) -> list[TcaOrderSummary]:
        """Group routes by order and build TcaOrderSummary objects."""
        from collections import defaultdict

        order_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in route_rows:
            order_groups[(r["order_id"], r["order_as_of_date"])].append(r)

        summaries: list[TcaOrderSummary] = []
        for (order_id, order_date), routes in order_groups.items():
            route_details: list[TcaRouteDetail] = []
            for r in routes:
                key = (r["order_id"], r["route_id"], r["order_as_of_date"])
                metrics = tca_metrics.get(key, {})
                ts = time_series_map.get(key, [])
                route_details.append(TcaRouteDetail(
                    order_id=r["order_id"], route_id=r["route_id"],
                    order_as_of_date=r["order_as_of_date"],
                    broker=r.get("broker"), side=r.get("side"),
                    start_time=r.get("start_time"), end_time=r.get("end_time"),
                    fill_pct=fill_stats.get(r["order_id"], {}).get("fill_pct"),
                    exec_price=metrics.get("cum_fill_vwap"),
                    interval_vwap=metrics.get("cum_vwap"),
                    tracking_error_bps=metrics.get("cum_tracking_error"),
                    volume_pct_interval=metrics.get("cum_volume_pct"),
                    time_series=[{
                        "ts": row.get("mkt_timestamp"), "close": row.get("close"),
                        "fill_px": row.get("fill_px"), "fill_volume": row.get("fill_volume"),
                        "volume": row.get("volume"),
                        "cum_volume_pct": row.get("cum_volume_pct"),
                        "cum_fill_vwap": row.get("cum_fill_vwap"),
                        "cum_vwap": row.get("cum_vwap"),
                        "cum_tracking_error": row.get("cum_tracking_error"),
                    } for row in ts],
                ))

            equ_ticker = routes[0].get("equ_ticker") if routes else None
            mkt_key = (equ_ticker, order_date) if equ_ticker else None
            mkt = market_ctx.get(mkt_key, {}) if mkt_key else {}

            all_metrics = [
                tca_metrics.get((r["order_id"], r["route_id"], r["order_as_of_date"]), {})
                for r in routes
            ]
            filled_metrics = [m for m in all_metrics if m.get("cum_fill_vwap") is not None]

            exec_price = _mean_numeric(m.get("cum_fill_vwap") for m in filled_metrics)
            interval_vwap = _mean_numeric(m.get("cum_vwap") for m in filled_metrics)
            tracking_error = _mean_numeric(m.get("cum_tracking_error") for m in filled_metrics)
            volume_pct_interval = _mean_numeric(m.get("cum_volume_pct") for m in filled_metrics)

            adv_5d = mkt.get("adv_5d")
            adv_20d = mkt.get("adv_20d")
            filled_volume = fill_stats.get(order_id, {}).get("filled_volume")
            volume_pct_adv5 = (
                (filled_volume / adv_5d * 100.0)
                if (adv_5d and adv_5d > 0 and filled_volume is not None) else None
            )
            volume_pct_adv20 = (
                (filled_volume / adv_20d * 100.0)
                if (adv_20d and adv_20d > 0 and filled_volume is not None) else None
            )

            summaries.append(TcaOrderSummary(
                order_id=order_id, order_as_of_date=order_date,
                equ_ticker=equ_ticker,
                side=routes[0].get("side") if routes else None,
                algo=routes[0].get("algo") if routes else None,
                start_time=min(
                    (r["start_time"] for r in routes if r.get("start_time")), default=None
                ),
                end_time=max(
                    (r["end_time"] for r in routes if r.get("end_time")), default=None
                ),
                fill_pct=fill_stats.get(order_id, {}).get("fill_pct"),
                exec_price=exec_price, interval_vwap=interval_vwap,
                tracking_error_bps=tracking_error,
                volume_pct_interval=volume_pct_interval,
                volume_pct_adv5=volume_pct_adv5,
                volume_pct_adv20=volume_pct_adv20,
                daily_volatility=mkt.get("daily_volatility"),
                intraday_volatility=mkt.get("intraday_volatility"),
                price_movement_pct=mkt.get("price_movement_pct"),
                data_quality_warning=bool(mkt.get("data_quality_warning", False)),
                routes=route_details,
            ))

        return summaries

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

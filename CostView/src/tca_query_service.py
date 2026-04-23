"""
TCA Query Service — dynamic multi-filter query builder for Transaction Cost Analysis.

Provides parameterized SQL queries across the CostView SQLite databases
(processed_fills.db, fill_bdib.db, raw_bdib.db) and assembles a structured
TcaReport without any external API calls.

All SQL parameters are bound via ? placeholders (never f-string interpolation
of user input) to prevent SQL injection.

Design:
    TcaFilters  — validated filter specification (dataclass)
    TcaReport   — structured output (order summary list + per-route details)
    TcaQueryService — orchestrates cross-DB queries and metric assembly
"""

from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from .exchange_tz import convert_ny_to_local
from .processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)

# Trading bars per year (10s bars): 252 days * 6.5h * 360 bars/h
BARS_PER_YEAR = 252 * 6.5 * 3600 / 10


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class TcaFilters:
    """Filter specification for a TCA query.

    All fields are optional. An empty TcaFilters instance defaults to the
    most recent available trading day.
    """
    order_ids: Optional[list[str]] = None
    algo: Optional[str] = None
    start_date: Optional[str] = None   # YYYYMMDD
    end_date: Optional[str] = None     # YYYYMMDD
    broker: Optional[str] = None
    symbol: Optional[str] = None       # equ_ticker  e.g. "AAPL US Equity"
    aggregation: str = "per_order"     # "per_order" | "aggregated"
    limit: int = 50
    offset: int = 0


@dataclass
class TcaRouteDetail:
    """TCA metrics for a single broker route."""
    order_id: str
    route_id: str
    order_as_of_date: str
    broker: Optional[str]
    side: Optional[str]
    start_time: Optional[str]          # Local exchange HH:MM:SS
    end_time: Optional[str]            # Local exchange HH:MM:SS
    fill_pct: Optional[float]          # 0-100
    exec_price: Optional[float]        # cum_fill_vwap (execution VWAP)
    interval_vwap: Optional[float]     # cum_vwap (market VWAP = benchmark)
    tracking_error_bps: Optional[float]
    volume_pct_interval: Optional[float]  # % of interval traded volume
    # Time-series for charts (list of {ts, close, fill_px, volume, cum_volume_pct})
    time_series: list[dict] = field(default_factory=list)


@dataclass
class TcaOrderSummary:
    """TCA summary for a single order (may contain multiple routes)."""
    order_id: str
    order_as_of_date: str
    equ_ticker: Optional[str]
    side: Optional[str]
    algo: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    fill_pct: Optional[float]
    exec_price: Optional[float]
    interval_vwap: Optional[float]
    tracking_error_bps: Optional[float]
    volume_pct_interval: Optional[float]
    volume_pct_adv5: Optional[float]
    volume_pct_adv20: Optional[float]
    daily_volatility: Optional[float]
    intraday_volatility: Optional[float]
    price_movement_pct: Optional[float]
    data_quality_warning: bool = False
    routes: list[TcaRouteDetail] = field(default_factory=list)


@dataclass
class TcaReport:
    """Full TCA report for a set of filtered orders."""
    filters: dict
    total_orders: int
    offset: int
    limit: int
    orders: list[TcaOrderSummary]
    generated_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )
    data_source_warning: Optional[str] = None


# ── Service ──────────────────────────────────────────────────────────────────

class TcaQueryService:
    """Builds dynamic parameterized TCA queries and assembles TcaReports.

    All database access goes through private helpers that use ? placeholders.
    User-supplied filter values are never interpolated into SQL strings.
    """

    def __init__(
        self,
        proc_fills_db_path: Optional[str] = None,
        fill_bdib_db_path: Optional[str] = None,
        raw_bdib_db_path: Optional[str] = None,
        raw_fills_db_path: Optional[str] = None,
    ):
        self._proc_fills_path = str(proc_fills_db_path or Config.PROCESSED_FILLS_DB)
        self._fill_bdib_path = str(fill_bdib_db_path or Config.FILL_BDIB_DB)
        self._raw_bdib_path = str(raw_bdib_db_path or Config.RAW_BDIB_DB)
        self._raw_fills_path = str(raw_fills_db_path or Config.RAW_FILLS_DB)

    # ── Public API ──────────────────────────────────────────────────────────

    def build_tca_report(self, filters: TcaFilters) -> TcaReport:
        """Assemble a complete TcaReport for the given filters.

        Steps:
        1. Resolve date range defaults.
        2. Query processed_fills.db for matching (OrderId, RouteId, date) tuples.
        3. Fetch final-row TCA metrics from fill_bdib.db.
        4. Fetch market context (ADV, volatility, price movement) from raw_bdib.db.
        5. Fetch fill percentages from raw_fills.db.
        6. Assemble order summaries and route details.
        """
        # 1. Resolve date defaults
        filters = self._resolve_date_defaults(filters)

        # 2. Get matching routes from processed_fills.db
        route_rows, total_orders = self._get_matching_routes(filters)

        if not route_rows:
            return TcaReport(
                filters=self._filters_to_dict(filters),
                total_orders=0,
                offset=filters.offset,
                limit=filters.limit,
                orders=[],
                data_source_warning=None,
            )

        # 3. Fetch TCA metrics (final row per route) from fill_bdib.db
        route_keys = [(r["order_id"], r["route_id"], r["order_as_of_date"]) for r in route_rows]
        tca_metrics = self._get_tca_metrics(route_keys)

        # 4. Check for fill_bdib data availability
        if not tca_metrics:
            return TcaReport(
                filters=self._filters_to_dict(filters),
                total_orders=total_orders,
                offset=filters.offset,
                limit=filters.limit,
                orders=[],
                data_source_warning=(
                    "fill_bdib.db is empty — pipeline stages 5 & 6 have not yet run. "
                    "Trigger an update via POST /api/tca/trigger-update."
                ),
            )

        # 5. Fetch time-series for charts
        time_series_map = self._get_time_series(route_keys)

        # 6. Fetch market context (ADV, volatility, price movement) from raw_bdib.db
        tickers_and_dates = {
            (r["equ_ticker"], r["order_as_of_date"])
            for r in route_rows
            if r.get("equ_ticker")
        }
        market_ctx = self._get_market_context(tickers_and_dates, route_rows, time_series_map)

        # 7. Fetch fill percentages from raw_fills.db
        order_ids = list({r["order_id"] for r in route_rows})
        fill_stats = self._get_order_fill_stats(order_ids)

        # 8. Backfill missing route market metrics directly from raw_bdib when
        # fill_bdib was generated before local-time conversion was corrected.
        fallback_metrics, fallback_series = self._get_route_metric_fallbacks(route_rows, tca_metrics)
        for key, computed in fallback_metrics.items():
            existing = tca_metrics.setdefault(key, {})
            for field_name, field_value in computed.items():
                if existing.get(field_name) is None and field_value is not None:
                    existing[field_name] = field_value
        for key, series in fallback_series.items():
            if not time_series_map.get(key):
                time_series_map[key] = series

        # 9. Assemble order summaries grouped by order_id
        orders = self._assemble_report(
            route_rows, tca_metrics, market_ctx, fill_stats, time_series_map
        )

        return TcaReport(
            filters=self._filters_to_dict(filters),
            total_orders=total_orders,
            offset=filters.offset,
            limit=filters.limit,
            orders=orders,
        )

    # ── Query helpers ───────────────────────────────────────────────────────

    def _get_matching_routes(
        self, filters: TcaFilters
    ) -> tuple[list[dict], int]:
        """Query processed_fills.db for routes matching all active filters.

        Returns (page of route dicts, total_count_without_pagination).
        All filter parameters are passed as SQL ? bind values.
        """
        conditions: list[str] = []
        params: list[Any] = []

        # Date range — applied to processed_fills.order_as_of_date
        if filters.start_date:
            conditions.append("pf.order_as_of_date >= ?")
            params.append(filters.start_date)
        if filters.end_date:
            conditions.append("pf.order_as_of_date <= ?")
            params.append(filters.end_date)

        # Order ID filter — IN clause with individual ? per id
        if filters.order_ids:
            placeholders = ",".join(["?"] * len(filters.order_ids))
            conditions.append(f"pf.OrderId IN ({placeholders})")
            params.extend(filters.order_ids)

        # Algo filter — exact match (LIKE for partial is not offered to avoid injection risk)
        if filters.algo:
            conditions.append("pf.algo = ?")
            params.append(filters.algo)

        # Broker filter — exact match
        if filters.broker:
            conditions.append("pf.Broker = ?")
            params.append(filters.broker)

        # Symbol / equ_ticker filter (from route_registry)
        if filters.symbol:
            conditions.append("rr.equ_ticker = ?")
            params.append(filters.symbol)

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        base_sql = f"""
            SELECT
                pf.OrderId      AS order_id,
                pf.RouteId      AS route_id,
                pf.order_as_of_date,
                rr.equ_ticker,
                rr.ccy_ticker,
                rr.Side         AS side,
                pf.algo,
                pf.Broker       AS broker,
                pf.TraderName   AS trader_name,
                COALESCE(MAX(rr.Exchange), MAX(pf.Exchange)) AS exchange,
                MIN(pf.DateTimeOfFill) AS first_fill_datetime,
                MAX(pf.DateTimeOfFill) AS last_fill_datetime,
                MIN(pf.exchange_exec_time) AS start_time,
                MAX(pf.exchange_exec_time) AS end_time
            FROM {Config.PROCESSED_FILLS_TABLE} pf
            LEFT JOIN route_registry rr
                ON pf.OrderId = rr.OrderId AND pf.RouteId = rr.RouteId
            {where_clause}
            GROUP BY pf.OrderId, pf.RouteId, pf.order_as_of_date
        """

        conn = self._proc_fills_conn()
        try:
            # Total count (without pagination)
            count_sql = f"SELECT COUNT(*) FROM ({base_sql})"
            cursor = conn.execute(count_sql, params)
            total = int(cursor.fetchone()[0])

            # Paginated rows
            paged_sql = base_sql + " ORDER BY pf.order_as_of_date DESC, pf.OrderId LIMIT ? OFFSET ?"
            cursor = conn.execute(paged_sql, params + [filters.limit, filters.offset])
            columns = [desc[0] for desc in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

        for row in rows:
            local_start = self._derive_local_exchange_time(row.get("first_fill_datetime"), row.get("exchange"))
            local_end = self._derive_local_exchange_time(row.get("last_fill_datetime"), row.get("exchange"))
            if local_start is not None:
                row["start_time"] = local_start
            if local_end is not None:
                row["end_time"] = local_end

        return rows, total

    def _get_tca_metrics(
        self, route_keys: list[tuple[str, str, str]]
    ) -> dict[tuple[str, str, str], dict]:
        """Fetch the LAST row per (OrderId, RouteId, date) from fill_bdib.db.

        The last row contains the final cumulative TCA metrics (cum_vwap, etc.).
        Returns a dict keyed by (order_id, route_id, order_as_of_date).
        """
        if not route_keys:
            return {}

        # Batch fetch all relevant data, then filter to last row per route in Python
        order_ids = list({k[0] for k in route_keys})
        placeholders = ",".join(["?"] * len(order_ids))

        conn = self._fill_bdib_conn()
        try:
            # Check if table has data at all
            count_cursor = conn.execute(f"SELECT COUNT(*) FROM {Config.FILL_BDIB_TABLE}")
            if count_cursor.fetchone()[0] == 0:
                return {}

            sql = f"""
                SELECT *
                FROM {Config.FILL_BDIB_TABLE}
                WHERE OrderId IN ({placeholders})
                ORDER BY OrderId, RouteId, order_as_of_date, mkt_timestamp
            """
            cursor = conn.execute(sql, order_ids)
            columns = [desc[0] for desc in cursor.description]
            all_rows = cursor.fetchall()
        finally:
            conn.close()

        if not all_rows:
            return {}

        # Group and take last row per (OrderId, RouteId, order_as_of_date)
        result: dict[tuple[str, str, str], dict] = {}
        for row in all_rows:
            d = dict(zip(columns, row))
            key = (d["OrderId"], d["RouteId"], d["order_as_of_date"])
            if key in {k for k in route_keys}:
                result[key] = d  # each subsequent row overwrites → last row wins

        return result

    def _get_time_series(
        self, route_keys: list[tuple[str, str, str]]
    ) -> dict[tuple[str, str, str], list[dict]]:
        """Fetch full time-series rows from fill_bdib.db for chart rendering.

        Returns dict keyed by (order_id, route_id, order_as_of_date) →
        list of row dicts ordered by mkt_timestamp.
        """
        if not route_keys:
            return {}

        order_ids = list({k[0] for k in route_keys})
        placeholders = ",".join(["?"] * len(order_ids))

        conn = self._fill_bdib_conn()
        try:
            sql = f"""
                SELECT
                    OrderId, RouteId, order_as_of_date, mkt_timestamp,
                    equ_ticker, close, fill_px, fill_volume,
                    volume, cum_volume_pct, cum_fill_vwap, cum_vwap,
                    cum_slippage_bps, cum_tracking_error
                FROM {Config.FILL_BDIB_TABLE}
                WHERE OrderId IN ({placeholders})
                ORDER BY OrderId, RouteId, order_as_of_date, mkt_timestamp
            """
            cursor = conn.execute(sql, order_ids)
            columns = [desc[0] for desc in cursor.description]
            all_rows = cursor.fetchall()
        finally:
            conn.close()

        result: dict[tuple[str, str, str], list[dict]] = {}
        for row in all_rows:
            d = dict(zip(columns, row))
            key = (d["OrderId"], d["RouteId"], d["order_as_of_date"])
            if key in {k for k in route_keys}:
                result.setdefault(key, []).append(d)
        return result

    def _get_market_context(
        self,
        tickers_and_dates: set[tuple[str, str]],
        route_rows: list[dict],
        time_series_map: dict,
    ) -> dict[tuple[str, str], dict]:
        """Fetch ADV, volatility, and before-interval close from raw_bdib.db.

        Returns dict keyed by (equ_ticker, order_as_of_date).
        """
        if not tickers_and_dates:
            return {}

        conn = self._raw_bdib_conn()
        ctx: dict[tuple[str, str], dict] = {}
        try:
            for ticker, trade_date in tickers_and_dates:
                row: dict = {}

                # ADV + volatility from bdib_daily_summary
                cursor = conn.execute(
                    f"SELECT adv_5d, adv_20d, daily_volatility, intraday_volatility, total_volume, daily_close "
                    f"FROM {Config.BDIB_DAILY_SUMMARY_TABLE} "
                    "WHERE equ_ticker = ? AND trade_date = ?",
                    [ticker, trade_date],
                )
                summary_row = cursor.fetchone()
                if summary_row:
                    row["adv_5d"] = summary_row[0]
                    row["adv_20d"] = summary_row[1]
                    row["daily_volatility"] = summary_row[2]
                    row["intraday_volatility"] = summary_row[3]
                    row["total_volume"] = summary_row[4]
                    row["daily_close"] = summary_row[5]
                else:
                    row["adv_5d"] = None
                    row["adv_20d"] = None
                    row["daily_volatility"] = None
                    row["intraday_volatility"] = None
                    row["total_volume"] = None
                    row["daily_close"] = None

                # Determine minimum start_time across all routes for this ticker+date
                start_times = [
                    r["start_time"]
                    for r in route_rows
                    if r.get("equ_ticker") == ticker
                    and r["order_as_of_date"] == trade_date
                    and r.get("start_time")
                ]
                interval_start = min(start_times) if start_times else None

                # Before-interval close: last BDIB bar with mkt_timestamp < order start
                if interval_start:
                    cursor = conn.execute(
                        f"SELECT close FROM {Config.RAW_BDIB_TABLE} "
                        "WHERE equ_ticker = ? AND order_as_of_date = ? "
                        "AND substr(mkt_timestamp, -8) < ? "
                        "ORDER BY substr(mkt_timestamp, -8) DESC LIMIT 1",
                        [ticker, trade_date, interval_start],
                    )
                    before_row = cursor.fetchone()
                    row["before_interval_close"] = before_row[0] if before_row else None
                else:
                    row["before_interval_close"] = None

                # Interval close: last BDIB bar within the order interval
                end_times = [
                    r["end_time"]
                    for r in route_rows
                    if r.get("equ_ticker") == ticker
                    and r["order_as_of_date"] == trade_date
                    and r.get("end_time")
                ]
                interval_end = max(end_times) if end_times else None
                if interval_end:
                    cursor = conn.execute(
                        f"SELECT close FROM {Config.RAW_BDIB_TABLE} "
                        "WHERE equ_ticker = ? AND order_as_of_date = ? "
                        "AND substr(mkt_timestamp, -8) <= ? "
                        "ORDER BY substr(mkt_timestamp, -8) DESC LIMIT 1",
                        [ticker, trade_date, interval_end],
                    )
                    close_row = cursor.fetchone()
                    row["interval_close"] = close_row[0] if close_row else None
                else:
                    row["interval_close"] = None

                # Price movement % = (interval_close / before_interval_close) - 1
                if row.get("interval_close") and row.get("before_interval_close"):
                    row["price_movement_pct"] = (
                        row["interval_close"] / row["before_interval_close"] - 1.0
                    ) * 100.0
                else:
                    row["price_movement_pct"] = None

                # BDIB bar completeness check (data quality warning)
                if interval_start and interval_end:
                    cursor = conn.execute(
                        f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE} "
                        "WHERE equ_ticker = ? AND order_as_of_date = ? "
                        "AND substr(mkt_timestamp, -8) >= ? AND substr(mkt_timestamp, -8) <= ?",
                        [
                            ticker,
                            trade_date,
                            interval_start,
                            interval_end,
                        ],
                    )
                    actual_bars = cursor.fetchone()[0]
                    # Expected: 1 bar per 10s in the interval
                    try:
                        t_start = datetime.strptime(interval_start, "%H:%M:%S")
                        t_end = datetime.strptime(interval_end, "%H:%M:%S")
                        expected_bars = max(1, int((t_end - t_start).total_seconds() / 10))
                    except ValueError:
                        expected_bars = 1
                    row["data_quality_warning"] = actual_bars < 0.8 * expected_bars
                else:
                    row["data_quality_warning"] = False

                ctx[(ticker, trade_date)] = row
        finally:
            conn.close()

        return ctx

    def _get_order_fill_stats(
        self, order_ids: list[str]
    ) -> dict[str, dict[str, Optional[float]]]:
        """Return fill-level order stats derived from raw_fills.db."""
        if not order_ids:
            return {}

        placeholders = ",".join(["?"] * len(order_ids))
        conn = self._raw_fills_conn()
        try:
            cursor = conn.execute(
                f"SELECT OrderId, SUM(CAST(FillShares AS REAL)), MAX(CAST(Amount AS REAL)) "
                f"FROM {Config.RAW_FILLS_TABLE} "
                f"WHERE OrderId IN ({placeholders}) "
                "GROUP BY OrderId",
                order_ids,
            )
            result: dict[str, dict[str, Optional[float]]] = {}
            for row in cursor.fetchall():
                oid, total_filled, amount = row
                filled_volume = float(total_filled) if total_filled is not None else None
                amount_value = float(amount) if amount is not None else None
                fill_pct = None
                if amount_value and amount_value > 0 and filled_volume is not None:
                    fill_pct = round(filled_volume / amount_value * 100.0, 2)
                result[str(oid)] = {
                    "fill_pct": fill_pct,
                    "filled_volume": filled_volume,
                }
        finally:
            conn.close()
        return result

    def _get_fill_percentages(
        self, order_ids: list[str]
    ) -> dict[str, Optional[float]]:
        """Compute fill % = sum(FillShares) / Amount per order from raw_fills.db."""
        return {
            order_id: stats.get("fill_pct")
            for order_id, stats in self._get_order_fill_stats(order_ids).items()
        }

    @staticmethod
    def _mean_numeric(values: list[Optional[float]] | tuple[Optional[float], ...] | Any) -> Optional[float]:
        """Return the arithmetic mean of numeric values, ignoring None/NaN."""
        cleaned: list[float] = []
        for value in values:
            if value is None or pd.isna(value):
                continue
            cleaned.append(float(value))
        if not cleaned:
            return None
        return sum(cleaned) / len(cleaned)

    # ── Assembly ────────────────────────────────────────────────────────────

    def _assemble_report(
        self,
        route_rows: list[dict],
        tca_metrics: dict,
        market_ctx: dict,
        fill_stats: dict,
        time_series_map: dict,
    ) -> list[TcaOrderSummary]:
        """Group routes by order and build TcaOrderSummary objects."""
        # Group routes by (order_id, order_as_of_date)
        from collections import defaultdict
        order_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in route_rows:
            order_groups[(r["order_id"], r["order_as_of_date"])].append(r)

        summaries: list[TcaOrderSummary] = []
        for (order_id, order_date), routes in order_groups.items():
            # Build route details
            route_details: list[TcaRouteDetail] = []
            for r in routes:
                key = (r["order_id"], r["route_id"], r["order_as_of_date"])
                metrics = tca_metrics.get(key, {})
                ts = time_series_map.get(key, [])
                route_details.append(TcaRouteDetail(
                    order_id=r["order_id"],
                    route_id=r["route_id"],
                    order_as_of_date=r["order_as_of_date"],
                    broker=r.get("broker"),
                    side=r.get("side"),
                    start_time=r.get("start_time"),
                    end_time=r.get("end_time"),
                    fill_pct=fill_stats.get(r["order_id"], {}).get("fill_pct"),
                    exec_price=metrics.get("cum_fill_vwap"),
                    interval_vwap=metrics.get("cum_vwap"),
                    tracking_error_bps=metrics.get("cum_tracking_error"),
                    volume_pct_interval=metrics.get("cum_volume_pct"),
                    time_series=[{
                        "ts": row.get("mkt_timestamp"),
                        "close": row.get("close"),
                        "fill_px": row.get("fill_px"),
                        "fill_volume": row.get("fill_volume"),
                        "volume": row.get("volume"),
                        "cum_volume_pct": row.get("cum_volume_pct"),
                        "cum_fill_vwap": row.get("cum_fill_vwap"),
                        "cum_vwap": row.get("cum_vwap"),
                        "cum_tracking_error": row.get("cum_tracking_error"),
                    } for row in ts],
                ))

            # Aggregate order-level metrics across routes
            equ_ticker = routes[0].get("equ_ticker") if routes else None
            mkt_key = (equ_ticker, order_date) if equ_ticker else None
            mkt = market_ctx.get(mkt_key, {}) if mkt_key else {}

            # Aggregate fill_bdib metrics: weighted average across routes
            all_metrics = [
                tca_metrics.get((r["order_id"], r["route_id"], r["order_as_of_date"]), {})
                for r in routes
            ]
            filled_metrics = [m for m in all_metrics if m.get("cum_fill_vwap") is not None]

            exec_price = self._mean_numeric(m.get("cum_fill_vwap") for m in filled_metrics)
            interval_vwap = self._mean_numeric(m.get("cum_vwap") for m in filled_metrics)
            tracking_error = self._mean_numeric(m.get("cum_tracking_error") for m in filled_metrics)
            volume_pct_interval = self._mean_numeric(m.get("cum_volume_pct") for m in filled_metrics)

            # ADV-based volume percentages
            adv_5d = mkt.get("adv_5d")
            adv_20d = mkt.get("adv_20d")
            filled_volume = fill_stats.get(order_id, {}).get("filled_volume")
            volume_pct_adv5 = (
                (filled_volume / adv_5d * 100.0)
                if (adv_5d and adv_5d > 0 and filled_volume is not None)
                else None
            )
            volume_pct_adv20 = (
                (filled_volume / adv_20d * 100.0)
                if (adv_20d and adv_20d > 0 and filled_volume is not None)
                else None
            )

            summaries.append(TcaOrderSummary(
                order_id=order_id,
                order_as_of_date=order_date,
                equ_ticker=equ_ticker,
                side=routes[0].get("side") if routes else None,
                algo=routes[0].get("algo") if routes else None,
                start_time=min((r["start_time"] for r in routes if r.get("start_time")), default=None),
                end_time=max((r["end_time"] for r in routes if r.get("end_time")), default=None),
                fill_pct=fill_stats.get(order_id, {}).get("fill_pct"),
                exec_price=exec_price,
                interval_vwap=interval_vwap,
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

    @staticmethod
    def _derive_local_exchange_datetime(datetime_value: Any, exchange_code: Any) -> Optional[datetime]:
        if datetime_value is None or exchange_code is None:
            return None
        if pd.isna(datetime_value) or pd.isna(exchange_code):
            return None
        parsed = pd.to_datetime(datetime_value, errors="coerce")
        if pd.isna(parsed):
            return None
        local_dt = convert_ny_to_local(parsed.to_pydatetime(), str(exchange_code))
        if local_dt is None:
            return None
        return local_dt.replace(tzinfo=None)

    @classmethod
    def _derive_local_exchange_time(cls, datetime_value: Any, exchange_code: Any) -> Optional[str]:
        local_dt = cls._derive_local_exchange_datetime(datetime_value, exchange_code)
        if local_dt is None:
            return None
        return local_dt.strftime(Config.TIME_FORMAT)

    @staticmethod
    def _floor_time_to_10s(value: datetime) -> str:
        floored_seconds = (value.second // 10) * 10
        floored = value.replace(second=floored_seconds, microsecond=0)
        return floored.strftime(Config.TIME_FORMAT)

    @staticmethod
    def _time_key(value: Any) -> Optional[str]:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        if len(text) >= 8:
            return text[-8:]
        return None

    @staticmethod
    def _side_sign(side: Any) -> int:
        if side is None or pd.isna(side):
            return 0
        side_upper = str(side).strip().upper()
        if side_upper in {"B", "BUY"}:
            return -1
        if side_upper in {"S", "SELL"}:
            return 1
        return 0

    @staticmethod
    def _to_optional_float(value: Any) -> Optional[float]:
        if value is None or pd.isna(value):
            return None
        return float(value)

    def _get_route_metric_fallbacks(
        self,
        route_rows: list[dict],
        tca_metrics: dict[tuple[str, str, str], dict],
    ) -> tuple[
        dict[tuple[str, str, str], dict[str, Optional[float]]],
        dict[tuple[str, str, str], list[dict]],
    ]:
        fallback_candidates = []
        for route in route_rows:
            key = (route["order_id"], route["route_id"], route["order_as_of_date"])
            metrics = tca_metrics.get(key, {})
            if any(metrics.get(field) is None for field in ("cum_vwap", "cum_tracking_error", "cum_volume_pct")):
                fallback_candidates.append(route)

        if not fallback_candidates:
            return {}, {}

        metric_fallbacks: dict[tuple[str, str, str], dict[str, Optional[float]]] = {}
        series_fallbacks: dict[tuple[str, str, str], list[dict]] = {}

        proc_conn = self._proc_fills_conn()
        raw_conn = self._raw_bdib_conn()
        try:
            for route in fallback_candidates:
                key = (route["order_id"], route["route_id"], route["order_as_of_date"])
                fills = proc_conn.execute(
                    f"""
                    SELECT DateTimeOfFill, Exchange, FillPrice, FillShares
                    FROM {Config.PROCESSED_FILLS_TABLE}
                    WHERE OrderId = ? AND RouteId = ? AND order_as_of_date = ?
                    ORDER BY DateTimeOfFill
                    """,
                    list(key),
                ).fetchall()
                computed = self._compute_route_metrics_from_raw_bdib(raw_conn, route, fills)
                if computed is None:
                    continue
                metric_fallbacks[key] = computed["metrics"]
                series_fallbacks[key] = computed["time_series"]
        finally:
            proc_conn.close()
            raw_conn.close()

        return metric_fallbacks, series_fallbacks

    def _compute_route_metrics_from_raw_bdib(
        self,
        raw_conn: sqlite3.Connection,
        route: dict,
        fill_rows: list[sqlite3.Row],
    ) -> Optional[dict[str, Any]]:
        ticker = route.get("equ_ticker")
        trade_date = route.get("order_as_of_date")
        if not ticker or not trade_date or not fill_rows:
            return None

        fills_by_bucket: dict[str, dict[str, float]] = {}
        bucket_times: list[str] = []
        for fill in fill_rows:
            exchange = fill["Exchange"] if fill["Exchange"] else route.get("exchange")
            local_dt = self._derive_local_exchange_datetime(fill["DateTimeOfFill"], exchange)
            if local_dt is None:
                continue
            bucket = self._floor_time_to_10s(local_dt)
            fill_volume = self._to_optional_float(fill["FillShares"])
            fill_price = self._to_optional_float(fill["FillPrice"])
            if fill_volume is None or fill_price is None:
                continue
            bucket_times.append(bucket)
            bucket_row = fills_by_bucket.setdefault(bucket, {"fill_volume": 0.0, "fill_value": 0.0})
            bucket_row["fill_volume"] += fill_volume
            bucket_row["fill_value"] += fill_volume * fill_price

        if not bucket_times:
            return None

        start_bucket = min(bucket_times)
        end_bucket = max(bucket_times)
        bars = raw_conn.execute(
            f"""
            SELECT mkt_timestamp, close, volume, value
            FROM {Config.RAW_BDIB_TABLE}
            WHERE equ_ticker = ? AND order_as_of_date = ?
              AND substr(mkt_timestamp, -8) >= ?
              AND substr(mkt_timestamp, -8) <= ?
            ORDER BY substr(mkt_timestamp, -8)
            """,
            [ticker, trade_date, start_bucket, end_bucket],
        ).fetchall()
        if not bars:
            return None

        side_sign = self._side_sign(route.get("side"))
        cum_fill_volume = 0.0
        cum_fill_value = 0.0
        cum_volume = 0.0
        cum_value = 0.0
        slippage_points: list[Optional[float]] = []
        points: list[dict[str, Any]] = []

        for bar in bars:
            time_key = self._time_key(bar["mkt_timestamp"])
            if time_key is None:
                continue

            market_close = self._to_optional_float(bar["close"])
            market_volume = self._to_optional_float(bar["volume"]) or 0.0
            market_value = self._to_optional_float(bar["value"])
            if market_value is None and market_close is not None and market_volume > 0:
                market_value = market_close * market_volume
            market_value = market_value or 0.0

            cum_volume += market_volume
            cum_value += market_value

            fill_bucket = fills_by_bucket.get(time_key)
            fill_volume = None
            fill_px = None
            if fill_bucket is not None:
                fill_volume = fill_bucket["fill_volume"]
                fill_value = fill_bucket["fill_value"]
                cum_fill_volume += fill_volume
                cum_fill_value += fill_value
                fill_px = fill_value / fill_volume if fill_volume > 0 else None

            cum_vwap = (cum_value / cum_volume) if cum_volume > 0 else None
            cum_fill_vwap = (cum_fill_value / cum_fill_volume) if cum_fill_volume > 0 else None
            cum_volume_pct = (cum_fill_volume / cum_volume * 100.0) if cum_volume > 0 else None

            cum_slippage_bps = None
            if side_sign != 0 and cum_vwap not in (None, 0) and cum_fill_vwap is not None:
                cum_slippage_bps = side_sign * (cum_fill_vwap / cum_vwap - 1.0) * 10000.0
            slippage_points.append(cum_slippage_bps)
            points.append(
                {
                    "ts": time_key,
                    "close": market_close,
                    "fill_px": fill_px,
                    "fill_volume": fill_volume,
                    "volume": market_volume,
                    "cum_volume_pct": cum_volume_pct,
                    "cum_fill_vwap": cum_fill_vwap,
                    "cum_vwap": cum_vwap,
                    "cum_tracking_error": None,
                }
            )

        if not points:
            return None

        tracking_series = pd.Series(slippage_points, dtype=float).expanding().std()
        for index, tracking_value in enumerate(tracking_series.tolist()):
            points[index]["cum_tracking_error"] = None if pd.isna(tracking_value) else float(tracking_value)

        final_point = points[-1]
        return {
            "metrics": {
                "cum_fill_vwap": final_point.get("cum_fill_vwap"),
                "cum_vwap": final_point.get("cum_vwap"),
                "cum_tracking_error": final_point.get("cum_tracking_error"),
                "cum_volume_pct": final_point.get("cum_volume_pct"),
            },
            "time_series": points,
        }

    # ── Utilities ───────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_date_defaults(filters: TcaFilters) -> TcaFilters:
        """Apply sensible defaults when no date range is specified."""
        from datetime import date, timedelta
        if filters.start_date is None and filters.end_date is None and not filters.order_ids:
            # Default: last weekday
            ref = date.today()
            if ref.weekday() == 0:
                ref = ref - timedelta(days=3)  # Monday → Friday
            elif ref.weekday() == 6:
                ref = ref - timedelta(days=2)  # Sunday → Friday
            else:
                ref = ref - timedelta(days=1)
            filters.start_date = ref.strftime("%Y%m%d")
            filters.end_date = filters.start_date
        return filters

    @staticmethod
    def _filters_to_dict(filters: TcaFilters) -> dict:
        return {
            "order_ids": filters.order_ids,
            "algo": filters.algo,
            "start_date": filters.start_date,
            "end_date": filters.end_date,
            "broker": filters.broker,
            "symbol": filters.symbol,
            "aggregation": filters.aggregation,
            "limit": filters.limit,
            "offset": filters.offset,
        }

    def _proc_fills_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._proc_fills_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _fill_bdib_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._fill_bdib_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _raw_bdib_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._raw_bdib_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _raw_fills_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._raw_fills_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

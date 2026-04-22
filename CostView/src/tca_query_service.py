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
        fill_pcts = self._get_fill_percentages(order_ids)

        # 8. Assemble order summaries grouped by order_id
        orders = self._assemble_report(
            route_rows, tca_metrics, market_ctx, fill_pcts, time_series_map
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
                        "AND mkt_timestamp < ? "
                        "ORDER BY mkt_timestamp DESC LIMIT 1",
                        [ticker, trade_date, trade_date + " " + interval_start],
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
                        "AND mkt_timestamp <= ? "
                        "ORDER BY mkt_timestamp DESC LIMIT 1",
                        [ticker, trade_date, trade_date + " " + interval_end],
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
                        "AND mkt_timestamp >= ? AND mkt_timestamp <= ?",
                        [
                            ticker, trade_date,
                            trade_date + " " + interval_start,
                            trade_date + " " + interval_end,
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

    def _get_fill_percentages(
        self, order_ids: list[str]
    ) -> dict[str, Optional[float]]:
        """Compute fill % = sum(FillShares) / Amount per order from raw_fills.db."""
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
            result: dict[str, Optional[float]] = {}
            for row in cursor.fetchall():
                oid, total_filled, amount = row
                if amount and amount > 0:
                    result[str(oid)] = round(total_filled / amount * 100.0, 2)
                else:
                    result[str(oid)] = None
        finally:
            conn.close()
        return result

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
        fill_pcts: dict,
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
                    fill_pct=fill_pcts.get(r["order_id"]),
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
            total_vol = mkt.get("total_volume")
            volume_pct_adv5 = (
                (total_vol / adv_5d * 100.0) if (adv_5d and total_vol) else None
            )
            volume_pct_adv20 = (
                (total_vol / adv_20d * 100.0) if (adv_20d and total_vol) else None
            )

            summaries.append(TcaOrderSummary(
                order_id=order_id,
                order_as_of_date=order_date,
                equ_ticker=equ_ticker,
                side=routes[0].get("side") if routes else None,
                algo=routes[0].get("algo") if routes else None,
                start_time=min((r["start_time"] for r in routes if r.get("start_time")), default=None),
                end_time=max((r["end_time"] for r in routes if r.get("end_time")), default=None),
                fill_pct=fill_pcts.get(order_id),
                exec_price=exec_price,
                interval_vwap=interval_vwap,
                tracking_error_bps=tracking_error,
                volume_pct_interval=volume_pct_interval,
                volume_pct_adv5=volume_pct_adv5,
                volume_pct_adv20=volume_pct_adv20,
                intraday_volatility=mkt.get("intraday_volatility"),
                price_movement_pct=mkt.get("price_movement_pct"),
                data_quality_warning=bool(mkt.get("data_quality_warning", False)),
                routes=route_details,
            ))

        return summaries

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
        return conn

    def _raw_fills_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._raw_fills_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

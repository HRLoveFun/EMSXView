"""
TCA SQL query builders — extracted from ``tca_query_service.py``.

Each function accepts a ``ConnectionManager`` as first argument and returns
the same type as the original method.  They replace the corresponding
``self._get_*()`` methods on ``TcaQueryService``.

Extracted in Iteration 6.3 to reduce tca_query_service.py below 500 lines.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager
from platform_data.contracts import TcaFilters

from .tca_utils import (
    to_optional_float as _to_optional_float,
)

logger = logging.getLogger(__name__)

# BDIB查询引擎选择 (Plan §7.2)
_BDIB_ENGINE = Config.BDIB_QUERY_ENGINE


# ═══════════════════════════════════════════════════════════════════════════
# Connection helpers (internal to this module)
# ═══════════════════════════════════════════════════════════════════════════


def _fill_bdib_conn(mgr: ConnectionManager) -> sqlite3.Connection:
    return mgr.get_connection("fill_bdib", AccessTier.READ)


def _raw_bdib_conn(mgr: ConnectionManager) -> sqlite3.Connection:
    return mgr.get_connection("raw_bdib", AccessTier.READ, row_factory=sqlite3.Row)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cursor = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ? LIMIT 1",
        [table_name],
    )
    return cursor.fetchone() is not None


# ═══════════════════════════════════════════════════════════════════════════
# Time series (fill_bdib.db)
# ═══════════════════════════════════════════════════════════════════════════


def get_time_series(
    mgr: ConnectionManager,
    route_keys: list[tuple[str, str, str]],
) -> dict[tuple[str, str, str], list[dict]]:
    """Fetch full time-series rows from fill_bdib.db for chart rendering.

    Returns dict keyed by (order_id, route_id, order_as_of_date) → list of row dicts.
    """
    if not route_keys:
        return {}

    order_ids = list({k[0] for k in route_keys})
    placeholders = ",".join(["?"] * len(order_ids))

    conn = _fill_bdib_conn(mgr)
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


# ═══════════════════════════════════════════════════════════════════════════
# Market context (raw_bdib.db)
# ═══════════════════════════════════════════════════════════════════════════


def get_market_context(
    mgr: ConnectionManager,
    tickers_and_dates: set[tuple[str, str]],
    route_rows: list[dict],
    time_series_map: dict,
) -> dict[tuple[str, str], dict]:
    """Fetch ADV, volatility, and before-interval close from BDIB data.

    根据 BDIB_QUERY_ENGINE 选择:
        "sqlite"  — raw_bdib.db (默认)
        "duckdb"  — Parquet via DuckDB

    Returns dict keyed by (equ_ticker, order_as_of_date).
    """
    if _BDIB_ENGINE == "duckdb":
        return _get_market_context_duckdb(
            mgr, tickers_and_dates, route_rows, time_series_map,
        )
    return _get_market_context_sqlite(
        mgr, tickers_and_dates, route_rows, time_series_map,
    )


def _get_market_context_duckdb(
    mgr: ConnectionManager,
    tickers_and_dates: set[tuple[str, str]],
    route_rows: list[dict],
    time_series_map: dict,
) -> dict[tuple[str, str], dict]:
    """通过DuckDB/Parquet获取市场上下文。"""
    if not tickers_and_dates:
        return {}

    from DataPipeline.storage.market_store import MarketStoreReader
    reader = MarketStoreReader(Config.BDIB_PARQUET_DIR)

    conn = _raw_bdib_conn(mgr)
    ctx: dict[tuple[str, str], dict] = {}
    try:
        for ticker, trade_date in tickers_and_dates:
            row: dict = {}

            cursor = conn.execute(
                f"SELECT adv_5d, adv_20d, daily_volatility, intraday_volatility, "
                f"total_volume, daily_close "
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
                for k in ("adv_5d", "adv_20d", "daily_volatility",
                          "intraday_volatility", "total_volume", "daily_close"):
                    row[k] = None

            start_times = [
                r["start_time"]
                for r in route_rows
                if r.get("equ_ticker") == ticker
                and r["order_as_of_date"] == trade_date
                and r.get("start_time")
            ]
            interval_start = min(start_times) if start_times else None

            if interval_start:
                before_df = reader.query(
                    "SELECT close FROM bdib_bars "
                    "WHERE equ_ticker = ? AND order_as_of_date = ? "
                    "AND mkt_timestamp < ? "
                    "ORDER BY mkt_timestamp DESC LIMIT 1",
                    [ticker, trade_date, interval_start],
                )
                row["before_interval_close"] = float(before_df["close"].iloc[0]) if not before_df.empty else None
            else:
                row["before_interval_close"] = None

            end_times = [
                r["end_time"]
                for r in route_rows
                if r.get("equ_ticker") == ticker
                and r["order_as_of_date"] == trade_date
                and r.get("end_time")
            ]
            interval_end = max(end_times) if end_times else None
            if interval_end:
                close_df = reader.query(
                    "SELECT close FROM bdib_bars "
                    "WHERE equ_ticker = ? AND order_as_of_date = ? "
                    "AND mkt_timestamp <= ? "
                    "ORDER BY mkt_timestamp DESC LIMIT 1",
                    [ticker, trade_date, interval_end],
                )
                row["interval_close"] = float(close_df["close"].iloc[0]) if not close_df.empty else None
            else:
                row["interval_close"] = None

            if row.get("interval_close") and row.get("before_interval_close"):
                row["price_movement_pct"] = (
                    row["interval_close"] / row["before_interval_close"] - 1.0
                ) * 100.0
            else:
                row["price_movement_pct"] = None

            if interval_start and interval_end:
                count_df = reader.query(
                    "SELECT COUNT(*) AS cnt FROM bdib_bars "
                    "WHERE equ_ticker = ? AND order_as_of_date = ? "
                    "AND mkt_timestamp >= ? AND mkt_timestamp <= ?",
                    [ticker, trade_date, interval_start, interval_end],
                )
                actual_bars = int(count_df["cnt"].iloc[0]) if not count_df.empty else 0
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
        reader.close()

    return ctx


def _get_market_context_sqlite(
    mgr: ConnectionManager,
    tickers_and_dates: set[tuple[str, str]],
    route_rows: list[dict],
    time_series_map: dict,
) -> dict[tuple[str, str], dict]:
    """从 raw_bdib.db 获取市场上下文 (SQLite默认路径)。"""
    if not tickers_and_dates:
        return {}

    conn = _raw_bdib_conn(mgr)
    ctx: dict[tuple[str, str], dict] = {}
    try:
        for ticker, trade_date in tickers_and_dates:
            row: dict = {}

            # ADV + volatility from bdib_daily_summary
            cursor = conn.execute(
                f"SELECT adv_5d, adv_20d, daily_volatility, intraday_volatility, "
                f"total_volume, daily_close "
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

            # Before-interval close
            if interval_start:
                cursor = conn.execute(
                    f"SELECT close FROM {Config.RAW_BDIB_TABLE} "
                    "WHERE equ_ticker = ? AND order_as_of_date = ? "
                    "AND mkt_timestamp < ? "
                    "ORDER BY mkt_timestamp DESC LIMIT 1",
                    [ticker, trade_date, interval_start],
                )
                before_row = cursor.fetchone()
                row["before_interval_close"] = before_row[0] if before_row else None
            else:
                row["before_interval_close"] = None

            # Interval close
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
                    [ticker, trade_date, interval_end],
                )
                close_row = cursor.fetchone()
                row["interval_close"] = close_row[0] if close_row else None
            else:
                row["interval_close"] = None

            # Price movement %
            if row.get("interval_close") and row.get("before_interval_close"):
                row["price_movement_pct"] = (
                    row["interval_close"] / row["before_interval_close"] - 1.0
                ) * 100.0
            else:
                row["price_movement_pct"] = None

            # BDIB bar completeness check (data quality)
            if interval_start and interval_end:
                cursor = conn.execute(
                    f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE} "
                    "WHERE equ_ticker = ? AND order_as_of_date = ? "
                    "AND mkt_timestamp >= ? AND mkt_timestamp <= ?",
                    [ticker, trade_date, interval_start, interval_end],
                )
                actual_bars = cursor.fetchone()[0]
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


# ═══════════════════════════════════════════════════════════════════════════
# TCA route summaries (tca_route_summary table)
# ═══════════════════════════════════════════════════════════════════════════


def get_tca_route_summaries(
    mgr: ConnectionManager,
    filters: TcaFilters,
) -> tuple[list[dict], int]:
    """Query tca_route_summary for routes matching filters.

    Returns (page of route dicts, total_count_without_pagination).
    """
    conditions: list[str] = []
    params: list[Any] = []

    if filters.start_date:
        conditions.append("order_as_of_date >= ?")
        params.append(filters.start_date)
    if filters.end_date:
        conditions.append("order_as_of_date <= ?")
        params.append(filters.end_date)
    if filters.order_ids:
        placeholders = ",".join(["?"] * len(filters.order_ids))
        conditions.append(f"OrderId IN ({placeholders})")
        params.extend(filters.order_ids)
    if filters.algo:
        conditions.append("algo = ?")
        params.append(filters.algo)
    if filters.broker:
        conditions.append("Broker = ?")
        params.append(filters.broker)
    if filters.symbol:
        conditions.append("equ_ticker = ?")
        params.append(filters.symbol)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    conn = _fill_bdib_conn(mgr)
    try:
        if not _table_exists(conn, Config.TCA_ROUTE_SUMMARY_TABLE):
            return [], 0

        base_sql = f"""
            SELECT *
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            {where_clause}
        """
        count_sql = f"SELECT COUNT(*) FROM ({base_sql})"
        total = int(conn.execute(count_sql, params).fetchone()[0])

        paged_sql = base_sql + " ORDER BY order_as_of_date DESC, OrderId, RouteId LIMIT ? OFFSET ?"
        cursor = conn.execute(paged_sql, params + [filters.limit, filters.offset])
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return rows, total
    finally:
        conn.close()


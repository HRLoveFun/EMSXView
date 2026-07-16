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
from typing import Any, Optional

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager
from platform_data.contracts import TcaFilters

from .tca_utils import (
    derive_local_exchange_time as _derive_local_exchange_time,
    to_optional_float as _to_optional_float,
)

logger = logging.getLogger(__name__)

# BDIB查询引擎选择 (Plan §7.2)
_BDIB_ENGINE = Config.BDIB_QUERY_ENGINE


# ═══════════════════════════════════════════════════════════════════════════
# Connection helpers (internal to this module)
# ═══════════════════════════════════════════════════════════════════════════


def _proc_conn(mgr: ConnectionManager) -> sqlite3.Connection:
    return mgr.get_connection("processed_fills", AccessTier.READ, row_factory=sqlite3.Row)


def _fill_bdib_conn(mgr: ConnectionManager) -> sqlite3.Connection:
    return mgr.get_connection("fill_bdib", AccessTier.READ)


def _raw_bdib_conn(mgr: ConnectionManager) -> sqlite3.Connection:
    return mgr.get_connection("raw_bdib", AccessTier.READ, row_factory=sqlite3.Row)


def _raw_fills_conn(mgr: ConnectionManager) -> sqlite3.Connection:
    return mgr.get_connection("raw_fills", AccessTier.READ)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cursor = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ? LIMIT 1",
        [table_name],
    )
    return cursor.fetchone() is not None


# ═══════════════════════════════════════════════════════════════════════════
# Route matching
# ═══════════════════════════════════════════════════════════════════════════


def get_matching_routes(
    mgr: ConnectionManager,
    filters: TcaFilters,
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

    # Algo filter — exact match
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

    history_conditions: list[str] = []
    history_params: list[Any] = []
    if filters.start_date:
        history_conditions.append("rh.order_as_of_date >= ?")
        history_params.append(filters.start_date)
    if filters.end_date:
        history_conditions.append("rh.order_as_of_date <= ?")
        history_params.append(filters.end_date)
    if filters.order_ids:
        placeholders = ",".join(["?"] * len(filters.order_ids))
        history_conditions.append(f"rh.OrderId IN ({placeholders})")
        history_params.extend(filters.order_ids)
    if filters.algo:
        history_conditions.append("COALESCE(rh.algo, oh.algo) = ?")
        history_params.append(filters.algo)
    if filters.broker:
        history_conditions.append("COALESCE(rh.Broker, oh.Broker) = ?")
        history_params.append(filters.broker)
    if filters.symbol:
        history_conditions.append("COALESCE(rh.equ_ticker, oh.equ_ticker) = ?")
        history_params.append(filters.symbol)

    history_where_clause = (
        "WHERE " + " AND ".join(history_conditions)
        if history_conditions
        else ""
    )

    conn = _proc_conn(mgr)
    try:
        if _table_exists(conn, Config.ROUTE_HISTORY_TABLE) and _table_exists(conn, Config.ORDER_HISTORY_TABLE):
            history_sql = f"""
                SELECT
                    rh.OrderId AS order_id,
                    rh.RouteId AS route_id,
                    rh.order_as_of_date,
                    COALESCE(rh.equ_ticker, oh.equ_ticker) AS equ_ticker,
                    COALESCE(rh.ccy_ticker, oh.ccy_ticker) AS ccy_ticker,
                    COALESCE(rh.Side, oh.Side) AS side,
                    COALESCE(rh.algo, oh.algo) AS algo,
                    COALESCE(rh.Broker, oh.Broker) AS broker,
                    COALESCE(rh.TraderName, oh.TraderName) AS trader_name,
                    COALESCE(rh.Exchange, oh.Exchange) AS exchange,
                    rh.first_fill_time AS first_fill_datetime,
                    rh.last_fill_time AS last_fill_datetime,
                    substr(rh.first_fill_time, -8) AS start_time,
                    substr(rh.last_fill_time, -8) AS end_time
                FROM {Config.ROUTE_HISTORY_TABLE} rh
                LEFT JOIN {Config.ORDER_HISTORY_TABLE} oh
                  ON rh.OrderId = oh.OrderId
                 AND rh.order_as_of_date = oh.order_as_of_date
                {history_where_clause}
            """

            count_sql = f"SELECT COUNT(*) FROM ({history_sql})"
            total = int(conn.execute(count_sql, history_params).fetchone()[0])

            paged_sql = (
                history_sql
                + " ORDER BY rh.order_as_of_date DESC, rh.last_fill_time DESC, rh.OrderId LIMIT ? OFFSET ?"
            )
            cursor = conn.execute(paged_sql, history_params + [filters.limit, filters.offset])
            columns = [desc[0] for desc in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return rows, total
    finally:
        conn.close()

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

    conn = _proc_conn(mgr)
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
        local_start = _derive_local_exchange_time(row.get("first_fill_datetime"), row.get("exchange"))
        local_end = _derive_local_exchange_time(row.get("last_fill_datetime"), row.get("exchange"))
        if local_start is not None:
            row["start_time"] = local_start
        if local_end is not None:
            row["end_time"] = local_end

    return rows, total


# ═══════════════════════════════════════════════════════════════════════════
# TCA metrics (fill_bdib.db)
# ═══════════════════════════════════════════════════════════════════════════


def get_tca_metrics(
    mgr: ConnectionManager,
    route_keys: list[tuple[str, str, str]],
) -> dict[tuple[str, str, str], dict]:
    """Fetch the LAST row per (OrderId, RouteId, date) from fill_bdib.db.

    Returns a dict keyed by (order_id, route_id, order_as_of_date).
    """
    if not route_keys:
        return {}

    order_ids = list({k[0] for k in route_keys})
    placeholders = ",".join(["?"] * len(order_ids))

    conn = _fill_bdib_conn(mgr)
    try:
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

    result: dict[tuple[str, str, str], dict] = {}
    for row in all_rows:
        d = dict(zip(columns, row))
        key = (d["OrderId"], d["RouteId"], d["order_as_of_date"])
        if key in {k for k in route_keys}:
            result[key] = d  # last row wins

    return result


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
# Order fill stats (raw_fills.db / order_history)
# ═══════════════════════════════════════════════════════════════════════════


def get_order_fill_stats(
    mgr: ConnectionManager,
    order_ids: list[str],
) -> dict[str, dict[str, Optional[float]]]:
    """Return fill-level order stats derived from raw_fills.db."""
    if not order_ids:
        return {}

    placeholders = ",".join(["?"] * len(order_ids))

    proc = _proc_conn(mgr)
    try:
        if _table_exists(proc, Config.ORDER_HISTORY_TABLE):
            cursor = proc.execute(
                f"SELECT OrderId, SUM(total_fill_shares), MAX(order_amount) "
                f"FROM {Config.ORDER_HISTORY_TABLE} "
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
                result[str(oid)] = {"fill_pct": fill_pct, "filled_volume": filled_volume}
            return result
    finally:
        proc.close()

    conn = _raw_fills_conn(mgr)
    try:
        cursor = conn.execute(
            f"SELECT OrderId, SUM(CAST(FillShares AS REAL)), MAX(CAST(Amount AS REAL)) "
            f"FROM {Config.RAW_FILLS_TABLE} "
            f"WHERE OrderId IN ({placeholders}) "
            "GROUP BY OrderId",
            order_ids,
        )
        result = {}
        for row in cursor.fetchall():
            oid, total_filled, amount = row
            filled_volume = float(total_filled) if total_filled is not None else None
            amount_value = float(amount) if amount is not None else None
            fill_pct = None
            if amount_value and amount_value > 0 and filled_volume is not None:
                fill_pct = round(filled_volume / amount_value * 100.0, 2)
            result[str(oid)] = {"fill_pct": fill_pct, "filled_volume": filled_volume}
    finally:
        conn.close()
    return result




def get_fill_percentages(
    mgr: ConnectionManager,
    order_ids: list[str],
) -> dict[str, Optional[float]]:
    """Compute fill % = sum(FillShares) / Amount per order from raw_fills.db."""
    stats = get_order_fill_stats(mgr, order_ids)
    return {
        order_id: s.get("fill_pct")
        for order_id, s in stats.items()
    }


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


def get_tca_route_summaries_by_keys(
    mgr: ConnectionManager,
    route_keys: list[tuple[str, str, str]],
) -> dict[tuple[str, str, str], dict]:
    """Fetch tca_route_summary rows for specific (OrderId, RouteId, order_as_of_date) keys."""
    if not route_keys:
        return {}

    placeholders = ",".join(["(?, ?, ?)"] * len(route_keys))
    flat_params = [item for key in route_keys for item in key]

    conn = _fill_bdib_conn(mgr)
    try:
        if not _table_exists(conn, Config.TCA_ROUTE_SUMMARY_TABLE):
            return {}

        sql = f"""
            SELECT *
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            WHERE (OrderId, RouteId, order_as_of_date) IN ({placeholders})
        """
        cursor = conn.execute(sql, flat_params)
        columns = [desc[0] for desc in cursor.description]
        result: dict[tuple[str, str, str], dict] = {}
        for row in cursor.fetchall():
            d = dict(zip(columns, row))
            key = (d["OrderId"], d["RouteId"], d["order_as_of_date"])
            result[key] = d
        return result
    finally:
        conn.close()


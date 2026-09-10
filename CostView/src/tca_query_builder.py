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
from typing import Any

from data_access.config import Config
from data_access.storage.connection import AccessTier, ConnectionManager
from platform_data.contracts import TcaFilters

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Connection helpers (internal to this module)
# ═══════════════════════════════════════════════════════════════════════════


def _fill_bdib_conn(mgr: ConnectionManager) -> sqlite3.Connection:
    return mgr.get_connection("fill_bdib", AccessTier.READ)


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

    try:
        conn = _fill_bdib_conn(mgr)
    except FileNotFoundError:
        # 只读模式下 fill_bdib.db 缺失 → 无时序数据（保持空结果降级语义, 009）
        return {}
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

    # P2-2：key 集合循环外一次构建（此前每行重建 set，复杂度 O(行数×key数)）
    route_key_set = set(route_keys)
    result: dict[tuple[str, str, str], list[dict]] = {}
    for row in all_rows:
        d = dict(zip(columns, row))
        key = (d["OrderId"], d["RouteId"], d["order_as_of_date"])
        if key in route_key_set:
            result.setdefault(key, []).append(d)
    return result


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

    try:
        conn = _fill_bdib_conn(mgr)
    except FileNotFoundError:
        # 只读模式下 fill_bdib.db 缺失 → tca_route_summary 无数据（降级为空页, 009）
        return [], 0
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


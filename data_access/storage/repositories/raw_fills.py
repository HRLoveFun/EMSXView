"""Raw fill repository — read-only access to raw_fills.db.

Implements SqliteRawFillReadRepository using ConnectionManager.
写入路径（SqliteRawFillWriteRepository）已随 010-extract-pipeline 迁往
独立仓库 EMSXDataPipeline（唯一写入方）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from ._base import BaseRepository

logger = logging.getLogger(__name__)


class SqliteRawFillReadRepository(BaseRepository):
    """Read access to raw fills and fetch logs."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="raw_fills")

    def get_fills_for_source_date(self, date_str: str) -> pd.DataFrame:
        """Return raw fills for a source_date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM raw_fills WHERE source_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """Return raw fills for an order_as_of_date. Accepts YYYYMMDD or YYYY-MM-DD.

        raw_fills stores order_as_of_date as full datetime string (e.g.
        "2025-09-15 00:00:00"), so we normalize YYYYMMDD input to ISO date and
        try multiple matching strategies for robustness."""
        conn = self._get_read_conn()
        try:
            # 1) Direct match (e.g. full datetime string or YYYY-MM-DD)
            df = pd.read_sql_query(
                "SELECT * FROM raw_fills WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
            if not df.empty:
                return df
            # 2) YYYYMMDD -> YYYY-MM-DD conversion
            iso = None
            if isinstance(date_str, str) and len(date_str) == 8 and date_str.isdigit():
                iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            if iso:
                # 索引友好写法：`substr(order_as_of_date, 1, 10) = ?` 会让
                # idx_raw_order_date 失效（EXPLAIN 实测 `SCAN raw_fills`，14,338,090 行、
                # SELECT * 投影下 51.9s）。改写为半开区间后走
                # `SEARCH ... USING INDEX idx_raw_order_date`，实测 0.000s；
                # 两谓词对全表逐行比对结果一致（mismatch=0），对 len=8 / len=10 / len=19
                # 三种混存格式（本表实测：7,648,102 / 2,263,969 / 4,126,419 行）均语义等价。
                next_iso = (datetime.strptime(iso, "%Y-%m-%d")
                            + timedelta(days=1)).strftime("%Y-%m-%d")
                df = pd.read_sql_query(
                    "SELECT * FROM raw_fills"
                    " WHERE order_as_of_date >= ? AND order_as_of_date < ?",
                    conn.raw_connection,
                    params=[iso, next_iso],
                )
                if not df.empty:
                    return df
            # 3) Fallback: match by source_date
            return pd.read_sql_query(
                "SELECT * FROM raw_fills WHERE source_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_all_source_dates(self) -> List[str]:
        """Return all distinct source_date values."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT source_date FROM raw_fills "
                "WHERE source_date IS NOT NULL AND source_date != '' "
                "ORDER BY source_date"
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_distinct_order_as_of_dates(self) -> List[str]:
        """Return all distinct order_as_of_date values in raw_fills -- the S2 incremental processing key.

        raw_fills stores order_as_of_date as full datetime string (e.g.
        "2025-09-15 00:00:00"), but downstream code (processing_log,
        S2 target_dates, etc.) uses the YYYYMMDD short form. Normalize here to keep
        a single canonical representation across the pipeline."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT order_as_of_date FROM raw_fills "
                "WHERE order_as_of_date IS NOT NULL AND order_as_of_date != '' "
                "ORDER BY order_as_of_date"
            )
            oads: List[str] = []
            for r in cursor.fetchall():
                v = r[0]
                if not v:
                    continue
                # Normalize to YYYYMMDD
                compact = v.replace("-", "").split(" ")[0]
                oads.append(compact)
            return oads
        finally:
            conn.close()

    def get_row_count(self) -> int:
        """Return total rows in raw_fills."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM raw_fills")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_date_row_counts(self) -> Dict[str, int]:
        """Return row counts grouped by source_date."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT source_date, COUNT(*) FROM raw_fills "
                "WHERE source_date IS NOT NULL AND source_date != '' "
                "GROUP BY source_date ORDER BY source_date"
            )
            return {r[0]: r[1] for r in cursor.fetchall()}
        finally:
            conn.close()

    def get_fetch_log_stats(self) -> List[Dict]:
        """Return fetch_log summary."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT source_date, fetch_timestamp, row_count, "
                "data_hash, file_path, status "
                "FROM fetch_log ORDER BY fetch_timestamp DESC"
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_order_fetch_log(
        self,
        source_date: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Return order-level fetch log entries, optionally filtered by date."""
        conn = self._get_read_conn()
        try:
            if source_date:
                cursor = conn.execute(
                    "SELECT order_id, source_date "
                    "FROM order_fetch_log WHERE source_date = ? "
                    "ORDER BY source_date DESC LIMIT ?",
                    (source_date, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT order_id, source_date "
                    "FROM order_fetch_log "
                    "ORDER BY source_date DESC LIMIT ?",
                    (limit,),
                )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_last_fetch_date(self) -> Optional[str]:
        """Return the most recent source_date in fetch_log."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT MAX(source_date) FROM fetch_log WHERE status = 'fetched'"
            )
            return cursor.fetchone()[0]
        finally:
            conn.close()

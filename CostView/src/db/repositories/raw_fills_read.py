"""Raw fill read repository — read access to raw_fills.db.

Implements RawFillReadRepository Protocol using ConnectionManager.
"""

from __future__ import annotations

import logging
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
        """Return raw fills for an order_as_of_date (falls back to source_date)."""
        conn = self._get_read_conn()
        try:
            df = pd.read_sql_query(
                "SELECT * FROM raw_fills WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
            if not df.empty:
                return df
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

"""Raw fill repository — read/write access to raw_fills.db.

Implements SqliteRawFillReadRepository and SqliteRawFillWriteRepository
using ConnectionManager.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.schema.columns import ALL_RAW_COLUMNS, EMSX_FILL_COLUMNS
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


class SqliteRawFillWriteRepository(BaseRepository):
    """Write access to raw fills and fetch logs."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="raw_fills")

    def upsert_raw_api_data(
        self, fills: List[Dict[str, Any]], source_date: str,
    ) -> int:
        """Insert Bloomberg API raw data directly. Returns rows upserted."""
        if not fills:
            return 0

        conn = self._get_write_conn()
        try:
            cols = list(EMSX_FILL_COLUMNS) + ["source_date", "fetched_at"]
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            sql = f"INSERT OR REPLACE INTO raw_fills ({col_names}) VALUES ({placeholders})"

            now = datetime.now().isoformat()
            rows = []
            for f in fills:
                row = []
                for col in EMSX_FILL_COLUMNS:
                    val = f.get(col)
                    row.append(None if val is None else str(val))
                row.append(source_date)
                row.append(now)
                rows.append(tuple(row))

            conn.executemany(sql, rows)
            conn.commit()
            logger.info(f"Upserted {len(rows)} raw API rows (source_date={source_date})")
            return len(rows)
        finally:
            conn.close()

    def upsert_fills(self, df: pd.DataFrame) -> int:
        """Insert or replace cleaned fill records. Returns count of new rows."""
        if df.empty:
            return 0

        conn = self._get_write_conn()
        try:
            all_columns = ALL_RAW_COLUMNS + ["source_date", "ingested_at"]
            insert_columns = [c for c in all_columns if c in df.columns]
            placeholders = ", ".join(["?"] * len(insert_columns))
            col_names = ", ".join(insert_columns)
            sql = f"INSERT OR REPLACE INTO raw_fills ({col_names}) VALUES ({placeholders})"

            count_before = conn.execute("SELECT COUNT(*) FROM raw_fills").fetchone()[0]

            rows = []
            for tup in df[insert_columns].itertuples(index=False, name=None):
                values = []
                for i, col in enumerate(insert_columns):
                    val = tup[i]
                    if pd.isna(val) or val is None:
                        values.append(None)
                    else:
                        values.append(str(val))
                rows.append(tuple(values))

            conn.executemany(sql, rows)
            conn.commit()

            count_after = conn.execute("SELECT COUNT(*) FROM raw_fills").fetchone()[0]
            new_count = count_after - count_before
            logger.info(f"Upserted {len(rows)} fills ({new_count} new)")
            return new_count
        finally:
            conn.close()

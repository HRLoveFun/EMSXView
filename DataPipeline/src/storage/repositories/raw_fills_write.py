"""Raw fill write repository — write access to raw_fills.db.

Implements RawFillWriteRepository Protocol using ConnectionManager.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from DataPipeline.src.common.schema import ALL_RAW_COLUMNS, EMSX_FILL_COLUMNS
from ._base import BaseRepository

logger = logging.getLogger(__name__)


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

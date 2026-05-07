"""Fill write repository — write access to processed_fills.db.

Implements FillWriteRepository Protocol using ConnectionManager.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from DataPipeline.src.storage.connection import AccessTier
from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from DataPipeline.src.common.schema import COLUMN_TYPE_MAP, PROCESSED_COLUMNS, ROUTE_REGISTRY_COLUMNS, AGG_COLUMNS
from ._base import BaseRepository

logger = logging.getLogger(__name__)


class SqliteFillWriteRepository(BaseRepository):
    """Write access to processed fills, aggregations, and processing log."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="processed_fills")

    def upsert_processed_fills(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Upsert processed fills. Returns new row count."""
        if df.empty:
            return 0
        own_conn = conn is None
        if own_conn:
            conn = self._get_write_conn()
        try:
            count = self._upsert_fixed_schema(
                df, Config.PROCESSED_FILLS_TABLE,
                key_columns=["FillId"],
                expected_columns=PROCESSED_COLUMNS,
                type_map=COLUMN_TYPE_MAP,
                conn=conn,
            )
            if own_conn:
                conn.commit()
            return count
        finally:
            if own_conn:
                conn.close()

    def upsert_agg_fills_10s(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Upsert 10s aggregated fills. Returns row count."""
        if df.empty:
            return 0
        own_conn = conn is None
        if own_conn:
            conn = self._get_write_conn()
        try:
            count = self._upsert_fixed_schema(
                df, Config.AGG_10S_TABLE,
                key_columns=["OrderId", "RouteId", "mkt_timestamp", "order_as_of_date"],
                expected_columns=AGG_COLUMNS,
                type_map=COLUMN_TYPE_MAP,
                conn=conn,
            )
            if own_conn:
                conn.commit()
            return count
        finally:
            if own_conn:
                conn.close()

    def upsert_order_labels(self, df: pd.DataFrame) -> int:
        """Upsert order labels."""
        if df.empty:
            return 0
        conn = self._get_write_conn()
        try:
            cols = list(df.columns)
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            sql = f"INSERT OR REPLACE INTO order_label ({col_names}) VALUES ({placeholders})"
            rows = [tuple(r) for r in df[cols].itertuples(index=False, name=None)]
            conn.executemany(sql, rows)
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    def mark_date_processed(
        self, date_str: str, stage: str, row_count: int = 0,
        conn: Optional[object] = None,
    ) -> None:
        """Mark a date as processed for a given stage."""
        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO {Config.PROCESSING_LOG_TABLE} "
                f"(order_as_of_date, row_count, stage) VALUES (?, ?, ?)",
                (date_str, row_count, stage),
            )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    @staticmethod
    def _upsert_fixed_schema(
        df: pd.DataFrame, table: str, *,
        key_columns: list, expected_columns: list,
        type_map: dict, conn,
    ) -> int:
        """Upsert DataFrame into a fixed-schema table.

        Shared utility migrated from BaseProcessedFillsRepo._upsert_fixed_schema.
        """
        insert_columns = [c for c in expected_columns if c in df.columns]
        if not insert_columns:
            return 0
        placeholders = ", ".join(["?"] * len(insert_columns))
        col_names = ", ".join(insert_columns)
        sql = f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})"

        rows = []
        for tup in df[insert_columns].itertuples(index=False, name=None):
            values = []
            for i, col in enumerate(insert_columns):
                val = tup[i]
                if val is None or (isinstance(val, float) and val != val):
                    values.append(None)
                elif col in type_map:
                    target = type_map[col]
                    if target == "REAL":
                        values.append(float(val) if val is not None else None)
                    elif target == "INTEGER":
                        values.append(int(val) if val is not None else None)
                    else:
                        values.append(str(val) if val is not None else None)
                else:
                    values.append(str(val) if val is not None else None)
            rows.append(tuple(values))

        conn.executemany(sql, rows)
        return len(rows)

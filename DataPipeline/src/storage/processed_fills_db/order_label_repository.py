"""
Order label repository.

Manages the ``order_label`` table — a simple mapping from OrderId
to ``order_as_of_date`` used for date-based label lookups.
"""

from __future__ import annotations

import logging

import pandas as pd

from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from ._base import BaseProcessedFillsRepo

logger = logging.getLogger(__name__)


class OrderLabelRepository(BaseProcessedFillsRepo):
    """Repository for order label read/write operations."""

    def upsert_order_labels(self, df: pd.DataFrame) -> int:
        """Insert or replace order label records."""
        if df.empty:
            return 0

        conn = self._get_admin_conn()
        try:
            cursor = conn.execute(f"PRAGMA table_info({Config.ORDER_LABEL_TABLE})")
            existing_cols = {row[1] for row in cursor.fetchall()}

            for col in df.columns:
                if col not in existing_cols:
                    conn.execute(
                        f"ALTER TABLE {Config.ORDER_LABEL_TABLE} ADD COLUMN [{col}] TEXT"
                    )
                    logger.debug(f"Added column [{col}] to {Config.ORDER_LABEL_TABLE}")

            insert_cols = list(df.columns)
            placeholders = ", ".join(["?"] * len(insert_cols))
            col_names = ", ".join(f"[{c}]" for c in insert_cols)

            sql = f"INSERT OR REPLACE INTO {Config.ORDER_LABEL_TABLE} ({col_names}) VALUES ({placeholders})"

            rows = []
            for _, row in df.iterrows():
                values = []
                for col in insert_cols:
                    val = row.get(col)
                    if pd.isna(val) or val is None:
                        values.append(None)
                    else:
                        values.append(str(val))
                rows.append(tuple(values))

            conn.executemany(sql, rows)
            conn.commit()
            logger.info(f"Upserted {len(rows)} order labels")
            return len(rows)
        finally:
            conn.close()

    def get_order_labels(self) -> pd.DataFrame:
        """Get all order labels."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.ORDER_LABEL_TABLE}", conn
            )
        finally:
            conn.close()

    def get_order_labels_for_date(self, date_str: str) -> pd.DataFrame:
        """Get order labels for a specific date."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.ORDER_LABEL_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()
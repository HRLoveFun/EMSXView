"""
Legacy aggregation repository (DEPRECATED).

Manages ``agg_processed_fills`` and ``processed_fills_1min`` — order-level
aggregation tables from the pre-v3 pipeline.  These tables are **disabled**
in the current pipeline but retained for backward-compatibility reads and
ad-hoc manual use.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Set

import pandas as pd

from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from ._base import BaseProcessedFillsRepo

logger = logging.getLogger(__name__)


class LegacyRepository(BaseProcessedFillsRepo):
    """Repository for deprecated legacy aggregation tables.

    .. deprecated::
        Use :class:`AggregationRepository` for new code.  These methods
        operate on order-level (not route-level) tables that are no longer
        populated by the pipeline.
    """

    def _upsert_df_to_table(
        self,
        df: pd.DataFrame,
        table_name: str,
        key_columns: List[str],
        allowed_columns: Optional[Set] = None,
    ) -> int:
        """Legacy dynamic-schema upsert (kept for backward compatibility).

        If ``allowed_columns`` is provided, any DataFrame column not in
        the set is silently dropped (with a WARNING log) instead of being
        auto-added to the table via ``ALTER TABLE``.
        """
        if df.empty:
            return 0

        if allowed_columns is not None:
            full_allowed = allowed_columns | set(key_columns)
            unknown = set(df.columns) - full_allowed
            if unknown:
                logger.warning(
                    f"_upsert_df_to_table({table_name}): dropping {len(unknown)} "
                    f"unknown columns not in whitelist: {sorted(unknown)}"
                )
                df = df[[c for c in df.columns if c in full_allowed]]

        conn = self._get_admin_conn()
        try:
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            existing_cols = {row[1] for row in cursor.fetchall()}

            for col in df.columns:
                if col not in existing_cols:
                    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN [{col}] TEXT")
                    logger.debug(f"Added column [{col}] to {table_name}")

            insert_cols = list(df.columns)
            placeholders = ", ".join(["?"] * len(insert_cols))
            col_names = ", ".join(f"[{c}]" for c in insert_cols)

            sql = f"INSERT OR REPLACE INTO {table_name} ({col_names}) VALUES ({placeholders})"

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
            return len(rows)
        finally:
            conn.close()

    # ── Legacy 10s aggregation (order-level, dynamic schema) ──────────

    def upsert_agg_fills(self, df: pd.DataFrame) -> int:
        """Legacy: upsert 10s aggregated fills (dynamic schema)."""
        count = self._upsert_df_to_table(
            df,
            Config.AGG_PROCESSED_FILLS_TABLE,
            ["OrderId", "mkt_timestamp", "order_as_of_date"],
        )
        logger.info(f"Upserted {count} aggregated fills (10s, legacy dynamic schema)")
        return count

    def get_agg_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """Legacy: get 10s aggregated fills for a date."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.AGG_PROCESSED_FILLS_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    # ── Legacy 1min aggregation (order-level, dynamic schema) ──────────

    def upsert_1min_fills(self, df: pd.DataFrame) -> int:
        """[DEPRECATED] Legacy: upsert 1min aggregated fills (dynamic schema, old order-level)."""
        count = self._upsert_df_to_table(
            df,
            Config.PROCESSED_FILLS_1MIN_TABLE,
            ["OrderId", "mkt_timestamp_1min", "order_as_of_date"],
        )
        logger.info(f"Upserted {count} aggregated fills (1min, legacy dynamic schema)")
        return count

    def get_1min_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """Legacy: get 1min aggregated fills for a date."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.PROCESSED_FILLS_1MIN_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()
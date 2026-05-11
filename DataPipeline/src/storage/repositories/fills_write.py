"""Fill write repository — write access to processed_fills.db."""

from __future__ import annotations

import logging
from typing import List, Optional, Set

import pandas as pd

from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from DataPipeline.src.storage.schema.columns import (
    COLUMN_TYPE_MAP, PROCESSED_COLUMNS, ROUTE_REGISTRY_COLUMNS, AGG_COLUMNS,
    AGG_1MIN_COLUMNS, ORDER_HISTORY_COLUMNS, ROUTE_HISTORY_COLUMNS,
    ROUTE_EVENT_HISTORY_COLUMNS,
)
from ._base import BaseRepository

logger = logging.getLogger(__name__)


class SqliteFillWriteRepository(BaseRepository):
    """Write access to processed fills, aggregations, and processing log."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="processed_fills")

    # ── Private helper ─────────────────────────────────────────────────────

    def _upsert(
        self, df: pd.DataFrame, table: str,
        key_columns: List[str], expected_columns: List[str],
        conn: Optional[object] = None,
    ) -> int:
        """Upsert DataFrame rows into a fixed-schema table.

        Returns row count.  If *conn* is provided the caller owns the
        transaction; otherwise a fresh write connection is opened,
        committed, and closed.
        """
        if df.empty:
            return 0
        own_conn = conn is None
        if own_conn:
            conn = self._get_write_conn()
        try:
            count = self._upsert_fixed_schema(
                df, table,
                key_columns=key_columns,
                expected_columns=expected_columns,
                type_map=COLUMN_TYPE_MAP,
                conn=conn,
            )
            if own_conn:
                conn.commit()
            return count
        finally:
            if own_conn:
                conn.close()

    def upsert_processed_fills(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Upsert processed fills. Returns new row count."""
        return self._upsert(df, Config.PROCESSED_FILLS_TABLE, ["FillId"], PROCESSED_COLUMNS, conn)

    def upsert_agg_fills_10s(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Upsert 10s aggregated fills. Returns row count."""
        return self._upsert(
            df, Config.AGG_10S_TABLE,
            ["OrderId", "RouteId", "mkt_timestamp", "order_as_of_date"],
            AGG_COLUMNS, conn,
        )

    def upsert_order_labels(self, df: pd.DataFrame) -> int:
        """Upsert order labels (dynamic-column upsert)."""
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

    # ── Route registry ────────────────────────────────────────────────────

    def upsert_route_registry(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Insert or replace route registry records."""
        return self._upsert(df, "route_registry", ["OrderId", "RouteId"], ROUTE_REGISTRY_COLUMNS, conn)

    # ── 1-minute aggregation writes ────────────────────────────────────────

    def upsert_agg_fills_1min(self, df: pd.DataFrame) -> int:
        """[DEPRECATED v3] Insert or replace route-level 1-minute aggregated fills."""
        return self._upsert(df, Config.AGG_1MIN_TABLE,
                            ["OrderId", "RouteId", "mkt_timestamp_1min", "order_as_of_date"],
                            AGG_1MIN_COLUMNS)

    # ── Execution history writes (migrated from ExecutionHistoryRepository) ──

    def upsert_order_history(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Insert or replace order history records."""
        return self._upsert(df, Config.ORDER_HISTORY_TABLE,
                            ["OrderId", "order_as_of_date"], ORDER_HISTORY_COLUMNS, conn)

    def upsert_route_history(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Insert or replace route history records."""
        return self._upsert(df, Config.ROUTE_HISTORY_TABLE,
                            ["OrderId", "RouteId", "order_as_of_date"], ROUTE_HISTORY_COLUMNS, conn)

    def upsert_route_event_history(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Insert or replace route event history records."""
        return self._upsert(df, Config.ROUTE_EVENT_HISTORY_TABLE,
                            ["event_id"], ROUTE_EVENT_HISTORY_COLUMNS, conn)

    # ── Ticker metadata writes (migrated from TickerRepository) ────────────

    def update_ticker_date_mapping(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> None:
        """Update ticker→date mapping from processed fills DataFrame."""
        if df.empty:
            return
        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            records = []
            if "equ_ticker" in df.columns and "order_as_of_date" in df.columns:
                for ticker, dates in df.groupby("equ_ticker")["order_as_of_date"].apply(set).items():
                    for date_str in dates:
                        if ticker and date_str:
                            records.append((str(ticker), "equ_ticker", str(date_str)))
            if "ccy_ticker" in df.columns and "order_as_of_date" in df.columns:
                for ticker, dates in df.groupby("ccy_ticker")["order_as_of_date"].apply(set).items():
                    for date_str in dates:
                        if ticker and date_str:
                            records.append((str(ticker), "ccy_ticker", str(date_str)))
            if records:
                conn.executemany(
                    f"INSERT OR IGNORE INTO {Config.TICKER_DATE_MAPPING_TABLE} "
                    "(ticker, ticker_type, order_as_of_date) VALUES (?, ?, ?)",
                    records,
                )
                if own_conn:
                    conn.commit()
        finally:
            if own_conn:
                conn.close()

    def update_ticker_repository(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> None:
        """Upsert equ_ticker → Exchange mapping from aggregated fills."""
        if df.empty or "equ_ticker" not in df.columns or "Exchange" not in df.columns:
            return
        work = df[["equ_ticker", "Exchange"]].dropna().copy()
        if work.empty:
            return
        work["equ_ticker"] = work["equ_ticker"].astype(str).str.strip()
        work["Exchange"] = work["Exchange"].astype(str).str.strip().str.upper()
        work = work[
            work["equ_ticker"].ne("")
            & work["equ_ticker"].str.lower().ne("none")
            & work["equ_ticker"].str.lower().ne("nan")
            & work["Exchange"].ne("")
            & work["Exchange"].str.lower().ne("none")
            & work["Exchange"].str.lower().ne("nan")
        ]
        if work.empty:
            return
        pairs = list(
            work.drop_duplicates(subset=["equ_ticker"])[["equ_ticker", "Exchange"]].itertuples(
                index=False, name=None
            )
        )
        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            conn.executemany(
                "INSERT INTO ticker_repository (equ_ticker, exchange, updated_at) "
                "VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(equ_ticker) DO UPDATE SET "
                "    exchange = excluded.exchange, "
                "    updated_at = datetime('now')",
                pairs,
            )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    def update_ticker_registries(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> None:
        """Update equ_ticker_registry and ccy_ticker_registry from processed fills."""
        if df.empty:
            return
        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            if "equ_ticker" in df.columns and "order_as_of_date" in df.columns:
                equ_groups = (
                    df.groupby("equ_ticker")
                    .agg(
                        first_date=("order_as_of_date", "min"),
                        last_date=("order_as_of_date", "max"),
                        order_count=("OrderId", "nunique"),
                    )
                    .reset_index()
                )
                for _, row in equ_groups.iterrows():
                    ticker = str(row["equ_ticker"])
                    if not ticker:
                        continue
                    conn.execute(
                        f"INSERT INTO {Config.EQU_TICKER_REGISTRY_TABLE} "
                        "(equ_ticker, first_seen_date, last_seen_date, order_count) "
                        "VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(equ_ticker) DO UPDATE SET "
                        "    first_seen_date = MIN(first_seen_date, excluded.first_seen_date), "
                        "    last_seen_date = MAX(last_seen_date, excluded.last_seen_date), "
                        "    order_count = order_count + excluded.order_count",
                        (ticker, str(row["first_date"]), str(row["last_date"]), int(row["order_count"])),
                    )
            if "ccy_ticker" in df.columns and "order_as_of_date" in df.columns:
                ccy_groups = (
                    df.groupby("ccy_ticker")
                    .agg(
                        first_date=("order_as_of_date", "min"),
                        last_date=("order_as_of_date", "max"),
                        order_count=("OrderId", "nunique"),
                    )
                    .reset_index()
                )
                for _, row in ccy_groups.iterrows():
                    ticker = str(row["ccy_ticker"])
                    if not ticker:
                        continue
                    conn.execute(
                        f"INSERT INTO {Config.CCY_TICKER_REGISTRY_TABLE} "
                        "(ccy_ticker, first_seen_date, last_seen_date, order_count) "
                        "VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(ccy_ticker) DO UPDATE SET "
                        "    first_seen_date = MIN(first_seen_date, excluded.first_seen_date), "
                        "    last_seen_date = MAX(last_seen_date, excluded.last_seen_date), "
                        "    order_count = order_count + excluded.order_count",
                        (ticker, str(row["first_date"]), str(row["last_date"]), int(row["order_count"])),
                    )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    # ── Legacy writes (migrated from LegacyRepository) ─────────────────────

    def _upsert_df_to_table(
        self, df: pd.DataFrame, table_name: str,
        key_columns: List[str],
        allowed_columns: Optional[Set] = None,
    ) -> int:
        """Legacy dynamic-schema upsert (kept for backward compatibility)."""
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

    def upsert_agg_fills(self, df: pd.DataFrame) -> int:
        """[DEPRECATED] Legacy: upsert 10s aggregated fills (dynamic schema)."""
        count = self._upsert_df_to_table(
            df, Config.AGG_PROCESSED_FILLS_TABLE,
            ["OrderId", "mkt_timestamp", "order_as_of_date"],
        )
        return count

    def upsert_1min_fills(self, df: pd.DataFrame) -> int:
        """[DEPRECATED] Legacy: upsert 1min aggregated fills (dynamic schema)."""
        count = self._upsert_df_to_table(
            df, Config.PROCESSED_FILLS_1MIN_TABLE,
            ["OrderId", "mkt_timestamp_1min", "order_as_of_date"],
        )
        return count

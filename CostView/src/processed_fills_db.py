"""
Processed Fills SQLite Database — storage for cleaned & enriched fill data.

Stores:
    - processed_fills: fixed 27-column schema (TEXT + REAL numerics), PK=(OrderId, FillId)
    - agg_fills_10s:   route-level 10-second aggregation (23 cols), active in pipeline
    - agg_fills_1min:  route-level 1-minute aggregation (23 cols), **disabled** since v3
                        (table definition kept for backward compat / manual use only)
    - processing_log:   per-date stage tracking (processed -> aggregated -> labeled)
    - ticker_date_mapping: equ_ticker/ccy_ticker -> date index
    - order_label:      OrderId -> order_as_of_date lookup

Legacy tables (deprecated, not used in new flow):
    - agg_processed_fills, processed_fills_1min: old order-level schemas
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd

from .database_access import (
    AccessControlledConnection,
    AccessTier,
    backup_database,
    resolve_access_tier,
)
from .processing_config import ProcessingConfig as Config
from .schema import (
    AGG_1MIN_COLUMNS,
    AGG_COLUMNS,
    COLUMN_TYPE_MAP,
    PROCESSED_COLUMNS,
    ROUTE_REGISTRY_COLUMNS,
)

logger = logging.getLogger(__name__)


class ProcessedFillsDB:
    """SQLite storage for processed EMSX fill data (fixed schema)."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        access_tier: Optional[AccessTier] = None,
    ):
        self.db_path = Path(db_path or Config.PROCESSED_FILLS_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._access_tier = resolve_access_tier(access_tier)
        self._init_db()

    def _get_conn(self) -> AccessControlledConnection:
        """Return an access-controlled SQLite connection."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=Config.SQLITE_CONNECT_TIMEOUT_SEC,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={Config.SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys=ON")
        return AccessControlledConnection(conn, self._access_tier)

    def _get_admin_conn(self) -> sqlite3.Connection:
        """Return a raw connection for schema init (always admin)."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=Config.SQLITE_CONNECT_TIMEOUT_SEC,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={Config.SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _build_column_defs(columns: List[str], type_map: Dict[str, str]) -> str:
        """Build SQL column definition string from column list."""
        parts = []
        for col in columns:
            col_type = type_map.get(col, "TEXT")
            parts.append(f"[{col}] {col_type}")
        return ",\n                    ".join(parts)

    def _init_db(self) -> None:
        """Create tables with fixed schemas."""
        conn = self._get_admin_conn()
        try:
            # IMPORTANT: never drop live tables during normal initialization.
            # `_init_db()` must be idempotent and non-destructive so recurring
            # ProcessedFillsDB() constructions do not wipe data.

            # -- processed_fills: Fact table (Schema V2) --

            proc_cols = self._build_column_defs(PROCESSED_COLUMNS, COLUMN_TYPE_MAP)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.PROCESSED_FILLS_TABLE} (
                    {proc_cols},
                    PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)
                )
            """)

            # Migrate old schema where PK was only FillId (causing massive
            # cross-order/date overwrite) to composite PK.
            self._migrate_processed_fills_pk(conn)

            # Processed_fills schema migration: add missing columns (e.g. Exchange)
            proc_info = conn.execute(f"PRAGMA table_info({Config.PROCESSED_FILLS_TABLE})").fetchall()
            proc_existing_cols = {row[1] for row in proc_info}
            for col in PROCESSED_COLUMNS:
                if col not in proc_existing_cols:
                    col_type = COLUMN_TYPE_MAP.get(col, "TEXT")
                    conn.execute(f"ALTER TABLE {Config.PROCESSED_FILLS_TABLE} ADD COLUMN [{col}] {col_type}")

            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_proc_date
                ON {Config.PROCESSED_FILLS_TABLE} (order_as_of_date)
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_proc_orderid
                ON {Config.PROCESSED_FILLS_TABLE} (OrderId)
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_proc_routeid
                ON {Config.PROCESSED_FILLS_TABLE} (RouteId)
            """)

            # -- route_registry: Dimension table (Schema V2) --
            route_reg_cols = self._build_column_defs(ROUTE_REGISTRY_COLUMNS, COLUMN_TYPE_MAP)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS route_registry (
                    {route_reg_cols},
                    PRIMARY KEY (OrderId, RouteId)
                )
            """)

            # Route registry schema migration: add missing columns (e.g. Exchange)
            route_info = conn.execute("PRAGMA table_info(route_registry)").fetchall()
            route_existing_cols = {row[1] for row in route_info}
            for col in ROUTE_REGISTRY_COLUMNS:
                if col not in route_existing_cols:
                    col_type = COLUMN_TYPE_MAP.get(col, "TEXT")
                    conn.execute(f"ALTER TABLE route_registry ADD COLUMN [{col}] {col_type}")

            # Backfill processed_fills.Exchange from route_registry for legacy rows.
            conn.execute(f"""
                UPDATE {Config.PROCESSED_FILLS_TABLE}
                SET Exchange = (
                    SELECT r.Exchange
                    FROM route_registry r
                    WHERE r.OrderId = {Config.PROCESSED_FILLS_TABLE}.OrderId
                      AND r.RouteId = {Config.PROCESSED_FILLS_TABLE}.RouteId
                )
                WHERE Exchange IS NULL OR TRIM(Exchange) = ''
            """)

            # -- v_processed_fills_legacy: Compatibility view --
            # Use IF NOT EXISTS to avoid DROP+CREATE race under concurrent access.
            # To update the view definition, manually DROP first or bump schema version.
            conn.execute(f"""
                CREATE VIEW IF NOT EXISTS v_processed_fills_legacy AS
                SELECT 
                    r.OrderId,
                    p.FillId,
                    p.order_as_of_date,
                    p.mkt_timestamp,
                    p.exchange_exec_time,
                    CASE
                        WHEN r.equ_ticker IS NULL OR TRIM(r.equ_ticker) = '' THEN NULL
                        WHEN INSTR(TRIM(r.equ_ticker), ' ') > 0 THEN SUBSTR(TRIM(r.equ_ticker), 1, INSTR(TRIM(r.equ_ticker), ' ') - 1)
                        ELSE TRIM(r.equ_ticker)
                    END AS Ticker,
                    r.equ_ticker,
                    CASE
                        WHEN p.Exchange IS NULL OR TRIM(p.Exchange) = '' THEN NULL
                        WHEN LOWER(TRIM(p.Exchange)) IN ('none', 'nan') THEN NULL
                        ELSE UPPER(TRIM(p.Exchange))
                    END AS Exchange,
                    p.Amount,
                    r.Side,
                    CASE
                        WHEN r.ccy_ticker IS NULL OR TRIM(r.ccy_ticker) = '' THEN NULL
                        WHEN INSTR(TRIM(r.ccy_ticker), ' ') > 0 THEN SUBSTR(TRIM(r.ccy_ticker), 1, INSTR(TRIM(r.ccy_ticker), ' ') - 1)
                        ELSE SUBSTR(TRIM(r.ccy_ticker), 1, 3)
                    END AS Currency,
                    p.region,
                    p.Broker,
                    p.StrategyType,
                    p.algo,
                    r.ccy_ticker,
                    p.is_closing_auction,
                    p.route_as_of_time,
                    p.RouteShares,
                    p.TraderName,
                    p.FillPrice,
                    p.FillShares,
                    p.ExecType,
                    r.RouteId,
                    p.DateTimeOfFill
                FROM {Config.PROCESSED_FILLS_TABLE} p
                LEFT JOIN route_registry r ON p.OrderId = r.OrderId AND p.RouteId = r.RouteId
            """)

            # -- agg_fills_10s: route-level 10s aggregation --
            agg_cols = self._build_column_defs(AGG_COLUMNS, COLUMN_TYPE_MAP)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.AGG_10S_TABLE} (
                    {agg_cols},
                    PRIMARY KEY (OrderId, RouteId, mkt_timestamp, order_as_of_date)
                )
            """)

            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_agg_10s_order_route
                ON {Config.AGG_10S_TABLE} (OrderId, RouteId)
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_agg_10s_date
                ON {Config.AGG_10S_TABLE} (order_as_of_date)
            """)

            # -- agg_fills_1min: route-level 1min aggregation --
            agg_1min_cols = self._build_column_defs(AGG_1MIN_COLUMNS, COLUMN_TYPE_MAP)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.AGG_1MIN_TABLE} (
                    {agg_1min_cols},
                    PRIMARY KEY (OrderId, RouteId, mkt_timestamp_1min, order_as_of_date)
                )
            """)

            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_agg_1min_date
                ON {Config.AGG_1MIN_TABLE} (order_as_of_date)
            """)

            # -- processing_log: track which dates have been processed --
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.PROCESSING_LOG_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_as_of_date TEXT NOT NULL,
                    processing_timestamp TEXT DEFAULT (datetime('now')),
                    row_count INTEGER,
                    stage TEXT DEFAULT 'processed',
                    UNIQUE(order_as_of_date, stage)
                )
            """)

            # -- ticker_date_mapping: equ_ticker/ccy_ticker -> dates --
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.TICKER_DATE_MAPPING_TABLE} (
                    ticker TEXT NOT NULL,
                    ticker_type TEXT NOT NULL,
                    order_as_of_date TEXT NOT NULL,
                    PRIMARY KEY (ticker, ticker_type, order_as_of_date)
                )
            """)

            # -- order_label --
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.ORDER_LABEL_TABLE} (
                    OrderId TEXT PRIMARY KEY,
                    order_as_of_date TEXT
                )
            """)

            # -- ticker_repository: equ_ticker -> exchange mapping for BDIB fetch --
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ticker_repository (
                    equ_ticker TEXT PRIMARY KEY,
                    exchange   TEXT,
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)

            # -- equ_ticker_registry: downstream summary (Phase 4A) --
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.EQU_TICKER_REGISTRY_TABLE} (
                    equ_ticker      TEXT PRIMARY KEY,
                    first_seen_date TEXT,
                    last_seen_date  TEXT,
                    order_count     INTEGER DEFAULT 0
                )
            """)

            # -- ccy_ticker_registry: downstream summary (Phase 4A) --
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.CCY_TICKER_REGISTRY_TABLE} (
                    ccy_ticker      TEXT PRIMARY KEY,
                    first_seen_date TEXT,
                    last_seen_date  TEXT,
                    order_count     INTEGER DEFAULT 0
                )
            """)

            # -- Legacy tables (kept for backward compatibility, not used in new flow) --
            # agg_processed_fills (order-level, old schema)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.AGG_PROCESSED_FILLS_TABLE} (
                    OrderId TEXT NOT NULL,
                    mkt_timestamp TEXT NOT NULL,
                    order_as_of_date TEXT,
                    PRIMARY KEY (OrderId, mkt_timestamp, order_as_of_date)
                )
            """)
            # processed_fills_1min (order-level, old schema)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.PROCESSED_FILLS_1MIN_TABLE} (
                    OrderId TEXT NOT NULL,
                    mkt_timestamp_1min TEXT NOT NULL,
                    order_as_of_date TEXT,
                    PRIMARY KEY (OrderId, mkt_timestamp_1min, order_as_of_date)
                )
            """)

            conn.commit()
            logger.debug(f"Processed fills DB initialized at {self.db_path}")
        finally:
            conn.close()

    def _migrate_processed_fills_pk(self, conn: sqlite3.Connection) -> None:
        """Upgrade processed_fills PK to composite key if needed."""
        cursor = conn.execute(f"PRAGMA table_info({Config.PROCESSED_FILLS_TABLE})")
        col_info = cursor.fetchall()
        if not col_info:
            return

        pk_columns = [row[1] for row in col_info if row[5] > 0]
        desired_pk = {"OrderId", "RouteId", "FillId", "order_as_of_date"}
        if set(pk_columns) == desired_pk:
            return

        logger.warning(
            "Migrating processed_fills PK from %s to %s",
            pk_columns,
            sorted(desired_pk),
        )

        old_table = Config.PROCESSED_FILLS_TABLE
        new_table = f"{old_table}_new"
        backup_table = f"{old_table}_backup"

        # Compatibility view depends on processed_fills; drop before table swap.
        conn.execute("DROP VIEW IF EXISTS v_processed_fills_legacy")
        conn.execute(f"DROP TABLE IF EXISTS {new_table}")

        # ── Pre-migration conflict detection ──
        conflict_cursor = conn.execute(
            f"""SELECT OrderId, FillId, COUNT(*) as cnt
                FROM {old_table}
                GROUP BY OrderId, FillId
                HAVING COUNT(*) > 1"""
        )
        conflicts = conflict_cursor.fetchall()
        if conflicts:
            logger.warning(
                f"processed_fills PK migration: {len(conflicts)} (OrderId,FillId) "
                f"pairs have multiple variants — INSERT OR REPLACE will keep "
                f"the last-encountered row per new PK"
            )

        # ── Backup old table before destructive migration ──
        conn.execute(f"DROP TABLE IF EXISTS {backup_table}")
        conn.execute(
            f"CREATE TABLE {backup_table} AS SELECT * FROM {old_table}"
        )
        backup_count = conn.execute(
            f"SELECT COUNT(*) FROM {backup_table}"
        ).fetchone()[0]
        logger.info(f"processed_fills PK migration: backed up {backup_count} rows to {backup_table}")

        proc_cols = self._build_column_defs(PROCESSED_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE {new_table} (
                {proc_cols},
                PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)
            )
        """)

        old_columns = [row[1] for row in col_info]
        copy_cols = [c for c in PROCESSED_COLUMNS if c in old_columns]
        if copy_cols:
            cols = ", ".join(f"[{c}]" for c in copy_cols)
            conn.execute(
                f"INSERT OR REPLACE INTO {new_table} ({cols}) SELECT {cols} FROM {old_table}"
            )

        conn.execute(f"DROP TABLE {old_table}")
        conn.execute(f"ALTER TABLE {new_table} RENAME TO {old_table}")
        conn.commit()

    # -- Fixed-schema upsert (no ALTER TABLE) ---

    def _upsert_fixed_schema(
        self,
        df: pd.DataFrame,
        table_name: str,
        key_columns: List[str],
        expected_columns: List[str],
        type_map: Dict[str, str],
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Insert or replace using a fixed column set (no dynamic ALTER TABLE).

        Only writes columns present in expected_columns. Others are silently dropped.
        If conn is provided, uses it without commit/close (caller manages transaction).
        """
        if df.empty:
            return 0

        # Filter to expected columns only
        insert_cols = [c for c in expected_columns if c in df.columns]
        if not insert_cols:
            logger.warning(f"No expected columns found in DataFrame for {table_name}")
            return 0

        own_conn = conn is None
        if own_conn:
            conn = self._get_conn()
        try:
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
                    elif type_map.get(col) in ("REAL", "INTEGER"):
                        values.append(val)
                    else:
                        values.append(str(val))
                rows.append(tuple(values))

            conn.executemany(sql, rows)
            if own_conn:
                conn.commit()
            return len(rows)
        finally:
            if own_conn:
                conn.close()

    # -- Processed Fills Fact Table (Schema V2) ---

    def upsert_processed_fills(self, df: pd.DataFrame, conn: Optional[sqlite3.Connection] = None) -> int:
        """Insert or replace processed fill records (Fact table).

        If conn is provided, uses it without commit/close (caller manages transaction).
        """
        count = self._upsert_fixed_schema(
            df, Config.PROCESSED_FILLS_TABLE,
            key_columns=["FillId"],
            expected_columns=PROCESSED_COLUMNS,
            type_map=COLUMN_TYPE_MAP,
            conn=conn,
        )
        logger.info(f"Upserted {count} processed fills (Fact table schema)")
        return count

    # -- Route Registry Dimension Table (Schema V2) ---

    def upsert_route_registry(self, df: pd.DataFrame, conn: Optional[sqlite3.Connection] = None) -> int:
        """Insert or replace route registry records.

        If conn is provided, uses it without commit/close (caller manages transaction).
        """
        count = self._upsert_fixed_schema(
            df, "route_registry",
            key_columns=["OrderId", "RouteId"],
            expected_columns=ROUTE_REGISTRY_COLUMNS,
            type_map=COLUMN_TYPE_MAP,
            conn=conn,
        )
        logger.info(f"Upserted {count} route registry records")
        return count

    def get_processed_fills_for_date(self, date_str: str, use_legacy_view: bool = False) -> pd.DataFrame:
        """Get processed fills for a specific order_as_of_date.
        If use_legacy_view is True, reads from v_processed_fills_legacy to provide the old 27-column structure.
        """
        table_or_view = "v_processed_fills_legacy" if use_legacy_view else Config.PROCESSED_FILLS_TABLE
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {table_or_view} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_processed_fills_for_date_range(self, start: str, end: str, use_legacy_view: bool = False) -> pd.DataFrame:
        """Get processed fills for a date range (inclusive, YYYYMMDD)."""
        table_or_view = "v_processed_fills_legacy" if use_legacy_view else Config.PROCESSED_FILLS_TABLE
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"""SELECT * FROM {table_or_view}
                    WHERE order_as_of_date >= ? AND order_as_of_date <= ?
                    ORDER BY order_as_of_date, mkt_timestamp""",
                conn,
                params=[start, end],
            )
        finally:
            conn.close()

    def get_all_processed_fills(self, use_legacy_view: bool = False) -> pd.DataFrame:
        """Get all processed fills."""
        table_or_view = "v_processed_fills_legacy" if use_legacy_view else Config.PROCESSED_FILLS_TABLE
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {table_or_view}", conn
            )
        finally:
            conn.close()

    # -- Aggregated Fills (route-level, fixed schema) ---

    def upsert_agg_fills_10s(self, df: pd.DataFrame, conn: Optional[sqlite3.Connection] = None) -> int:
        """Insert or replace route-level 10-second aggregated fills."""
        own_conn = conn is None
        if own_conn:
            conn = self._get_conn()

        try:
            count = self._upsert_fixed_schema(
                df, Config.AGG_10S_TABLE,
                key_columns=["OrderId", "RouteId", "mkt_timestamp", "order_as_of_date"],
                expected_columns=AGG_COLUMNS,
                type_map=COLUMN_TYPE_MAP,
                conn=conn,
            )
            self.update_ticker_repository(df, conn=conn)
            if own_conn:
                conn.commit()
            logger.info(f"Upserted {count} route-level agg fills (10s)")
            return count
        finally:
            if own_conn:
                conn.close()

    def upsert_agg_fills_1min(self, df: pd.DataFrame) -> int:
        """[DEPRECATED v3] Insert or replace route-level 1-minute aggregated fills.

        The 1-minute aggregation has been disabled in the pipeline (pipeline.py
        run_aggregate()). This method and the agg_fills_1min table are retained
        for backward compatibility and potential manual ad-hoc use only.
        """
        count = self._upsert_fixed_schema(
            df, Config.AGG_1MIN_TABLE,
            key_columns=["OrderId", "RouteId", "mkt_timestamp_1min", "order_as_of_date"],
            expected_columns=AGG_1MIN_COLUMNS,
            type_map=COLUMN_TYPE_MAP,
        )
        logger.info(f"Upserted {count} route-level agg fills (1min)")
        return count

    def get_agg_fills_10s_for_date(self, date_str: str) -> pd.DataFrame:
        """Get route-level 10s aggregated fills for a date."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.AGG_10S_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_agg_fills_1min_for_date(self, date_str: str) -> pd.DataFrame:
        """[DEPRECATED v3] Get route-level 1min aggregated fills for a date."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.AGG_1MIN_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    # -- Legacy agg methods (DEPRECATED, backward compat only, dynamic schema) --

    def _upsert_df_to_table(
        self,
        df: pd.DataFrame,
        table_name: str,
        key_columns: List[str],
        allowed_columns: Optional[set] = None,
    ) -> int:
        """Legacy dynamic-schema upsert (kept for backward compatibility).
        
        If allowed_columns is provided, any DataFrame column not in the set
        is silently dropped (with a WARNING log) instead of being auto-added
        to the table via ALTER TABLE.
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

        conn = self._get_conn()
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

    def upsert_agg_fills(self, df: pd.DataFrame) -> int:
        """Legacy: upsert 10s aggregated fills (dynamic schema)."""
        count = self._upsert_df_to_table(
            df, Config.AGG_PROCESSED_FILLS_TABLE,
            ["OrderId", "mkt_timestamp", "order_as_of_date"],
        )
        logger.info(f"Upserted {count} aggregated fills (10s, legacy dynamic schema)")
        return count

    def get_agg_fills_for_date(self, date_str: str) -> pd.DataFrame:
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.AGG_PROCESSED_FILLS_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    def upsert_1min_fills(self, df: pd.DataFrame) -> int:
        """[DEPRECATED] Legacy: upsert 1min aggregated fills (dynamic schema, old order-level)."""
        count = self._upsert_df_to_table(
            df, Config.PROCESSED_FILLS_1MIN_TABLE,
            ["OrderId", "mkt_timestamp_1min", "order_as_of_date"],
        )
        logger.info(f"Upserted {count} aggregated fills (1min, legacy dynamic schema)")
        return count

    def get_1min_fills_for_date(self, date_str: str) -> pd.DataFrame:
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.PROCESSED_FILLS_1MIN_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    # -- Order Labels ---

    def upsert_order_labels(self, df: pd.DataFrame) -> int:
        """Insert or replace order label records."""
        count = self._upsert_df_to_table(
            df, Config.ORDER_LABEL_TABLE, ["OrderId"]
        )
        logger.info(f"Upserted {count} order labels")
        return count

    def get_order_labels(self) -> pd.DataFrame:
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.ORDER_LABEL_TABLE}", conn
            )
        finally:
            conn.close()

    def get_order_labels_for_date(self, date_str: str) -> pd.DataFrame:
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.ORDER_LABEL_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    # -- Processing Log ---

    def mark_date_processed(self, date_str: str, stage: str = "processed", row_count: int = 0, conn: Optional[sqlite3.Connection] = None) -> None:
        """Record that a date has been processed at a given stage.

        If conn is provided, uses it without commit/close (caller manages transaction).
        """
        own_conn = conn is None
        if own_conn:
            conn = self._get_conn()
        try:
            conn.execute(
                f"""INSERT OR REPLACE INTO {Config.PROCESSING_LOG_TABLE}
                    (order_as_of_date, row_count, stage)
                    VALUES (?, ?, ?)""",
                (date_str, row_count, stage),
            )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    def get_processed_dates(self, stage: str = "processed") -> List[str]:
        """Get all dates that have been processed at a given stage."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT DISTINCT order_as_of_date
                    FROM {Config.PROCESSING_LOG_TABLE}
                    WHERE stage = ?
                    ORDER BY order_as_of_date""",
                (stage,),
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_unprocessed_dates(self, raw_dates: List[str], stage: str = "processed") -> List[str]:
        """Get dates from raw_dates that haven't been processed at the given stage."""
        processed = set(self.get_processed_dates(stage))
        return [d for d in raw_dates if d not in processed]

    # -- Ticker-Date Mapping ---

    def update_ticker_date_mapping(self, df: pd.DataFrame, conn: Optional[sqlite3.Connection] = None) -> None:
        """Update ticker->date mapping from processed fills DataFrame.

        If conn is provided, uses it without commit/close (caller manages transaction).
        """
        if df.empty:
            return

        own_conn = conn is None
        if own_conn:
            conn = self._get_conn()
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
                    f"""INSERT OR IGNORE INTO {Config.TICKER_DATE_MAPPING_TABLE}
                        (ticker, ticker_type, order_as_of_date) VALUES (?, ?, ?)""",
                    records,
                )
                if own_conn:
                    conn.commit()
                logger.debug(f"Updated ticker-date mapping: {len(records)} entries")
        finally:
            if own_conn:
                conn.close()

    def get_ticker_dates(self, ticker_type: str = "equ_ticker") -> Dict[str, List[str]]:
        """Get ticker->dates mapping."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT ticker, order_as_of_date
                    FROM {Config.TICKER_DATE_MAPPING_TABLE}
                    WHERE ticker_type = ?
                    ORDER BY ticker, order_as_of_date""",
                (ticker_type,),
            )
            result: Dict[str, List[str]] = {}
            for ticker, date_str in cursor.fetchall():
                result.setdefault(ticker, []).append(date_str)
            return result
        finally:
            conn.close()

    def update_ticker_repository(self, df: pd.DataFrame, conn: Optional[sqlite3.Connection] = None) -> None:
        """Upsert equ_ticker -> Exchange mapping from aggregated fills."""
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

        pairs = list(work.drop_duplicates(subset=["equ_ticker"])[["equ_ticker", "Exchange"]].itertuples(index=False, name=None))

        own_conn = conn is None
        if own_conn:
            conn = self._get_conn()
        try:
            conn.executemany(
                """
                INSERT INTO ticker_repository (equ_ticker, exchange, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(equ_ticker) DO UPDATE SET
                    exchange = excluded.exchange,
                    updated_at = datetime('now')
                """,
                pairs,
            )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    def get_ticker_exchange_map(
        self,
        tickers: Optional[List[str]] = None,
        exchanges: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Get equ_ticker -> Exchange mapping from ticker_repository."""
        conn = self._get_conn()
        try:
            params: List[str] = []
            where_clauses: List[str] = []

            if tickers:
                clean_tickers = [str(t).strip() for t in tickers if str(t).strip()]
                if not clean_tickers:
                    return {}
                where_clauses.append(f"equ_ticker IN ({','.join(['?'] * len(clean_tickers))})")
                params.extend(clean_tickers)

            if exchanges:
                clean_exchanges = [str(e).strip().upper() for e in exchanges if str(e).strip()]
                if not clean_exchanges:
                    return {}
                where_clauses.append(f"UPPER(exchange) IN ({','.join(['?'] * len(clean_exchanges))})")
                params.extend(clean_exchanges)

            query = "SELECT equ_ticker, exchange FROM ticker_repository"
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)

            rows = conn.execute(query, params).fetchall()

            return {
                str(ticker): str(exchange).upper()
                for ticker, exchange in rows
                if ticker is not None and exchange is not None and str(exchange).strip()
            }
        finally:
            conn.close()

    # -- Ticker Registry (Phase 4A) ---

    def update_ticker_registries(self, df: pd.DataFrame, conn: Optional[sqlite3.Connection] = None) -> None:
        """Update equ_ticker_registry and ccy_ticker_registry from processed fills.

        Computes first_seen_date, last_seen_date, and order_count per ticker.
        Uses INSERT OR REPLACE with MIN/MAX logic for date tracking.
        If conn is provided, uses it without commit/close (caller manages transaction).
        """
        if df.empty:
            return

        own_conn = conn is None
        if own_conn:
            conn = self._get_conn()
        try:
            # Equity ticker registry
            if "equ_ticker" in df.columns and "order_as_of_date" in df.columns:
                equ_groups = df.groupby("equ_ticker").agg(
                    first_date=("order_as_of_date", "min"),
                    last_date=("order_as_of_date", "max"),
                    order_count=("OrderId", "nunique"),
                ).reset_index()

                for _, row in equ_groups.iterrows():
                    ticker = str(row["equ_ticker"])
                    if not ticker:
                        continue
                    conn.execute(
                        f"""INSERT INTO {Config.EQU_TICKER_REGISTRY_TABLE}
                            (equ_ticker, first_seen_date, last_seen_date, order_count)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(equ_ticker) DO UPDATE SET
                                first_seen_date = MIN(first_seen_date, excluded.first_seen_date),
                                last_seen_date = MAX(last_seen_date, excluded.last_seen_date),
                                order_count = order_count + excluded.order_count""",
                        (ticker, str(row["first_date"]),
                         str(row["last_date"]), int(row["order_count"])),
                    )

            # Currency ticker registry
            if "ccy_ticker" in df.columns and "order_as_of_date" in df.columns:
                ccy_groups = df.groupby("ccy_ticker").agg(
                    first_date=("order_as_of_date", "min"),
                    last_date=("order_as_of_date", "max"),
                    order_count=("OrderId", "nunique"),
                ).reset_index()

                for _, row in ccy_groups.iterrows():
                    ticker = str(row["ccy_ticker"])
                    if not ticker:
                        continue
                    conn.execute(
                        f"""INSERT INTO {Config.CCY_TICKER_REGISTRY_TABLE}
                            (ccy_ticker, first_seen_date, last_seen_date, order_count)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(ccy_ticker) DO UPDATE SET
                                first_seen_date = MIN(first_seen_date, excluded.first_seen_date),
                                last_seen_date = MAX(last_seen_date, excluded.last_seen_date),
                                order_count = order_count + excluded.order_count""",
                        (ticker, str(row["first_date"]),
                         str(row["last_date"]), int(row["order_count"])),
                    )

            if own_conn:
                conn.commit()
            logger.debug("Updated ticker registries")
        finally:
            if own_conn:
                conn.close()

    def get_equ_ticker_registry(self) -> pd.DataFrame:
        """Get all equity tickers from the registry."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.EQU_TICKER_REGISTRY_TABLE} ORDER BY equ_ticker",
                conn,
            )
        finally:
            conn.close()

    def get_ccy_ticker_registry(self) -> pd.DataFrame:
        """Get all currency tickers from the registry."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.CCY_TICKER_REGISTRY_TABLE} ORDER BY ccy_ticker",
                conn,
            )
        finally:
            conn.close()

    # -- Stats ---

    def get_processing_stats(self) -> Dict[str, Any]:
        """Get summary statistics across all tables."""
        conn = self._get_conn()
        try:
            stats = {}
            for table in [
                Config.PROCESSED_FILLS_TABLE,
                Config.AGG_10S_TABLE,
                Config.AGG_1MIN_TABLE,
                Config.AGG_PROCESSED_FILLS_TABLE,
                Config.PROCESSED_FILLS_1MIN_TABLE,
                Config.ORDER_LABEL_TABLE,
            ]:
                try:
                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    stats[table] = cursor.fetchone()[0]
                except sqlite3.OperationalError:
                    stats[table] = 0

            try:
                cursor = conn.execute(
                    f"""SELECT stage, COUNT(DISTINCT order_as_of_date)
                        FROM {Config.PROCESSING_LOG_TABLE}
                        GROUP BY stage"""
                )
                stats["processing_stages"] = {r[0]: r[1] for r in cursor.fetchall()}
            except sqlite3.OperationalError:
                stats["processing_stages"] = {}

            return stats
        finally:
            conn.close()

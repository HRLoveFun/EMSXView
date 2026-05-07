"""
Base class and schema initialization for processed_fills.db repositories.

All domain-specific repositories inherit from ``BaseProcessedFillsRepo`` to
reuse connection setup and access control.  Schema creation is coordinated
here — not scattered across 6 files — because the 15+ tables have
interdependencies (views, FK-style joins, migration order).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from DataPipeline.src.storage.connection import (
    AccessControlledConnection,
    AccessTier,
    ConnectionManager,
    resolve_access_tier,
)
from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from DataPipeline.src.common.schema import (
    AGG_1MIN_COLUMNS,
    AGG_COLUMNS,
    COLUMN_TYPE_MAP,
    ORDER_HISTORY_COLUMNS,
    PROCESSED_COLUMNS,
    ROUTE_EVENT_HISTORY_COLUMNS,
    ROUTE_HISTORY_COLUMNS,
    ROUTE_REGISTRY_COLUMNS,
)

logger = logging.getLogger(__name__)


class BaseProcessedFillsRepo:
    """Base class providing shared DB connection management.

    All domain-specific repositories inherit from this class to reuse
    connection setup, access control, and path configuration.

    Parameters
    ----------
    db_path : str, optional
        Path to the processed_fills.db file.  Defaults to
        ``Config.PROCESSED_FILLS_DB``.
    access_tier : AccessTier, optional
        Permission tier for the connection.  Resolved from environment
        variable ``COSTVIEW_DB_ACCESS`` if not provided.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        access_tier: Optional[AccessTier] = None,
        connection_manager: Optional[ConnectionManager] = None,
    ):
        self.db_path = Path(db_path or Config.PROCESSED_FILLS_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._access_tier = resolve_access_tier(access_tier)
        if connection_manager is not None:
            self._mgr = connection_manager
        else:
            overrides = {"processed_fills": self.db_path} if db_path else {}
            self._mgr = ConnectionManager(path_overrides=overrides)

    def _get_conn(self) -> AccessControlledConnection:
        """Return an access-controlled SQLite connection."""
        return self._mgr.get_connection("processed_fills", self._access_tier)

    def _get_admin_conn(self) -> sqlite3.Connection:
        """Return a raw connection for schema init (always admin)."""
        return self._mgr.get_admin_connection("processed_fills")

    @staticmethod
    def _build_column_defs(columns: List[str], type_map: Dict[str, str]) -> str:
        """Build SQL column definition string from column list."""
        parts = []
        for col in columns:
            col_type = type_map.get(col, "TEXT")
            parts.append(f"[{col}] {col_type}")
        return ",\n                    ".join(parts)

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

        Only writes columns present in ``expected_columns``.  Others are
        silently dropped.

        Parameters
        ----------
        df : pd.DataFrame
            Data to upsert.
        table_name : str
            Target table.
        key_columns : List[str]
            Columns that form the unique key (unused in SQL, for documentation).
        expected_columns : List[str]
            Allowed column set.
        type_map : Dict[str, str]
            Column → SQLite type mapping.
        conn : sqlite3.Connection, optional
            If provided, uses it without commit/close (caller manages transaction).
            If None, opens and closes its own admin connection.
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
            conn = self._get_admin_conn()
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


# ── Schema Initialization ──────────────────────────────────────────────────


def init_processed_fills_schema(repo: BaseProcessedFillsRepo) -> None:
    """Initialize ALL tables in processed_fills.db.

    Called once at startup (or on first ``ProcessedFillsDB()`` construction).
    Each table's DDL is kept here to guarantee creation order and
    inter-table dependencies (views, migration).

    Parameters
    ----------
    repo : BaseProcessedFillsRepo
        Any repository instance — only used for ``_get_admin_conn()``
        and ``_build_column_defs()``.
    """
    conn = repo._get_admin_conn()
    try:
        # IMPORTANT: never drop live tables during normal initialization.
        # This function must be idempotent and non-destructive so recurring
        # ProcessedFillsDB() constructions do not wipe data.

        # -- processed_fills: Fact table (Schema V2) --
        proc_cols = repo._build_column_defs(PROCESSED_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.PROCESSED_FILLS_TABLE} (
                {proc_cols},
                PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)
            )
        """)

        # Migrate old schema where PK was only FillId
        _migrate_processed_fills_pk(repo, conn)

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
        route_reg_cols = repo._build_column_defs(ROUTE_REGISTRY_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS route_registry (
                {route_reg_cols},
                PRIMARY KEY (OrderId, RouteId)
            )
        """)

        # Order history
        order_history_cols = repo._build_column_defs(ORDER_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.ORDER_HISTORY_TABLE} (
                {order_history_cols},
                PRIMARY KEY (OrderId, order_as_of_date)
            )
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_order_history_date
            ON {Config.ORDER_HISTORY_TABLE} (order_as_of_date)
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_order_history_ticker
            ON {Config.ORDER_HISTORY_TABLE} (equ_ticker)
        """)

        # Route history
        route_history_cols = repo._build_column_defs(ROUTE_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.ROUTE_HISTORY_TABLE} (
                {route_history_cols},
                PRIMARY KEY (OrderId, RouteId, order_as_of_date)
            )
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_route_history_date
            ON {Config.ROUTE_HISTORY_TABLE} (order_as_of_date)
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_route_history_ticker
            ON {Config.ROUTE_HISTORY_TABLE} (equ_ticker)
        """)

        # Route event history
        route_event_history_cols = repo._build_column_defs(ROUTE_EVENT_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.ROUTE_EVENT_HISTORY_TABLE} (
                {route_event_history_cols},
                PRIMARY KEY (event_id)
            )
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_route_event_history_date
            ON {Config.ROUTE_EVENT_HISTORY_TABLE} (order_as_of_date)
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_route_event_history_route
            ON {Config.ROUTE_EVENT_HISTORY_TABLE} (OrderId, RouteId)
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_route_event_history_timestamp
            ON {Config.ROUTE_EVENT_HISTORY_TABLE} (event_timestamp)
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
        agg_cols = repo._build_column_defs(AGG_COLUMNS, COLUMN_TYPE_MAP)
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
        agg_1min_cols = repo._build_column_defs(AGG_1MIN_COLUMNS, COLUMN_TYPE_MAP)
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

        # -- Legacy tables (kept for backward compatibility) --
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.AGG_PROCESSED_FILLS_TABLE} (
                OrderId TEXT NOT NULL,
                mkt_timestamp TEXT NOT NULL,
                order_as_of_date TEXT,
                PRIMARY KEY (OrderId, mkt_timestamp, order_as_of_date)
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.PROCESSED_FILLS_1MIN_TABLE} (
                OrderId TEXT NOT NULL,
                mkt_timestamp_1min TEXT NOT NULL,
                order_as_of_date TEXT,
                PRIMARY KEY (OrderId, mkt_timestamp_1min, order_as_of_date)
            )
        """)

        conn.commit()
        logger.debug(f"Processed fills DB initialized at {repo.db_path}")
    finally:
        conn.close()


def _migrate_processed_fills_pk(repo: BaseProcessedFillsRepo, conn: sqlite3.Connection) -> None:
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

    # Pre-migration conflict detection
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

    # Backup old table before destructive migration
    conn.execute(f"DROP TABLE IF EXISTS {backup_table}")
    conn.execute(
        f"CREATE TABLE {backup_table} AS SELECT * FROM {old_table}"
    )
    backup_count = conn.execute(
        f"SELECT COUNT(*) FROM {backup_table}"
    ).fetchone()[0]
    logger.info(f"processed_fills PK migration: backed up {backup_count} rows to {backup_table}")

    proc_cols = repo._build_column_defs(PROCESSED_COLUMNS, COLUMN_TYPE_MAP)
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
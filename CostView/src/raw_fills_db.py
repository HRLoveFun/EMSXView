"""
Raw Fills SQLite Database — primary storage for Bloomberg EMSX fill data (v3).

Stores raw EMSX API data (28 original + 5 derived = 33 TEXT columns) with
PK = (OrderId, RouteId, FillId). INSERT OR REPLACE handles late corrections from
Bloomberg. Tracks fetch history in a separate fetch_log table.

Schema migration:
    _migrate_raw_fills_table() is called during _init_db() to handle old DB
    files that were created without the 5 derived columns added by the cleaner
    layer (order_as_of_date, order_as_of_time, exchange_exec_time,
    route_as_of_time, local_fill_datetime). Uses ALTER TABLE ADD COLUMN
    which is safe in SQLite.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import date, datetime
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
from .schema import ALL_RAW_COLUMNS, EMSX_FILL_COLUMNS, RAW_METADATA_COLUMNS

logger = logging.getLogger(__name__)


class RawFillsDB:
    """SQLite storage for EMSX fill data (raw + fetch tracking)."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        access_tier: Optional[AccessTier] = None,
    ):
        self.db_path = Path(db_path or Config.RAW_FILLS_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._access_tier = resolve_access_tier(access_tier)
        # Init always needs full access (CREATE TABLE etc.)
        self._init_db()

    def _get_conn(self) -> AccessControlledConnection:
        """Return an access-controlled SQLite connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return AccessControlledConnection(conn, self._access_tier)

    def _get_admin_conn(self) -> sqlite3.Connection:
        """Return a raw connection for schema init/migration (always admin)."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist, then migrate existing tables."""
        conn = self._get_admin_conn()
        try:
            # ── raw_fills: store all EMSX fill columns + metadata ──
            # All values stored as TEXT for simplicity. Numerics are cast on read.
            # PK = (OrderId, RouteId, FillId). Each fill correction from Bloomberg
            # arrives as a separate record with the same OrderId+FillId but different
            # RouteId and/or field values. Triple-key preserves ALL versions.
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.RAW_FILLS_TABLE} (
                    -- 28 EMSX original columns (TEXT)
                    OrderId               TEXT NOT NULL,
                    Account               TEXT,
                    SecurityName          TEXT,
                    Ticker                TEXT,
                    Exchange              TEXT,
                    Currency              TEXT,
                    Side                  TEXT,
                    Amount                TEXT,
                    NyOrderCreateAsOfDateTime TEXT,
                    Type                  TEXT,
                    LimitPrice            TEXT,
                    Broker                TEXT,
                    StopPrice             TEXT,
                    StrategyType          TEXT,
                    TraderName            TEXT,
                    TraderUuid            TEXT,
                    RouteId               TEXT NOT NULL,
                    NyTranCreateAsOfDateTime TEXT,
                    RouteShares           TEXT,
                    FillId                TEXT NOT NULL,
                    ExecType              TEXT,
                    DateTimeOfFill        TEXT,
                    FillPrice             TEXT,
                    FillShares            TEXT,
                    LastCapacity          TEXT,
                    LastMarket            TEXT,
                    Liquidity             TEXT,
                    LocalExchangeSymbol   TEXT,
                    -- Metadata columns
                    source_date           TEXT NOT NULL DEFAULT '',
                    fetched_at            TEXT DEFAULT (datetime('now')),
                    ingested_at           TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (OrderId, RouteId, FillId)
                )
            """)

            # Schema migration: ensure all expected columns exist + PK upgrade
            self._migrate_raw_fills_table(conn)

            # Indexes for common query patterns
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_raw_source_date
                ON {Config.RAW_FILLS_TABLE} (source_date)
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_raw_order_date
                ON {Config.RAW_FILLS_TABLE} (order_as_of_date)
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_raw_ticker
                ON {Config.RAW_FILLS_TABLE} (Ticker)
            """)

            # ── fetch_log: unified fetch tracking (replaces ingestion_log) ──
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.FETCH_LOG_TABLE} (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_date           TEXT NOT NULL,
                    fetch_timestamp       TEXT DEFAULT (datetime('now')),
                    row_count             INTEGER NOT NULL,
                    data_hash             TEXT NOT NULL,
                    file_path             TEXT,
                    status                TEXT DEFAULT 'fetched',
                    UNIQUE(source_date, data_hash)
                )
            """)

            # ── ingestion_log: legacy, kept for backward compatibility ──
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.INGESTION_LOG_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_date TEXT NOT NULL,
                    source_file TEXT,
                    ingestion_timestamp TEXT DEFAULT (datetime('now')),
                    row_count INTEGER,
                    new_row_count INTEGER,
                    hash_value TEXT,
                    UNIQUE(source_date, hash_value)
                )
            """)

            # ── order_fetch_log: per-order fetch tracking (Phase 2B) ──
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.ORDER_FETCH_LOG_TABLE} (
                    order_id              TEXT NOT NULL,
                    source_date           TEXT NOT NULL,
                    fetch_timestamp       TEXT DEFAULT (datetime('now')),
                    row_count             INTEGER NOT NULL,
                    data_hash             TEXT NOT NULL,
                    PRIMARY KEY (order_id, source_date)
                )
            """)

            conn.commit()
            logger.debug(f"Raw fills DB initialized at {self.db_path}")
        finally:
            conn.close()

    def _migrate_raw_fills_table(self, conn: sqlite3.Connection) -> None:
        """Migrate existing raw_fills table to match current schema.

        Handles:
            1. Old DB missing derived columns (ADD COLUMN)
            2. PK upgrade: (OrderId, FillId) -> (OrderId, RouteId, FillId)
               This is needed because Bloomberg sends fill corrections as
               separate records with the same (OrderId,FillId) but different
               RouteId/field values. The old PK caused data loss via INSERT OR REPLACE.
        """
        # Get actual columns in the table
        cursor = conn.execute(f"PRAGMA table_info({Config.RAW_FILLS_TABLE})")
        col_info = cursor.fetchall()
        existing_cols = {row[1] for row in col_info}

        # ── Check if PK needs upgrading ──────────────────────────────
        # SQLite stores pk info in column index 5 of PRAGMA table_info.
        # New PK = columns with pk>0: OrderId(pk=1), RouteId(pk=2), FillId(pk=3)
        pk_columns = [row[1] for row in col_info if row[5] > 0]
        old_pk = set(pk_columns) == {"OrderId", "FillId"}
        new_pk = set(pk_columns) == {"OrderId", "RouteId", "FillId"}

        if old_pk and not new_pk:
            logger.info("PK Migration: upgrading (OrderId, FillId) -> "
                        "(OrderId, RouteId, FillId)")
            self._upgrade_pk_to_triple(conn)

            # Refresh column info after recreation
            cursor = conn.execute(f"PRAGMA table_info({Config.RAW_FILLS_TABLE})")
            col_info = cursor.fetchall()
            existing_cols = {row[1] for row in col_info}

        # Derived columns added by fill_cleaner (may not exist in old tables)
        derived_cols = {
            "order_as_of_date":     "TEXT DEFAULT ''",
            "order_as_of_time":     "TEXT DEFAULT ''",
            "exchange_exec_time":   "TEXT DEFAULT ''",
            "route_as_of_time":     "TEXT DEFAULT ''",
            "local_fill_datetime":  "TEXT DEFAULT ''",
        }

        migrated = False
        for col_name, col_type in derived_cols.items():
            if col_name not in existing_cols:
                try:
                    conn.execute(
                        f"ALTER TABLE {Config.RAW_FILLS_TABLE} "
                        f"ADD COLUMN [{col_name}] {col_type}"
                    )
                    logger.info(f"Migration: added column [{col_name}] to raw_fills")
                    migrated = True
                except sqlite3.OperationalError as e:
                    logger.warning(f"Failed to add [{col_name}]: {e}")

        if migrated:
            conn.commit()

    def _upgrade_pk_to_triple(self, conn: sqlite3.Connection) -> None:
        """Recreate raw_fills table with new triple-column PK.

        Since SQLite doesn't support ALTER TABLE on PRIMARY KEY, we must:
            1. Create new table with correct PK
            2. Copy data from old to new (INSERT OR IGNORE)
            3. Drop old table, rename new
        """
        old_table = Config.RAW_FILLS_TABLE
        new_table = f"{old_table}_new"

        logger.info("Rebuilding raw_fills table with PK=(OrderId,RouteId,FillId)")

        try:
            # Build new schema dynamically but safely: use only col names/types,
            # strip all inline constraints (PK, defaults) to avoid parse issues.
            old_cols = conn.execute(f"PRAGMA table_info({old_table})").fetchall()
            
            # Collect column names in order
            col_names_list = [f"[{c[1]}]" for c in old_cols]
            col_names_str = ", ".join(col_names_list)

            # Build clean column definitions: name + type + NOT NULL only.
            # No defaults, no inline PK — keep it simple.
            col_defs = []
            for c in old_cols:
                name = c[1]
                ctype = c[2] or "TEXT"
                notnull = ""
                if c[3] or name in ("OrderId", "RouteId", "FillId", "source_date"):
                    notnull = " NOT NULL"
                col_defs.append(f"  {name} {ctype}{notnull}")

            create_sql = (
                f"CREATE TABLE IF NOT EXISTS {new_table} (\n"
                + ",\n".join(col_defs)
                + "\n,\n  PRIMARY KEY (OrderId, RouteId, FillId)\n)"
            )
            conn.execute(create_sql)

            row_count = conn.execute(
                f"INSERT OR IGNORE INTO {new_table} SELECT {col_names_str} FROM {old_table}"
            ).rowcount
            logger.info(f"Copied {row_count} rows to new table")

            conn.execute(f"DROP TABLE {old_table}")
            conn.execute(f"ALTER TABLE {new_table} RENAME TO {old_table}")
            conn.commit()
            logger.info("PK migration complete")

        except Exception as e:
            logger.error(f"PK migration failed: {e}")
            raise

    # ═══════════════════════════════════════════════════════════════════════
    # RAW API DATA UPSERT (new: direct from Bloomberg API output)
    # ═══════════════════════════════════════════════════════════════════════

    def upsert_raw_api_data(
        self, fills: List[Dict[str, Any]], source_date: str
    ) -> int:
        """Insert Bloomberg API raw data directly into raw_fills table.

        Does NOT call clean_emsx_fills() — stores API output as-is.
        Only writes 28 EMSX columns + source_date + fetched_at metadata.

        Args:
            fills: BloombergFillFetcher output (List[Dict] with EMSX keys).
            source_date: API call target date YYYYMMDD.

        Returns:
            Number of rows upserted.
        """
        if not fills:
            return 0

        conn = self._get_conn()
        try:
            cols = list(EMSX_FILL_COLUMNS) + ["source_date", "fetched_at"]
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)

            sql = f"""
                INSERT OR REPLACE INTO {Config.RAW_FILLS_TABLE}
                ({col_names}) VALUES ({placeholders})
            """

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

            logger.info(
                f"Upserted {len(rows)} raw API rows (source_date={source_date})"
            )
            return len(rows)
        finally:
            conn.close()

    def upsert_raw_api_data_batch(
        self, batch_items: List[Tuple[List[Dict[str, Any]], str]]
    ) -> int:
        """Insert multiple days of Bloomberg API data in a single transaction.

        [OPT-5] Batch write optimization — reduces commit overhead for parallel
        or batched fetches where multiple days are written at once.

        Args:
            batch_items: List of (fills, source_date) tuples.

        Returns:
            Total number of rows upserted across all dates.
        """
        if not batch_items:
            return 0

        conn = self._get_conn()
        try:
            cols = list(EMSX_FILL_COLUMNS) + ["source_date", "fetched_at"]
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)

            sql = f"""
                INSERT OR REPLACE INTO {Config.RAW_FILLS_TABLE}
                ({col_names}) VALUES ({placeholders})
            """

            now = datetime.now().isoformat()
            total_rows = 0
            rows_batch = []
            for fills, source_date in batch_items:
                if not fills:
                    continue
                for f in fills:
                    row = []
                    for col in EMSX_FILL_COLUMNS:
                        val = f.get(col)
                        row.append(None if val is None else str(val))
                    row.append(source_date)
                    row.append(now)
                    rows_batch.append(tuple(row))
                total_rows += len(fills)

            conn.executemany(sql, rows_batch)
            conn.commit()

            logger.info(
                f"Batch-upserted {total_rows} raw API rows "
                f"({len(batch_items)} dates, single transaction)"
            )
            return total_rows
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════════════
    # CLEANED DATA UPSERT (legacy: from fill_ingestion/clean_emsx_fills)
    # ═══════════════════════════════════════════════════════════════════════

    def upsert_fills(self, df: pd.DataFrame) -> int:
        """Insert or replace cleaned fill records. Returns count of new rows.

        Uses INSERT OR REPLACE on (OrderId, RouteId, FillId) primary key.
        """
        if df.empty:
            return 0

        conn = self._get_conn()
        try:
            existing_keys = self._get_existing_keys(conn)

            all_columns = ALL_RAW_COLUMNS + ["source_date", "ingested_at"]
            insert_columns = [c for c in all_columns if c in df.columns]

            placeholders = ", ".join(["?"] * len(insert_columns))
            col_names = ", ".join(insert_columns)

            sql = f"""
                INSERT OR REPLACE INTO {Config.RAW_FILLS_TABLE}
                ({col_names}) VALUES ({placeholders})
            """

            rows = []
            for _, row in df.iterrows():
                values = []
                for col in insert_columns:
                    val = row.get(col)
                    if pd.isna(val) or val is None:
                        values.append(None)
                    else:
                        values.append(str(val))
                rows.append(tuple(values))

            conn.executemany(sql, rows)
            conn.commit()

            new_keys = set()
            for _, row in df.iterrows():
                key = (
                    str(row.get("OrderId", "")),
                    str(row.get("RouteId", "")),
                    str(row.get("FillId", "")),
                )
                if key not in existing_keys:
                    new_keys.add(key)

            new_count = len(new_keys)
            logger.info(
                f"Upserted {len(rows)} fills into raw_fills "
                f"({new_count} new, {len(rows) - new_count} updated)"
            )
            return new_count
        finally:
            conn.close()

    def _get_existing_keys(self, conn: sqlite3.Connection) -> Set[tuple]:
        """Get all existing (OrderId, RouteId, FillId) triples."""
        cursor = conn.execute(
            f"SELECT OrderId, RouteId, FillId FROM {Config.RAW_FILLS_TABLE}"
        )
        return {(str(r[0]), str(r[1]), str(r[2])) for r in cursor.fetchall()}

    # ═══════════════════════════════════════════════════════════════════════
    # QUERY INTERFACE
    # ═══════════════════════════════════════════════════════════════════════

    def get_fills_for_source_date(self, date_str: str) -> pd.DataFrame:
        """Get all fills for a given source_date (YYYYMMDD format)."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.RAW_FILLS_TABLE} WHERE source_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """Get all fills for a given order_as_of_date (YYYYMMDD format).

        Falls back to source_date if order_as_of_date column is empty.
        """
        conn = self._get_conn()
        try:
            # Try order_as_of_date first (cleaned data)
            df = pd.read_sql_query(
                f"SELECT * FROM {Config.RAW_FILLS_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
            if not df.empty:
                return df
            # Fallback to source_date (raw API data)
            return pd.read_sql_query(
                f"SELECT * FROM {Config.RAW_FILLS_TABLE} WHERE source_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_fills_for_date_range(self, start: str, end: str) -> pd.DataFrame:
        """Get fills for a date range (inclusive, YYYYMMDD format).

        Queries both order_as_of_date and source_date to cover all data.
        """
        conn = self._get_conn()
        try:
            df = pd.read_sql_query(
                f"""SELECT DISTINCT * FROM {Config.RAW_FILLS_TABLE}
                    WHERE (order_as_of_date >= ? AND order_as_of_date <= ?)
                       OR (source_date >= ? AND source_date <= ?)
                    ORDER BY source_date, DateTimeOfFill""",
                conn,
                params=[start, end, start, end],
            )
            return df
        finally:
            conn.close()

    def get_all_source_dates(self) -> List[str]:
        """Get all distinct source_date values."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT DISTINCT source_date
                    FROM {Config.RAW_FILLS_TABLE}
                    WHERE source_date IS NOT NULL AND source_date != ''
                    ORDER BY source_date"""
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_all_dates(self) -> List[str]:
        """Get all distinct date values (order_as_of_date preferred)."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT DISTINCT COALESCE(
                        NULLIF(order_as_of_date, ''), source_date
                    ) AS date_val
                    FROM {Config.RAW_FILLS_TABLE}
                    WHERE date_val IS NOT NULL AND date_val != ''
                    ORDER BY date_val"""
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_row_count(self) -> int:
        """Total number of rows in raw_fills."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {Config.RAW_FILLS_TABLE}")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_date_row_counts(self) -> Dict[str, int]:
        """Get row counts grouped by source_date."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT source_date, COUNT(*)
                    FROM {Config.RAW_FILLS_TABLE}
                    WHERE source_date IS NOT NULL AND source_date != ''
                    GROUP BY source_date
                    ORDER BY source_date"""
            )
            return {r[0]: r[1] for r in cursor.fetchall()}
        finally:
            conn.close()

    def has_updates_since(self, source_date: str, since_timestamp: str) -> bool:
        """Check if raw_fills for a date have been re-fetched after a timestamp.

        Used for late correction detection.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT 1 FROM {Config.RAW_FILLS_TABLE}
                    WHERE source_date = ? AND fetched_at > ?
                    LIMIT 1""",
                (source_date, since_timestamp),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════════════
    # FETCH LOG (new: unified dedup + audit)
    # ═══════════════════════════════════════════════════════════════════════

    def add_fetch_log_record(
        self,
        source_date: str,
        row_count: int,
        data_hash: str,
        file_path: Optional[str] = None,
    ) -> None:
        """Record a successful fetch event in fetch_log."""
        conn = self._get_conn()
        try:
            conn.execute(
                f"""INSERT OR IGNORE INTO {Config.FETCH_LOG_TABLE}
                    (source_date, fetch_timestamp, row_count, data_hash, file_path, status)
                    VALUES (?, ?, ?, ?, ?, 'fetched')""",
                (source_date, datetime.now().isoformat(), row_count, data_hash, file_path),
            )
            conn.commit()
        finally:
            conn.close()

    def check_fetch_duplicate(self, source_date: str, data_hash: str) -> bool:
        """Check if (source_date, data_hash) already exists in fetch_log."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT 1 FROM {Config.FETCH_LOG_TABLE}
                    WHERE source_date = ? AND data_hash = ? LIMIT 1""",
                (source_date, data_hash),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def upsert_order_fetch_log(
        self,
        fills: List[Dict[str, Any]],
        source_date: str,
    ) -> int:
        """Compute per-order hashes and upsert to order_fetch_log.

        Groups fills by OrderId, computes SHA-256 for each order's fills,
        and upserts to the order_fetch_log table for order-level tracking.

        Returns:
            Number of order-level records upserted.
        """
        if not fills:
            return 0

        from collections import defaultdict

        orders: dict = defaultdict(list)
        for f in fills:
            oid = f.get("OrderId")
            if oid:
                orders[str(oid)].append(f)

        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            rows = []
            for order_id, order_fills in orders.items():
                order_hash = compute_fills_hash(order_fills)
                rows.append((
                    order_id,
                    source_date,
                    now,
                    len(order_fills),
                    order_hash,
                ))

            conn.executemany(
                f"""INSERT OR REPLACE INTO {Config.ORDER_FETCH_LOG_TABLE}
                    (order_id, source_date, fetch_timestamp, row_count, data_hash)
                    VALUES (?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()
            logger.debug(
                f"Upserted {len(rows)} order_fetch_log records "
                f"(source_date={source_date})"
            )
            return len(rows)
        finally:
            conn.close()

    def get_order_fetch_log(
        self,
        source_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get order-level fetch log entries."""
        conn = self._get_conn()
        try:
            if source_date:
                cursor = conn.execute(
                    f"""SELECT order_id, source_date, fetch_timestamp,
                               row_count, data_hash
                        FROM {Config.ORDER_FETCH_LOG_TABLE}
                        WHERE source_date = ?
                        ORDER BY order_id
                        LIMIT ?""",
                    (source_date, limit),
                )
            else:
                cursor = conn.execute(
                    f"""SELECT order_id, source_date, fetch_timestamp,
                               row_count, data_hash
                        FROM {Config.ORDER_FETCH_LOG_TABLE}
                        ORDER BY fetch_timestamp DESC
                        LIMIT ?""",
                    (limit,),
                )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_last_fetch_date(self) -> Optional[date]:
        """Return the last successful fetch date from fetch_log."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT MAX(source_date) FROM {Config.FETCH_LOG_TABLE}
                    WHERE status = 'fetched'"""
            )
            row = cursor.fetchone()
            if row and row[0]:
                return datetime.strptime(row[0], "%Y%m%d").date()
            return None
        finally:
            conn.close()

    def get_fetch_log_stats(self) -> List[Dict[str, Any]]:
        """Get fetch_log summary."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT source_date, fetch_timestamp, row_count,
                           data_hash, file_path, status
                    FROM {Config.FETCH_LOG_TABLE}
                    ORDER BY fetch_timestamp DESC"""
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════════════
    # INGESTION LOG (legacy, kept for backward compatibility)
    # ═══════════════════════════════════════════════════════════════════════

    def add_ingestion_record(
        self,
        source_date: str,
        row_count: int,
        new_row_count: int,
        hash_value: str,
        source_file: Optional[str] = None,
    ) -> None:
        """Record an ingestion event (legacy)."""
        conn = self._get_conn()
        try:
            conn.execute(
                f"""INSERT OR IGNORE INTO {Config.INGESTION_LOG_TABLE}
                    (source_date, source_file, row_count, new_row_count, hash_value)
                    VALUES (?, ?, ?, ?, ?)""",
                (source_date, source_file, row_count, new_row_count, hash_value),
            )
            conn.commit()
        finally:
            conn.close()

    def check_ingestion_duplicate(self, source_date: str, hash_value: str) -> bool:
        """Check if (date, hash) was already ingested (legacy)."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT 1 FROM {Config.INGESTION_LOG_TABLE}
                    WHERE source_date = ? AND hash_value = ? LIMIT 1""",
                (source_date, hash_value),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def get_ingested_dates(self) -> List[str]:
        """Get all dates that have been ingested (legacy)."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT DISTINCT source_date
                    FROM {Config.INGESTION_LOG_TABLE}
                    ORDER BY source_date"""
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_ingestion_stats(self) -> List[Dict[str, Any]]:
        """Get ingestion log summary (legacy)."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT source_date, source_file, ingestion_timestamp,
                           row_count, new_row_count, hash_value
                    FROM {Config.INGESTION_LOG_TABLE}
                    ORDER BY ingestion_timestamp DESC"""
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()


def compute_fills_hash(fills: List[Dict[str, Any]]) -> str:
    """Compute SHA-256 hash of fill data for duplicate detection."""
    serialized = json.dumps(fills, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

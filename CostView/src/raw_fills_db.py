"""
Raw Fills SQLite Database.

Stores cleaned EMSX fill data and tracks ingestion status.
Provides incremental upsert (INSERT OR REPLACE on OrderId+FillId)
and date-based querying.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd

from .processing_config import ProcessingConfig as Config
from .schema import DERIVED_COLUMNS, EMSX_DEDUP_KEY, EMSX_FILL_COLUMNS

logger = logging.getLogger(__name__)


class RawFillsDB:
    """SQLite storage for cleaned EMSX fill data."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or Config.RAW_FILLS_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        try:
            # raw_fills: store all EMSX fill columns + derived columns
            # Use TEXT for all columns to avoid schema migration issues
            # when new EMSX columns appear. Numerics are stored as text
            # and cast on read.
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.RAW_FILLS_TABLE} (
                    OrderId TEXT NOT NULL,
                    FillId TEXT NOT NULL,
                    Account TEXT,
                    SecurityName TEXT,
                    Ticker TEXT,
                    Exchange TEXT,
                    Currency TEXT,
                    Side TEXT,
                    Amount TEXT,
                    NyOrderCreateAsOfDateTime TEXT,
                    OrderInstruction TEXT,
                    IsLeg TEXT,
                    Type TEXT,
                    LimitPrice TEXT,
                    Broker TEXT,
                    StopPrice TEXT,
                    StrategyType TEXT,
                    TraderName TEXT,
                    TraderUuid TEXT,
                    RouteId TEXT,
                    NyTranCreateAsOfDateTime TEXT,
                    RouteShares TEXT,
                    RouteExecutionInstruction TEXT,
                    RouteHandlingInstruction TEXT,
                    RouteNotes TEXT,
                    ExecType TEXT,
                    DateTimeOfFill TEXT,
                    FillPrice TEXT,
                    FillShares TEXT,
                    LastCapacity TEXT,
                    LastMarket TEXT,
                    Liquidity TEXT,
                    LocalExchangeSymbol TEXT,
                    -- Derived columns
                    order_as_of_date TEXT,
                    order_as_of_time TEXT,
                    exec_date TEXT,
                    exec_time TEXT,
                    exchange_exec_time TEXT,
                    route_as_of_time TEXT,
                    local_fill_datetime TEXT,
                    -- Metadata
                    ingested_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (OrderId, FillId)
                )
            """)

            # Indexes for common query patterns
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_raw_fills_order_date
                ON {Config.RAW_FILLS_TABLE} (order_as_of_date)
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_raw_fills_exec_date
                ON {Config.RAW_FILLS_TABLE} (exec_date)
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_raw_fills_ticker
                ON {Config.RAW_FILLS_TABLE} (Ticker)
            """)

            # ingestion_log: track which Excel files / fetch dates have been ingested
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

            conn.commit()
            logger.debug(f"Raw fills DB initialized at {self.db_path}")
        finally:
            conn.close()

    def upsert_fills(self, df: pd.DataFrame) -> int:
        """Insert or replace fill records. Returns count of new rows inserted.

        Uses INSERT OR REPLACE on (OrderId, FillId) primary key.
        """
        if df.empty:
            return 0

        conn = self._get_conn()
        try:
            # Get existing keys for counting new rows
            existing_keys = self._get_existing_keys(conn)

            # Determine columns to insert (intersection of df columns and table columns)
            all_columns = EMSX_FILL_COLUMNS + DERIVED_COLUMNS
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
                    # Convert to string for SQLite TEXT storage
                    if pd.isna(val) or val is None:
                        values.append(None)
                    else:
                        values.append(str(val))
                rows.append(tuple(values))

            conn.executemany(sql, rows)
            conn.commit()

            # Count truly new rows
            new_keys = set()
            for _, row in df.iterrows():
                key = (str(row.get("OrderId", "")), str(row.get("FillId", "")))
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
        """Get all existing (OrderId, FillId) pairs."""
        cursor = conn.execute(
            f"SELECT OrderId, FillId FROM {Config.RAW_FILLS_TABLE}"
        )
        return {(str(r[0]), str(r[1])) for r in cursor.fetchall()}

    def get_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """Get all fills for a given order_as_of_date (YYYYMMDD format)."""
        conn = self._get_conn()
        try:
            df = pd.read_sql_query(
                f"SELECT * FROM {Config.RAW_FILLS_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
            return df
        finally:
            conn.close()

    def get_fills_for_date_range(self, start: str, end: str) -> pd.DataFrame:
        """Get fills for a date range (inclusive, YYYYMMDD format)."""
        conn = self._get_conn()
        try:
            df = pd.read_sql_query(
                f"""SELECT * FROM {Config.RAW_FILLS_TABLE}
                    WHERE order_as_of_date >= ? AND order_as_of_date <= ?
                    ORDER BY order_as_of_date, exec_time""",
                conn,
                params=[start, end],
            )
            return df
        finally:
            conn.close()

    def get_all_dates(self) -> List[str]:
        """Get all distinct order_as_of_date values."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT DISTINCT order_as_of_date
                    FROM {Config.RAW_FILLS_TABLE}
                    WHERE order_as_of_date IS NOT NULL AND order_as_of_date != ''
                    ORDER BY order_as_of_date"""
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
        """Get row counts grouped by order_as_of_date."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT order_as_of_date, COUNT(*)
                    FROM {Config.RAW_FILLS_TABLE}
                    WHERE order_as_of_date IS NOT NULL AND order_as_of_date != ''
                    GROUP BY order_as_of_date
                    ORDER BY order_as_of_date"""
            )
            return {r[0]: r[1] for r in cursor.fetchall()}
        finally:
            conn.close()

    # ── Ingestion log ───────────────────────────────────────────────────────

    def add_ingestion_record(
        self,
        source_date: str,
        row_count: int,
        new_row_count: int,
        hash_value: str,
        source_file: Optional[str] = None,
    ) -> None:
        """Record an ingestion event."""
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
        """Check if this (date, hash) combination was already ingested."""
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
        """Get all dates that have been ingested."""
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
        """Get ingestion log summary."""
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

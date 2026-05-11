"""
FillFetch Database Module
Manages SQL table to track fetch history with hash-based deduplication.

INTERNALS MIGRATED (Iteration 5): SQLAlchemy replaced with
ConnectionManager + native sqlite3. The public API is unchanged.
"""

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from DataPipeline.src.storage.connection import (
    ConnectionManager,
    AccessTier,
    DB_FETCH_HISTORY,
)

logger = logging.getLogger(__name__)

_FETCH_HISTORY_TABLE = "fill_fetch_history"


class FillFetchDatabase:
    """Database manager for FillFetch operations.

    Internally uses ConnectionManager for connection lifecycle.
    SQLAlchemy implementation removed in Iteration 5.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path: Optional[Path] = None
        if db_path is not None:
            self._db_path = Path(db_path).resolve()
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._mgr = ConnectionManager(
                path_overrides={DB_FETCH_HISTORY: self._db_path}
            )
        else:
            self._mgr = ConnectionManager()
            self._db_path = self._mgr.get_path(DB_FETCH_HISTORY)
        self._table = _FETCH_HISTORY_TABLE
        self._init_table()
        logger.info(f"Database initialized at: {self._db_path}")

    def _get_write_conn(self) -> sqlite3.Connection:
        """Get a WRITE access connection."""
        return self._mgr.get_connection(DB_FETCH_HISTORY, AccessTier.WRITE).raw_connection

    def _get_read_conn(self) -> sqlite3.Connection:
        """Get a READ access connection."""
        return self._mgr.get_connection(DB_FETCH_HISTORY, AccessTier.READ).raw_connection

    def _init_table(self) -> None:
        conn = self._mgr.get_admin_connection(DB_FETCH_HISTORY)
        try:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_date TEXT NOT NULL,
                    fetch_time TEXT NOT NULL,
                    import_timestamp TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    hash_value TEXT NOT NULL,
                    file_path TEXT,
                    UNIQUE(order_date, hash_value)
                )
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self._table}_date
                ON {self._table}(order_date)
            """)
            conn.commit()
        finally:
            conn.close()

    def check_duplicate(self, order_date: str, hash_value: str) -> bool:
        """Check if a fetch record with same date and hash exists."""
        conn = self._get_read_conn()
        try:
            cur = conn.execute(
                f"SELECT 1 FROM {self._table} WHERE order_date=? AND hash_value=?",
                (order_date, hash_value),
            )
            exists = cur.fetchone() is not None
            if exists:
                logger.info(f"Duplicate found for {order_date} with hash {hash_value[:16]}...")
            return exists
        finally:
            conn.close()

    def add_fetch_record(
        self, order_date: str, fetch_time: str, row_count: int,
        hash_value: str, file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a new fetch record to the database. Returns metadata dict."""
        conn = self._get_write_conn()
        try:
            conn.execute(
                f"INSERT OR IGNORE INTO {self._table} "
                "(order_date, fetch_time, import_timestamp, row_count, hash_value, file_path) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    order_date, fetch_time,
                    datetime.now(timezone.utc).isoformat(),
                    row_count, hash_value, file_path,
                ),
            )
            conn.commit()
            logger.info(f"Added fetch record for {order_date}: {row_count} rows")
            return {
                "order_date": order_date,
                "row_count": row_count,
                "hash_value": hash_value,
            }
        finally:
            conn.close()

    def get_fetch_history(
        self, order_date: Optional[str] = None, limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get fetch history records as dicts."""
        conn = self._get_read_conn()
        try:
            if order_date:
                cur = conn.execute(
                    f"SELECT * FROM {self._table} WHERE order_date=? "
                    f"ORDER BY import_timestamp DESC LIMIT ?",
                    (order_date, limit),
                )
            else:
                cur = conn.execute(
                    f"SELECT * FROM {self._table} "
                    f"ORDER BY import_timestamp DESC LIMIT ?",
                    (limit,),
                )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
        finally:
            conn.close()

    def get_latest_fetch(self, order_date: str) -> Optional[Dict[str, Any]]:
        """Get the most recent fetch record for a specific date."""
        conn = self._get_read_conn()
        try:
            cur = conn.execute(
                f"SELECT * FROM {self._table} WHERE order_date=? "
                f"ORDER BY import_timestamp DESC LIMIT 1",
                (order_date,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in cur.description]
            return dict(zip(columns, row))
        finally:
            conn.close()

    def delete_records_for_date(self, order_date: str) -> int:
        """Delete all fetch records for a specific date. Returns count deleted."""
        conn = self._get_write_conn()
        try:
            cur = conn.execute(
                f"DELETE FROM {self._table} WHERE order_date=?", (order_date,),
            )
            conn.commit()
            count = cur.rowcount
            if count:
                logger.info(f"Deleted {count} existing record(s) for {order_date}")
            return count
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        conn = self._get_read_conn()
        try:
            total_records = conn.execute(
                f"SELECT COUNT(*) FROM {self._table}"
            ).fetchone()[0]
            total_rows = conn.execute(
                f"SELECT COALESCE(SUM(row_count), 0) FROM {self._table}"
            ).fetchone()[0]
            unique_dates = conn.execute(
                f"SELECT COUNT(DISTINCT order_date) FROM {self._table}"
            ).fetchone()[0]
            latest = conn.execute(
                f"SELECT import_timestamp FROM {self._table} "
                f"ORDER BY import_timestamp DESC LIMIT 1"
            ).fetchone()
            return {
                "total_records": total_records,
                "total_rows_fetched": total_rows,
                "unique_dates": unique_dates,
                "latest_fetch": latest[0] if latest else None,
                "database_path": str(self._db_path),
            }
        finally:
            conn.close()

    def close(self) -> None:
        """No-op: ConnectionManager connections are short-lived and auto-closed."""
        logger.info("Database connection closed (no-op — ConnectionManager manages lifecycle)")


def compute_data_hash(data: List[Dict[str, Any]]) -> str:
    """Compute SHA-256 hash of data for deduplication."""
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

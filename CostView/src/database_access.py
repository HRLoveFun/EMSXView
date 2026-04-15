"""
Database Access Manager — application-level permission tiering for SQLite.

Three access tiers:
    READ  — SELECT only (query/status commands)
    WRITE — SELECT + INSERT/UPDATE (fetch, pipeline processing)
    ADMIN — All operations including DELETE/DROP/ALTER (rebuild, purge)

Usage:
    conn = AccessControlledConnection(raw_conn, tier=AccessTier.WRITE)
    conn.execute("INSERT ...")   # OK
    conn.execute("DELETE ...")   # raises PermissionError

The tier is determined (in priority order) by:
    1. Explicit parameter passed to DB constructor
    2. Environment variable COSTVIEW_DB_ACCESS
    3. Default (WRITE for pipeline commands, READ for query/status)
"""

from __future__ import annotations

import enum
import logging
import os
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


class AccessTier(enum.Enum):
    """Database access permission levels."""
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


# SQL statement classification patterns (case-insensitive)
_WRITE_PATTERN = re.compile(
    r"^\s*(INSERT|UPDATE|REPLACE|UPSERT)\b", re.IGNORECASE
)
_DESTRUCTIVE_PATTERN = re.compile(
    r"^\s*(DELETE|DROP|ALTER)\b", re.IGNORECASE
)
_PRAGMA_WRITE_PATTERN = re.compile(
    r"^\s*PRAGMA\s+(journal_mode|foreign_keys|wal_checkpoint)\b", re.IGNORECASE
)
_CREATE_PATTERN = re.compile(
    r"^\s*CREATE\b", re.IGNORECASE
)

# Allowed PRAGMAs at all tiers (they configure the connection, not data)
_PRAGMA_SAFE = re.compile(
    r"^\s*PRAGMA\s+(journal_mode|foreign_keys|table_info|index_list)\b",
    re.IGNORECASE,
)


def _classify_sql(sql: str) -> str:
    """Classify a SQL statement into an operation category.

    Returns one of: 'read', 'write', 'destructive', 'create', 'pragma_safe', 'pragma_write'.
    """
    stripped = sql.strip()
    if _PRAGMA_SAFE.match(stripped):
        return "pragma_safe"
    if _PRAGMA_WRITE_PATTERN.match(stripped):
        return "pragma_write"
    if _DESTRUCTIVE_PATTERN.match(stripped):
        return "destructive"
    if _WRITE_PATTERN.match(stripped):
        return "write"
    if _CREATE_PATTERN.match(stripped):
        return "create"
    return "read"


def _check_permission(tier: AccessTier, sql_category: str, sql: str) -> None:
    """Raise PermissionError if the operation is not allowed for the given tier."""
    if sql_category == "pragma_safe":
        return  # always allowed (connection config)

    if tier == AccessTier.READ:
        if sql_category != "read":
            raise PermissionError(
                f"READ-only access: '{sql_category}' operation denied. "
                f"SQL: {sql[:120]}..."
            )
    elif tier == AccessTier.WRITE:
        if sql_category == "destructive":
            raise PermissionError(
                f"WRITE access: destructive '{sql_category}' operation denied. "
                f"Use ADMIN tier or --db-access admin. SQL: {sql[:120]}..."
            )
    # ADMIN: everything allowed


class AccessControlledConnection:
    """Wraps a sqlite3.Connection to enforce access tier permissions.

    Delegates all attribute access to the underlying connection, but intercepts
    execute() and executemany() to check permissions before forwarding.
    """

    def __init__(self, conn: sqlite3.Connection, tier: AccessTier):
        self._conn = conn
        self._tier = tier

    @property
    def tier(self) -> AccessTier:
        return self._tier

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        category = _classify_sql(sql)
        _check_permission(self._tier, category, sql)
        if category == "destructive":
            logger.warning(f"ADMIN destructive operation: {sql[:200]}")
        return self._conn.execute(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters: Iterable) -> sqlite3.Cursor:
        category = _classify_sql(sql)
        _check_permission(self._tier, category, sql)
        return self._conn.executemany(sql, seq_of_parameters)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._conn.close()
        return False

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attribute access to the underlying connection."""
        return getattr(self._conn, name)


def resolve_access_tier(
    explicit: Optional[AccessTier] = None,
) -> AccessTier:
    """Resolve the effective access tier from explicit param or environment.

    Priority:
        1. Explicit parameter (from CLI --db-access flag)
        2. COSTVIEW_DB_ACCESS environment variable
        3. Default: WRITE
    """
    if explicit is not None:
        return explicit

    env_val = os.environ.get("COSTVIEW_DB_ACCESS", "").lower().strip()
    if env_val in ("read", "write", "admin"):
        return AccessTier(env_val)

    return AccessTier.WRITE


def backup_database(db_path: Path) -> Path:
    """Create a timestamped backup of a database file before destructive ops.

    Returns the path to the backup file.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_suffix(f".{timestamp}.bak")
    shutil.copy2(str(db_path), str(backup_path))
    logger.info(f"Database backup created: {backup_path}")
    return backup_path

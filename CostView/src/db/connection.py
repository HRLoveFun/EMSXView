"""Unified database connection management for CostView.

Migrated from database_access.py with the addition of ConnectionManager,
which provides centralized connection lifecycle management for all six
CostView SQLite databases.

Three access tiers:
    READ  — SELECT only (query/status commands)
    WRITE — SELECT + INSERT/UPDATE (fetch, pipeline processing)
    ADMIN — All operations including DELETE/DROP/ALTER (rebuild, purge)

Usage:
    from CostView.src.db.connection import ConnectionManager, AccessTier

    mgr = ConnectionManager()
    conn = mgr.get_connection("raw_fills", AccessTier.READ)
    # ... use conn ...
    conn.close()

    # Or as context manager:
    with mgr.connection("processed_fills", AccessTier.WRITE) as conn:
        conn.execute("INSERT ...")
        conn.commit()
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

from ..processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Access tier enumeration
# ═══════════════════════════════════════════════════════════════════════════

class AccessTier(enum.Enum):
    """Database access permission levels."""
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


# ═══════════════════════════════════════════════════════════════════════════
# SQL classification and permission checking
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# Access-controlled connection wrapper
# ═══════════════════════════════════════════════════════════════════════════

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

    @property
    def raw_connection(self) -> sqlite3.Connection:
        """Access the underlying sqlite3.Connection (for pd.read_sql_query etc.)."""
        return self._conn

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


# ═══════════════════════════════════════════════════════════════════════════
# Access tier resolution
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# Database backup utility
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# ConnectionManager — centralized connection lifecycle
# ═══════════════════════════════════════════════════════════════════════════

# Database name constants (used as keys in ConnectionManager)
DB_RAW_FILLS = "raw_fills"
DB_PROCESSED_FILLS = "processed_fills"
DB_RAW_BDIB = "raw_bdib"
DB_PROCESSED_RAW_BDIB = "processed_raw_bdib"
DB_FILL_BDIB = "fill_bdib"
DB_REGIME = "regime"

ALL_DATABASE_NAMES = [
    DB_RAW_FILLS,
    DB_PROCESSED_FILLS,
    DB_RAW_BDIB,
    DB_PROCESSED_RAW_BDIB,
    DB_FILL_BDIB,
    DB_REGIME,
]


class ConnectionManager:
    """Unified database connection manager for all CostView databases.

    Responsibilities:
    1. Map database names to file paths (from ProcessingConfig)
    2. Provide access-controlled connections with standard pragmas
    3. Manage connection lifecycle (create, use, close)
    4. Thread-safe: each get_connection() call creates a fresh connection
       (SQLite connections cannot be shared across threads)

    Usage:
        mgr = ConnectionManager()
        conn = mgr.get_connection("raw_fills", AccessTier.READ)
        try:
            df = pd.read_sql_query("SELECT ...", conn.raw_connection)
        finally:
            conn.close()

        # Context-manager shorthand:
        with mgr.connection("processed_fills", AccessTier.WRITE) as conn:
            conn.execute("INSERT ...")
            conn.commit()
    """

    def __init__(self, config: Optional[Config] = None):
        self._config = config or Config()
        self._registry: dict[str, Path] = {
            DB_RAW_FILLS: self._config.RAW_FILLS_DB,
            DB_PROCESSED_FILLS: self._config.PROCESSED_FILLS_DB,
            DB_RAW_BDIB: self._config.RAW_BDIB_DB,
            DB_PROCESSED_RAW_BDIB: self._config.PROCESSED_RAW_BDIB_DB,
            DB_FILL_BDIB: self._config.FILL_BDIB_DB,
            DB_REGIME: self._resolve_regime_db_path(),
        }

    def _resolve_regime_db_path(self) -> Path:
        """Resolve regime.db path.

        The regime module stores its path in CostView.src.regime.schema.REGIME_DB_PATH,
        but we avoid importing that at module level to prevent circular imports.
        Instead, we compute it from the same root as other DBs.
        """
        return self._config.DATA_DIR / "regime.db"

    @property
    def registry(self) -> dict[str, Path]:
        """Read-only view of database name → path mapping."""
        return dict(self._registry)

    def get_path(self, database: str) -> Path:
        """Get the file path for a named database."""
        if database not in self._registry:
            raise KeyError(
                f"Unknown database '{database}'. "
                f"Available: {list(self._registry)}"
            )
        return self._registry[database]

    def get_connection(
        self,
        database: str,
        tier: Optional[AccessTier] = None,
    ) -> AccessControlledConnection:
        """Create a new access-controlled connection to the named database.

        Each call creates a fresh sqlite3.Connection (SQLite connections
        cannot be shared across threads). The caller is responsible for
        closing the connection when done.

        Args:
            database: One of the DB_* constants or a name in the registry.
            tier: Access tier. Defaults to resolve_access_tier() (WRITE).

        Returns:
            AccessControlledConnection wrapping a new sqlite3.Connection.

        Raises:
            KeyError: If database name is not registered.
        """
        db_path = self.get_path(database)
        effective_tier = resolve_access_tier(tier)
        return self._create_connection(db_path, effective_tier)

    def get_admin_connection(self, database: str) -> sqlite3.Connection:
        """Create a raw admin connection for schema init/migration.

        Bypasses access control — use only for DDL operations.
        """
        db_path = self.get_path(database)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout = {self._config.SQLITE_BUSY_TIMEOUT_MS}")
        return conn

    def connection(
        self,
        database: str,
        tier: Optional[AccessTier] = None,
    ):
        """Context-manager shorthand for get_connection().

        Usage:
            with mgr.connection("raw_fills", AccessTier.READ) as conn:
                ...
        """
        conn = self.get_connection(database, tier)
        return conn  # AccessControlledConnection is already a context manager

    @staticmethod
    def _create_connection(
        db_path: Path,
        tier: AccessTier,
    ) -> AccessControlledConnection:
        """Create an AccessControlledConnection with standard pragmas."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.execute("PRAGMA journal_mode=WAL")
        raw_conn.execute("PRAGMA foreign_keys=ON")
        raw_conn.execute(f"PRAGMA busy_timeout = {Config.SQLITE_BUSY_TIMEOUT_MS}")
        return AccessControlledConnection(raw_conn, tier)

    def get_all_paths(self) -> dict[str, Path]:
        """Return a snapshot of all registered database paths."""
        return dict(self._registry)

    def database_exists(self, database: str) -> bool:
        """Check if the database file exists on disk."""
        return self.get_path(database).exists()

    def get_existing_databases(self) -> list[str]:
        """Return names of databases whose files exist on disk."""
        return [name for name, path in self._registry.items() if path.exists()]

"""Unified database connection management for CostView.

Migrated from database_access.py with the addition of ConnectionManager,
which provides centralized connection lifecycle management for all
CostView SQLite databases.

Two access tiers:
    READ  — SELECT only (query/status commands)
    WRITE — SELECT + INSERT/UPDATE (fetch, pipeline processing)

Usage:
    from DataPipeline.storage.connection import ConnectionManager, AccessTier

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
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from DataPipeline.config import Config, DB_RAW_FILLS, DB_PROCESSED_FILLS, DB_RAW_BDIB, DB_PROCESSED_RAW_BDIB, DB_FILL_BDIB, DB_REGIME, DB_FETCH_HISTORY, DB_BDIB_FETCH_HISTORY, DB_EXECUTION_HISTORY, DB_TICKER_REGISTRY

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Access tier enumeration
# ═══════════════════════════════════════════════════════════════════════════

class AccessTier(enum.Enum):
    """Database access permission levels."""
    READ = "read"
    WRITE = "write"


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

# execute_ddl 允许的 DDL 语句白名单 (M9): 仅 ALTER TABLE 与 CREATE TABLE/INDEX
_DDL_ALLOWED_PATTERN = re.compile(
    r"^\s*(ALTER\s+TABLE|CREATE\s+(TABLE|INDEX|VIEW))\b", re.IGNORECASE
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
                f"SQL: {sql[:120]}..."
            )


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
        """Access the underlying sqlite3.Connection (for pd.read_sql_query etc.).

        警告 (M9): 此属性绕过 execute() 的权限检查 — 仅限只读用途
        (pandas 读取、PRAGMA table_info 元数据查询)。任何 DDL/DML 写入
        必须走 ConnectionManager.execute_ddl() 或正规写连接。
        """
        return self._conn

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        category = _classify_sql(sql)
        _check_permission(self._tier, category, sql)
        if category == "destructive":
            logger.warning(f"Destructive operation: {sql[:200]}")
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
        1. Explicit parameter
        2. COSTVIEW_DB_ACCESS environment variable
        3. Default: WRITE
    """
    if explicit is not None:
        return explicit

    env_val = os.environ.get("COSTVIEW_DB_ACCESS", "").lower().strip()
    if env_val in ("read", "write"):
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

# Database name constants (sourced from DataPipeline.config)
ALL_DATABASE_NAMES = [
    DB_RAW_FILLS,
    DB_PROCESSED_FILLS,
    DB_RAW_BDIB,
    DB_PROCESSED_RAW_BDIB,
    DB_FILL_BDIB,
    DB_REGIME,
    DB_FETCH_HISTORY,
    DB_BDIB_FETCH_HISTORY,
    DB_EXECUTION_HISTORY,
    DB_TICKER_REGISTRY,
]


class ConnectionManager:
    """Unified database connection manager for all CostView databases.

    Responsibilities:
    1. Map database names to file paths (from Config)
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

    def __init__(
        self,
        config: Optional[Config] = None,
        path_overrides: Optional[dict[str, Path]] = None,
    ):
        self._config = config or Config()
        self._registry: dict[str, Path] = {
            DB_RAW_FILLS: self._config.RAW_FILLS_DB,
            DB_PROCESSED_FILLS: self._config.PROCESSED_FILLS_DB,
            DB_RAW_BDIB: self._config.RAW_BDIB_DB,
            DB_PROCESSED_RAW_BDIB: self._config.PROCESSED_RAW_BDIB_DB,
            DB_FILL_BDIB: self._config.FILL_BDIB_DB,
            DB_REGIME: self._resolve_regime_db_path(),
            DB_FETCH_HISTORY: self._config.FETCH_HISTORY_DB,
            DB_BDIB_FETCH_HISTORY: self._config.BDIB_FETCH_HISTORY_DB,
            DB_EXECUTION_HISTORY: self._config.EXECUTION_HISTORY_DB,
            DB_TICKER_REGISTRY: self._config.TICKER_REGISTRY_DB,
        }
        if path_overrides:
            for key, path in path_overrides.items():
                if key in self._registry:
                    self._registry[key] = Path(path)

        # Thread-local connection cache (Iteration 6.3 optimization).
        # For read-only / short-query workloads (e.g. regime tagger,
        # pipeline guards), the first get_connection(READ) call per
        # thread creates a connection and caches it; subsequent calls
        # within the same thread reuse it. This avoids the ~50µs per
        # call overhead of creating new sqlite3.Connection objects.
        # The cache is cleared on close() or when the thread dies.
        self._thread_local = threading.local()

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
        row_factory: Optional[type] = None,
    ) -> AccessControlledConnection:
        """Get an access-controlled connection to the named database.

        For READ-tier connections, reuses a thread-local cache when possible
        to avoid the overhead of creating new sqlite3.Connection objects
        on every call.  The cache key is ``(database, row_factory)`` so
        calls with different row factories get separate cached connections.

        For WRITE tier, always creates a fresh connection.

        Args:
            database: One of the DB_* constants or a name in the registry.
            tier: Access tier. Defaults to resolve_access_tier() (WRITE).
            row_factory: Optional row_factory to set on the underlying
                sqlite3.Connection (e.g. sqlite3.Row for dict-like rows).

        Returns:
            AccessControlledConnection wrapping an sqlite3.Connection.

        Raises:
            KeyError: If database name is not registered.
        """
        db_path = self.get_path(database)
        effective_tier = resolve_access_tier(tier)

        # READ connections: reuse thread-local cache if available.
        if effective_tier == AccessTier.READ:
            cache_key = (database, row_factory)
            cache = getattr(self._thread_local, 'read_conns', None)
            if cache is not None and cache_key in cache:
                cached = cache[cache_key]
                try:
                    cached.raw_connection.execute("SELECT 1")
                    return cached
                except Exception:
                    # Connection stale — discard and create new.
                    cache.pop(cache_key, None)

            conn = self._create_connection(db_path, effective_tier, row_factory=row_factory)
            if cache is None:
                self._thread_local.read_conns = {cache_key: conn}
            else:
                cache[cache_key] = conn
            return conn

        # WRITE connections: always fresh.
        return self._create_connection(db_path, effective_tier, row_factory=row_factory)

    def close_thread_cached_connections(self) -> None:
        """Close all cached READ connections for the current thread.

        After calling this, the next get_connection(READ) call in this
        thread will create fresh connections.  Useful when databases
        have been rebuilt or migrated and cached read handles are stale.
        """
        cache = getattr(self._thread_local, 'read_conns', None)
        if cache is None:
            return
        for key, conn in list(cache.items()):
            try:
                conn.close()
            except Exception:
                pass
        self._thread_local.read_conns = {}

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

    def execute_ddl(
        self,
        database: str,
        sql: str,
        params: tuple = (),
    ) -> None:
        """执行 DDL 语句 (ALTER TABLE 等) — 唯一的越权通道 (M9)。

        访问控制层将 ALTER/DROP 等归类为 destructive, 业务写入连接无法执行。
        此前代码通过 ``conn.raw_connection`` 绕过权限检查自行执行 DDL,
        形成隐式越权通道。本方法收敛该通道:
        - 显式命名 (execute_ddl), 调用意图自文档化
        - 仅允许 DDL 类别语句 (ALTER/CREATE), 拒绝 DML/DROP
        - 全程审计日志

        Args:
            database: 数据库名 (DB_* 常量)
            sql: DDL 语句
            params: 绑定参数

        Raises:
            ValueError: 语句不属于允许的 DDL 类别
        """
        if not _DDL_ALLOWED_PATTERN.match(sql or ""):
            raise ValueError(
                f"execute_ddl 仅允许 ALTER TABLE/CREATE 语句: {sql[:120]}"
            )
        logger.warning("DDL 越权通道调用: %s on %s: %s", database, sql[:200], params)
        conn = self.get_admin_connection(database)
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def connection(
        self,
        database: str,
        tier: Optional[AccessTier] = None,
        row_factory: Optional[type] = None,
    ):
        """Context-manager shorthand for get_connection().

        Usage:
            with mgr.connection("raw_fills", AccessTier.READ) as conn:
                ...
        """
        conn = self.get_connection(database, tier, row_factory=row_factory)
        return conn  # AccessControlledConnection is already a context manager

    @staticmethod
    def _create_connection(
        db_path: Path,
        tier: AccessTier,
        row_factory: Optional[type] = None,
    ) -> AccessControlledConnection:
        """Create an AccessControlledConnection with standard pragmas."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.execute("PRAGMA journal_mode=WAL")
        raw_conn.execute("PRAGMA foreign_keys=ON")
        raw_conn.execute(f"PRAGMA busy_timeout = {Config.SQLITE_BUSY_TIMEOUT_MS}")
        if row_factory is not None:
            raw_conn.row_factory = row_factory
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

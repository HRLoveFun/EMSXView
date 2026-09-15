"""Unified database connection management for CostView.

Migrated from database_access.py with the addition of ConnectionManager,
which provides centralized connection lifecycle management for all
CostView SQLite databases.

只读访问层（009-external-data-store 起物理分离，010-extract-pipeline 起只读化）:
    READ  — 文件级只读 (SQLite mode=ro)，仅 SELECT；库文件必须已存在，
            缺失抛 FileNotFoundError，由调用方决定是否降级为空结果。
            读取方 (API/查询/监控进程) 即使有 bug 也无法写坏数据文件。
    WRITE — 一律拒绝：数据库更新维护的唯一写入方是独立仓库
            EMSXDataPipeline，本模块不再提供任何写连接通道。

Usage:
    from data_access.storage.connection import ConnectionManager, AccessTier

    mgr = ConnectionManager()
    conn = mgr.get_connection("raw_fills", AccessTier.READ)
    # ... use conn ...
    conn.close()

    # Or as context manager:
    with mgr.connection("processed_fills") as conn:
        conn.execute("SELECT ...")
"""

from __future__ import annotations

import enum
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.request import pathname2url

from data_access.config import Config, DB_RAW_FILLS, DB_PROCESSED_FILLS, DB_RAW_BDIB, DB_PROCESSED_RAW_BDIB, DB_FILL_BDIB, DB_REGIME, DB_FETCH_HISTORY, DB_BDIB_FETCH_HISTORY, DB_EXECUTION_HISTORY, DB_TICKER_REGISTRY

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
# 注意：不含 journal_mode —— 只读连接无权切换 journal mode（由写入方
# 设置并持久化在文件头，只读连接直接受益），白名单不应放行该意图。
_PRAGMA_SAFE = re.compile(
    r"^\s*PRAGMA\s+(foreign_keys|table_info|index_list)\b",
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
    """Raise PermissionError if the operation is not allowed for the given tier.

    本模块只可能创建 READ tier 连接（get_connection 对非 READ 一律拒绝），
    故除 pragma_safe 外一切非读操作均拒绝。
    """
    if sql_category == "pragma_safe":
        return  # always allowed (connection config)

    if sql_category != "read":
        raise PermissionError(
            f"READ-only access: '{sql_category}' operation denied. "
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
        (pandas 读取、PRAGMA table_info 元数据查询)。即使经此通道注入
        写 SQL，mode=ro 文件级护栏仍会拒绝；任何 DDL/DML 写入属于
        独立仓库 EMSXDataPipeline 的职责。
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
        3. Default: READ（EMSXView 为纯读取消费者，010-extract-pipeline）
    """
    if explicit is not None:
        return explicit

    env_val = os.environ.get("COSTVIEW_DB_ACCESS", "").lower().strip()
    if env_val in ("read", "write"):
        return AccessTier(env_val)

    return AccessTier.READ


# ═══════════════════════════════════════════════════════════════════════════
# ConnectionManager — centralized connection lifecycle
# ═══════════════════════════════════════════════════════════════════════════

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
        with mgr.connection("processed_fills") as conn:
            conn.execute("SELECT ...")
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

        # P2-8 整改：移除 Iteration 6.3 引入的线程本地连接缓存。
        # 原因：(1) 全部调用方遵循 get→try→finally close 约定，缓存中的
        # 连接被 close 后靠 liveness 探测重建，缓存对热路径形同虚设；
        # (2) 缓存使 get_connection 返回值别名共享（如 repository 返回
        # 连接所有权时），一处 close() 会波及其他持有者。现契约：
        # 每次 get_connection 返回全新连接，生命周期完全归调用方。

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

        Args:
            database: One of the DB_* constants or a name in the registry.
            tier: Access tier. Defaults to resolve_access_tier() (READ)。
                非 READ tier 一律拒绝 —— EMSXView 是纯读取消费者。
            row_factory: Optional row_factory to set on the underlying
                sqlite3.Connection (e.g. sqlite3.Row for dict-like rows).

        Returns:
            AccessControlledConnection wrapping an sqlite3.Connection.

        Raises:
            KeyError: If database name is not registered.
            PermissionError: If tier resolves to anything other than READ.
        """
        db_path = self.get_path(database)
        effective_tier = resolve_access_tier(tier)

        # EMSXView 为纯读取消费者（010-extract-pipeline）：拒绝一切写意图。
        # 数据库更新维护的唯一写入方是独立仓库 EMSXDataPipeline。
        if effective_tier != AccessTier.READ:
            raise PermissionError(
                "EMSXView is a read-only consumer of the pipeline databases "
                "(010-extract-pipeline); pipeline writes belong to the "
                "independent EMSXDataPipeline repository."
            )

        # READ 连接：每次创建全新连接（P2-8：不再线程本地缓存）
        if effective_tier == AccessTier.READ:
            return self._create_connection(db_path, effective_tier, row_factory=row_factory)

        raise PermissionError(  # pragma: no cover - defensive
            "unreachable: non-READ tiers rejected above"
        )

    def close_thread_cached_connections(self) -> None:
        """Deprecated no-op（P2-8：线程缓存已移除，保留以兼容旧调用点）。

        历史上用于在数据库重建/迁移后丢弃线程缓存的 READ 连接；
        现在 get_connection 每次返回全新连接，此方法无需任何操作。
        """
        return None

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
        """Create an access-controlled READ connection with standard pragmas.

        只读语义 (009-external-data-store / 010-extract-pipeline):

        - 以 SQLite URI 只读模式 (``mode=ro``) 打开 — 文件系统层面
          拒绝任何写操作，即使调用方经 ``raw_connection`` 绕过 SQL 分类拦截，
          也无法写坏数据库 (G0 数据零受损)。
        - 要求库文件已存在：只读模式不创建新库，缺失即抛
          FileNotFoundError (fail-fast，防止误建空库掩盖数据缺失问题)。
          需要优雅降级的查询方 (如 TCA 报告) 自行捕获并回退为空结果。
        - 不执行 ``PRAGMA journal_mode=WAL``：只读连接无法切换
          journal mode；WAL 由写入方设置并持久化在文件头，只读连接直接受益。

        写连接通道已删除：数据库写入属于独立仓库 EMSXDataPipeline。
        """
        if not db_path.exists():
            raise FileNotFoundError(
                f"READ 连接要求库文件已存在 (只读模式不创建新库): {db_path}"
            )
        # pathname2url 处理 Windows 盘符、空格与中文路径的 URI 转义
        uri = "file:" + pathname2url(str(db_path)) + "?mode=ro"
        raw_conn = sqlite3.connect(uri, uri=True)
        raw_conn.execute("PRAGMA foreign_keys=ON")
        raw_conn.execute(f"PRAGMA busy_timeout = {Config.SQLITE_BUSY_TIMEOUT_MS}")
        if row_factory is not None:
            raw_conn.row_factory = row_factory
        return AccessControlledConnection(raw_conn, tier)

    def database_exists(self, database: str) -> bool:
        """Check if the database file exists on disk."""
        return self.get_path(database).exists()

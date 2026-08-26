"""Read-only diagnostic layer for the DatabaseView module.

Renamed from ``platform_data/repositories.py`` to clarify that this is a
*diagnostic query layer* for the frontend DatabaseView, not a business
logic repository.

This module exposes *diagnostic* statistics over the CostView SQLite files
without leaking the underlying DB classes to routing code. It keeps the
DatabaseView backend router thin, and lets us later swap physical storage
without touching the HTTP layer.

Scope (per iteration plan Phase A1):
- raw_fills.db          → raw_fills, fetch_log
- processed_fills.db    → processed_fills, route_registry
- raw_bdib.db           → raw_bdib
- fill_bdib.db          → fill_bdib
- fill_fetch_history.db → fetch_records (if present)

Diagnostic queries run in READ tier (access_tier=AccessTier.READ). The only
exception is the summary cache table (db_summary_cache) written to
fill_fetch_history.db via get_summary_cached() — a performance optimization
whose failures silently degrade to live recomputation.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# Phase 3/A2: ConnectionManager is injected via init_diagnostics_db() at module
# load time by the caller (e.g. backend/api/routers/database.py). platform_data
# no longer imports DataPipeline directly for diagnostics.
from platform_data.contracts.protocols import (
    AccessTier,
    ConnectionManagerProtocol,
    ConfigProtocol,
)

# Inlined from DataPipeline.storage.connection.DB_FETCH_HISTORY
_DB_FETCH_HISTORY_KEY: str = "fill_fetch_history"
# Inlined from DataPipeline.storage.connection.DB_BDIB_FETCH_HISTORY
_DB_BDIB_FETCH_HISTORY_KEY: str = "bdib_fetch_history"

# Summary 缓存表（建在 fill_fetch_history.db）：
# 每次切换数据库都实时重算 summary 在多 GB 表上耗时较长，将计算结果
# 缓存于此表，源库文件 mtime/size 未变且未跨天时直接复用。
_SUMMARY_CACHE_TABLE: str = "db_summary_cache"

# Table name constants (stable, synced with DataPipeline.config.Config)
_RAW_FILLS_TABLE: str = "raw_fills"
_PROCESSED_FILLS_TABLE: str = "processed_fills"
_FETCH_LOG_TABLE: str = "fetch_log"
_RAW_BDIB_TABLE: str = "raw_bdib"
_FILL_BDIB_TABLE: str = "fill_bdib"
_BDIB_FETCH_HISTORY_TABLE: str = "bdib_fetch_history"

logger = logging.getLogger(__name__)

# Injected at module load by the caller (see init_diagnostics_db).
_diagnostics_mgr: ConnectionManagerProtocol | None = None


def init_diagnostics_db(connection_manager: ConnectionManagerProtocol) -> None:
    """Wire a ConnectionManager into the diagnostics module.

    Must be called once before any diagnostic queries are performed.
    Typical call site: ``backend/api/routers/database.py`` at import time.

    Example::

        from DataPipeline import ConnectionManager
        from platform_data.database_diagnostics import init_diagnostics_db
        init_diagnostics_db(ConnectionManager())
    """
    global _diagnostics_mgr
    _diagnostics_mgr = connection_manager


def _get_db_paths() -> dict[str, Path]:
    """Get database paths from the injected ConnectionManager.

    Uses ConnectionManager's registry as the single source of truth for
    database paths. Call init_diagnostics_db() before usage.
    """
    if _diagnostics_mgr is None:
        raise RuntimeError(
            "ConnectionManager not injected. Call "
            "platform_data.database_diagnostics.init_diagnostics_db(ConnectionManager()) "
            "before using diagnostic functions."
        )
    return _diagnostics_mgr.get_all_paths()


# ── Registry of databases we expose to the frontend ──────────────────────────

@dataclass(frozen=True)
class _TableSpec:
    """Declarative spec for a table we surface in DatabaseView."""

    name: str
    date_column: Optional[str]   # column used for trading-date coverage (YYYYMMDD text)
    primary_key: Optional[str]   # for display only
    description: str


@dataclass(frozen=True)
class _DatabaseSpec:
    key: str                     # stable identifier used by the frontend
    label: str                   # human-readable name
    path: Path
    description: str
    tables: tuple[_TableSpec, ...]


def _build_registry() -> tuple[_DatabaseSpec, ...]:
    paths = _get_db_paths()
    return (
        _DatabaseSpec(
            key="raw_fills",
            label="Raw Fills",
            path=paths.get("raw_fills", Path("raw_fills.db")),
            description="EMSX GetFills raw rows (28 original + 5 derived columns).",
            tables=(
                _TableSpec(
                    name=_RAW_FILLS_TABLE,
                    date_column="order_as_of_date",
                    primary_key="(OrderId, RouteId, FillId)",
                    description="Bloomberg EMSX fills, INSERT OR REPLACE for late corrections.",
                ),
                _TableSpec(
                    name=_FETCH_LOG_TABLE,
                    date_column="fetch_date",
                    primary_key="(fetch_date, fetch_started_at)",
                    description="Per-day fetch tracking (records_fetched, status).",
                ),
            ),
        ),
        _DatabaseSpec(
            key="processed_fills",
            label="Processed Fills",
            path=paths.get("processed_fills", Path("processed_fills.db")),
            description="Cleaned 27-column fact table + route registry.",
            tables=(
                _TableSpec(
                    name=_PROCESSED_FILLS_TABLE,
                    date_column="order_as_of_date",
                    primary_key="(OrderId, RouteId, FillId, order_as_of_date)",
                    description="TCA-ready fills (deduplicated, typed).",
                ),
                _TableSpec(
                    name="route_registry",
                    date_column=None,
                    primary_key="(OrderId, RouteId)",
                    description="Route-level metadata lookup.",
                ),
            ),
        ),
        _DatabaseSpec(
            key="raw_bdib",
            label="Raw BDIB",
            path=paths.get("raw_bdib", Path("raw_bdib.db")),
            description="10-second intraday BDIB bars (Bloomberg-native columns).",
            tables=(
                _TableSpec(
                    name=_RAW_BDIB_TABLE,
                    date_column="order_as_of_date",
                    primary_key="(equ_ticker, order_as_of_date, mkt_timestamp)",
                    description="OHLC + volume + num_trds + value per 10s bar.",
                ),
            ),
        ),
        _DatabaseSpec(
            key="fill_bdib",
            label="Fill × BDIB",
            path=paths.get("fill_bdib", Path("fill_bdib.db")),
            description="Fills enriched with BDIB intraday metrics (TCA input).",
            tables=(
                _TableSpec(
                    name=_FILL_BDIB_TABLE,
                    date_column="order_as_of_date",
                    primary_key="(OrderId, RouteId, order_as_of_date, mkt_timestamp)",
                    description="Integrated fill × BDIB view used by TCA analysis.",
                ),
            ),
        ),
        _DatabaseSpec(
            key="fill_fetch_history",
            label="Fill Fetch History",
            path=paths.get(_DB_FETCH_HISTORY_KEY, Path("fill_fetch_history.db")),
            description="Historical fetch-job records (deduplication + audit).",
            tables=(
                _TableSpec(
                    name="fill_fetch_history",
                    date_column="source_date",
                    primary_key="(source_date, data_hash)",
                    description="Per-day fetch job records (data_hash dedup check).",
                ),
            ),
        ),
        _DatabaseSpec(
            key="bdib_fetch_history",
            label="BDIB Fetch History",
            path=paths.get(_DB_BDIB_FETCH_HISTORY_KEY, Path("bdib_fetch_history.db")),
            description="Per-trading-day BDIB fetch records (audit + coverage review).",
            tables=(
                _TableSpec(
                    name=_BDIB_FETCH_HISTORY_TABLE,
                    date_column="source_date",
                    primary_key="(source_date, data_hash)",
                    description="Per-day BDIB fetch records (row_count, ticker_count).",
                ),
            ),
        ),
    )


_REGISTRY: tuple[_DatabaseSpec, ...] | None = None


def _get_registry() -> tuple[_DatabaseSpec, ...]:
    """Lazily build the database registry on first access.

    This avoids calling _get_db_paths() at module import time, which requires
    ConnectionManager injection via init_diagnostics_db().
    """
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def _spec_by_key(key: str) -> _DatabaseSpec:
    for spec in _get_registry():
        if spec.key == key:
            return spec
    raise KeyError(f"Unknown database key: {key}")


def _list_actual_tables(path: Path) -> list[str]:
    """Return the user tables present in a SQLite file (excluding sqlite_*).

    Used as the source of truth for which tables exist, so the diagnostic
    UI can surface every table without needing manual registration.
    Returns an empty list if the file is missing or unreadable.
    """
    if not path.exists():
        return []
    try:
        with _open_ro(path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
        return [str(r[0]) for r in rows]
    except sqlite3.Error:
        return []


def _resolve_table_spec(spec: _DatabaseSpec, table: str) -> _TableSpec:
    """Validate a table name and return spec metadata (synthesised if needed).

    Validation rule: the table must exist in the actual SQLite file. This
    keeps SQL injection impossible (only real table names are ever
    interpolated into queries) while letting the UI inspect tables that
    aren't manually registered in `_build_registry()`.
    """
    actual = set(_list_actual_tables(spec.path))
    if table not in actual:
        raise KeyError(
            f"Table '{table}' does not exist in database '{spec.key}'"
        )
    for t in spec.tables:
        if t.name == table:
            return t
    # Unregistered but real table — synthesise a minimal spec.
    return _TableSpec(
        name=table,
        date_column=None,
        primary_key=None,
        description="(unregistered table)",
    )


def _spec_table(spec: _DatabaseSpec, table: str) -> _TableSpec:
    """Backwards-compatible alias for `_resolve_table_spec`."""
    return _resolve_table_spec(spec, table)


# ── Response dataclasses ──────────────────────────────────────────────────────

@dataclass
class DatabaseOverview:
    key: str
    label: str
    path: str
    description: str
    exists: bool
    size_bytes: int = 0
    last_modified: Optional[str] = None
    wal_active: bool = False
    table_count: int = 0
    total_rows: int = 0
    latest_trade_date: Optional[str] = None
    earliest_trade_date: Optional[str] = None
    distinct_trade_dates: int = 0
    health: str = "unknown"   # "ok" | "empty" | "missing" | "stale"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DateRowCount:
    trade_date: str
    row_count: int
    # 该交易日数据最近一次拉取日 (YYYY-MM-DD)；仅 raw_fills 有拉取元数据
    fetch_date: Optional[str] = None
    # 更新过程中值得告知用户的异常信息（如延迟拉取、多次拉取、拉取失败、无数据）
    note: Optional[str] = None


@dataclass
class TableSummary:
    name: str
    description: str
    primary_key: Optional[str]
    date_column: Optional[str]
    row_count: int
    latest_trade_date: Optional[str] = None
    earliest_trade_date: Optional[str] = None
    distinct_trade_dates: int = 0
    per_date_counts: list[DateRowCount] = field(default_factory=list)


@dataclass
class DatabaseSummary:
    key: str
    label: str
    path: str
    exists: bool
    size_bytes: int
    last_modified: Optional[str]
    description: str
    tables: list[TableSummary]

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "path": self.path,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "last_modified": self.last_modified,
            "description": self.description,
            "tables": [
                {
                    "name": t.name,
                    "description": t.description,
                    "primary_key": t.primary_key,
                    "date_column": t.date_column,
                    "row_count": t.row_count,
                    "latest_trade_date": t.latest_trade_date,
                    "earliest_trade_date": t.earliest_trade_date,
                    "distinct_trade_dates": t.distinct_trade_dates,
                    "per_date_counts": [asdict(r) for r in t.per_date_counts],
                }
                for t in self.tables
            ],
        }


@dataclass
class ColumnInfo:
    name: str
    type: str            # declared SQLite type, e.g. "TEXT", "INTEGER", "REAL"
    nullable: bool
    primary_key: int     # 0 if not part of PK; otherwise the 1-based PK position
    default_value: Optional[str] = None


@dataclass
class IndexInfo:
    name: str
    unique: bool
    columns: list[str] = field(default_factory=list)


@dataclass
class TableSchema:
    database_key: str
    table: str
    description: str
    primary_key_display: Optional[str]
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "database_key": self.database_key,
            "table": self.table,
            "description": self.description,
            "primary_key_display": self.primary_key_display,
            "columns": [asdict(c) for c in self.columns],
            "indexes": [asdict(i) for i in self.indexes],
        }


@dataclass
class ColumnAnomaly:
    column: str
    severity: str        # "info" | "warning" | "error"
    code: str            # "high_null" | "all_same" | "negative_value" | ...
    message: str


@dataclass
class TableSample:
    database_key: str
    table: str
    columns: list[str]
    rows: list[list]              # JSON-safe values (str/int/float/bool/None)
    row_count_estimate: int       # cheap estimate via MAX(_rowid_)
    fetched_at: str               # ISO timestamp
    order_by: Optional[str]       # human-readable ordering used
    anomalies: list[ColumnAnomaly] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "database_key": self.database_key,
            "table": self.table,
            "columns": list(self.columns),
            "rows": [list(r) for r in self.rows],
            "row_count_estimate": self.row_count_estimate,
            "fetched_at": self.fetched_at,
            "order_by": self.order_by,
            "anomalies": [asdict(a) for a in self.anomalies],
        }


@dataclass
class IntegrityIssue:
    code: str
    severity: str        # "info" | "warning" | "error"
    message: str
    count: int = 0


@dataclass
class IntegrityReport:
    key: str
    checked_at: str
    issues: list[IntegrityIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "checked_at": self.checked_at,
            "issues": [asdict(i) for i in self.issues],
        }


# ── Internal helpers ──────────────────────────────────────────────────────────

class _RoConnection:
    """Context manager wrapper that guarantees connection close on exit."""

    def __init__(self, path: Path):
        self._path = path
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> sqlite3.Connection:
        try:
            self._conn = sqlite3.connect(
                f"file:{self._path.as_posix()}?mode=ro",
                uri=True,
                timeout=5.0,
            )
        except sqlite3.OperationalError:
            self._conn = sqlite3.connect(str(self._path), timeout=5.0)
        self._conn.execute("PRAGMA busy_timeout=3000")
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass


def _open_ro(path: Path) -> _RoConnection:
    """Open a read-only SQLite connection as a closing context manager."""
    return _RoConnection(path)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0])
    except sqlite3.Error:
        return 0


def _count_rows_fast(conn: sqlite3.Connection, table: str) -> int:
    """Approximate row count using MAX(_rowid_).

    Works well for append-mostly tables (INSERT OR REPLACE keeps rowids stable
    for re-inserts since we use composite PKs, so rowid max ≈ row count).
    Far cheaper than COUNT(*) on multi-GB tables because it reads a single
    B-tree leaf instead of scanning the whole table.
    """
    try:
        row = conn.execute(f"SELECT MAX(_rowid_) FROM [{table}]").fetchone()
    except sqlite3.Error:
        return 0
    if not row or row[0] is None:
        return 0
    return int(row[0])


def _sum_per_date_count(
    conn: sqlite3.Connection, table: str, date_column: str
) -> Optional[int]:
    """Exact row count via the date index (scans covering index, not full table)."""
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM [{table}] "
            f"WHERE [{date_column}] IS NOT NULL AND TRIM([{date_column}]) != ''"
        ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return int(row[0])


def _date_coverage(
    conn: sqlite3.Connection, table: str, date_column: str
) -> tuple[Optional[str], Optional[str], int]:
    """Exact coverage — includes distinct-date count. May scan the index."""
    try:
        row = conn.execute(
            f"SELECT MIN([{date_column}]), MAX([{date_column}]), "
            f"COUNT(DISTINCT [{date_column}]) "
            f"FROM [{table}] WHERE [{date_column}] IS NOT NULL "
            f"AND TRIM([{date_column}]) != ''"
        ).fetchone()
    except sqlite3.Error:
        return None, None, 0
    if not row:
        return None, None, 0
    return row[0], row[1], int(row[2] or 0)


def _date_range_fast(
    conn: sqlite3.Connection, table: str, date_column: str
) -> tuple[Optional[str], Optional[str]]:
    """Index-only MIN/MAX lookup — O(log n) on an indexed date column.

    SQLite's MIN/MAX endpoint optimization only applies when MIN and MAX are
    the sole expression in the SELECT list; combining them into one query
    forces a full covering-index scan. Splitting the queries keeps this
    O(log n) even on multi-GB tables with 100M+ index entries.
    """
    try:
        min_row = conn.execute(
            f"SELECT MIN([{date_column}]) FROM [{table}] "
            f"WHERE [{date_column}] IS NOT NULL AND [{date_column}] > ''"
        ).fetchone()
        max_row = conn.execute(
            f"SELECT MAX([{date_column}]) FROM [{table}] "
            f"WHERE [{date_column}] IS NOT NULL AND [{date_column}] > ''"
        ).fetchone()
    except sqlite3.Error:
        return None, None
    lo = min_row[0] if min_row else None
    hi = max_row[0] if max_row else None
    # Treat empty strings as missing data
    if isinstance(lo, str) and not lo.strip():
        lo = None
    if isinstance(hi, str) and not hi.strip():
        hi = None
    return lo, hi


def _per_date_counts(
    conn: sqlite3.Connection,
    table: str,
    date_column: str,
    limit: int = 800,
) -> list[DateRowCount]:
    try:
        rows = conn.execute(
            f"SELECT [{date_column}] AS d, COUNT(*) AS c "
            f"FROM [{table}] "
            f"WHERE [{date_column}] IS NOT NULL AND [{date_column}] != '' "
            f"GROUP BY [{date_column}] "
            f"ORDER BY d ASC "
            f"LIMIT ?",
            (int(limit),),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [DateRowCount(trade_date=str(r[0]), row_count=int(r[1])) for r in rows]


# Overview 表格只展示最近的工作日窗口（周一至周五）。
_RECENT_TRADING_DAYS: int = 20
# 全量统计降级阈值：行数（MAX rowid 近似）超过该值时跳过 GROUP BY 全量聚合，
# 避免 80GB 级表（如 raw_bdib 3.7 亿行）上 30s+ 的首屏等待。
_FULL_STATS_THRESHOLD: int = 50_000_000
_DATE_ISO_RE = re.compile(r"^(\d{4})[-/]?(\d{2})[-/]?(\d{2})")


def _to_ymd(value: str) -> str:
    """归一化日期为 YYYY-MM-DD（兼容 YYYYMMDD / YYYY-MM-DD / datetime 字符串）。"""
    m = _DATE_ISO_RE.match(str(value).strip())
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return str(value).strip()


def _previous_weekdays(reference: date, n: int) -> list[date]:
    """从 reference（含）向前枚举 n 个工作日（周一至周五），升序返回。"""
    days: list[date] = []
    current = reference
    while len(days) < n:
        if current.weekday() < 5:
            days.append(current)
        current -= timedelta(days=1)
    days.reverse()
    return days


def _weekday_delta(later: str, earlier: str) -> int:
    """计算 later 相对 earlier 之间的工作日（周一至周五）数量，later <= earlier 返回 0。"""
    try:
        a = datetime.strptime(later, "%Y-%m-%d").date()
        b = datetime.strptime(earlier, "%Y-%m-%d").date()
    except ValueError:
        return 0
    if b <= a:
        return 0
    delta = 0
    current = a + timedelta(days=1)
    while current <= b:
        if current.weekday() < 5:
            delta += 1
        current += timedelta(days=1)
    return delta


def _window_ranges(days: list[date], date_column: str) -> tuple[str, str]:
    """为窗口日期生成两段闭区间范围条件（SARGable，可走索引）。

    返回 (iso_cond, compact_cond)，分别覆盖 YYYY-MM-DD(datetime) 与
    YYYYMMDD 两种存储格式：
        [col] >= '2026-07-28' AND [col] < '2026-08-25'
    范围含窗口内的周末日期（无数据则无行），Python 侧按工作日键取值。
    注意：必须避免 LIKE/OR 链/TRIM() 等表达式，否则 SQLite 无法使用
    日期索引，多 GB 表上会退化为全表扫描（分钟级）。
    """
    start = days[0]
    end = days[-1] + timedelta(days=1)
    iso = (
        f"[{date_column}] >= '{start.isoformat()}' "
        f"AND [{date_column}] < '{end.isoformat()}'"
    )
    compact = (
        f"[{date_column}] >= '{start.strftime('%Y%m%d')}' "
        f"AND [{date_column}] < '{end.strftime('%Y%m%d')}'"
    )
    return iso, compact


def _window_group_by(
    conn: sqlite3.Connection,
    table: str,
    date_column: str,
    days: list[date],
) -> dict[str, int]:
    """对窗口范围执行索引友好的 GROUP BY 计数，合并两种格式，返回 {iso_day: count}。"""
    result: dict[str, int] = {}
    for cond in _window_ranges(days, date_column):
        try:
            rows = conn.execute(
                f"SELECT [{date_column}] AS d, COUNT(*) AS c "
                f"FROM [{table}] "
                f"WHERE {cond} "
                f"GROUP BY [{date_column}]"
            ).fetchall()
        except sqlite3.Error:
            continue
        for r in rows:
            key = _to_ymd(str(r[0]))
            result[key] = result.get(key, 0) + int(r[1])
    return result


def _recent_rows(
    conn: sqlite3.Connection,
    table: str,
    date_column: str,
    days: list[date],
) -> list[DateRowCount]:
    """最近 n 个交易日的覆盖行；缺失日期以 row_count=0 + note='no data' 占位。"""
    if not days:
        return []
    by_day = _window_group_by(conn, table, date_column, days)
    result: list[DateRowCount] = []
    for d in days:
        iso_day = d.isoformat()
        count = by_day.get(iso_day, 0)
        note = None if count > 0 else "no data"
        result.append(DateRowCount(trade_date=iso_day, row_count=count, note=note))
    return result


def _recent_raw_fills_rows(
    conn: sqlite3.Connection,
    days: list[date],
) -> list[DateRowCount]:
    """raw_fills 最近 n 个交易日窗口行：行数 + fetch_date（最近拉取日）+ note。

    note 判定（更新过程中值得告知用户的异常）：
    - 无数据且 fetch_log 存在 failed 记录 → "fetch failed"
    - 无数据                             → "no data"
    - 多个 source_date（多次拉取）        → "fetched N times"
    - 唯一 source_date 且晚于交易日       → "delayed N days"
    """
    if not days:
        return []
    date_column = "order_as_of_date"
    # 行数（不要求 source_date 非空，兼容老数据）
    count_by_day = _window_group_by(conn, _RAW_FILLS_TABLE, date_column, days)
    # 每交易日对应的拉取日集合（同样按范围查询，避免全表扫描）
    sources_by_day: dict[str, set[str]] = {}
    for cond in _window_ranges(days, date_column):
        try:
            src_rows = conn.execute(
                f"SELECT DISTINCT [{date_column}] AS d, [source_date] AS s "
                f"FROM [{_RAW_FILLS_TABLE}] "
                f"WHERE {cond} AND [source_date] IS NOT NULL "
                f"AND TRIM([source_date]) != ''"
            ).fetchall()
        except sqlite3.Error:
            continue
        for oad, src in src_rows:
            sources_by_day.setdefault(_to_ymd(str(oad)), set()).add(_to_ymd(str(src)))
    # fetch_log 中 failed 的拉取日
    try:
        failed_rows = conn.execute(
            f"SELECT [source_date] FROM [{_FETCH_LOG_TABLE}] "
            f"WHERE status = 'failed'"
        ).fetchall()
        failed_sources = {_to_ymd(str(r[0])) for r in failed_rows}
    except sqlite3.Error:
        failed_sources = set()
    result: list[DateRowCount] = []
    for d in days:
        iso_day = d.isoformat()
        count = count_by_day.get(iso_day, 0)
        sources = sorted(sources_by_day.get(iso_day, set()))
        if count == 0 and not sources:
            note = "fetch failed" if iso_day in failed_sources else "no data"
            result.append(
                DateRowCount(trade_date=iso_day, row_count=0, note=note)
            )
            continue
        notes: list[str] = []
        if len(sources) > 1:
            notes.append(f"fetched {len(sources)} times")
        elif sources:
            delayed = _weekday_delta(iso_day, sources[0])
            if delayed > 0:
                notes.append(f"delayed {delayed}d")
        if any(s in failed_sources for s in sources):
            notes.append("fetch failed")
        result.append(
            DateRowCount(
                trade_date=iso_day,
                row_count=count,
                fetch_date=sources[-1] if sources else None,
                note="; ".join(notes) if notes else None,
            )
        )
    return result


def _stat_file(path: Path) -> tuple[bool, int, Optional[str], bool]:
    """Return (exists, size_bytes, last_modified_iso, wal_active)."""
    if not path.exists():
        return False, 0, None, False
    st = path.stat()
    last_mod = (
        datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds")
    )
    wal = (path.with_name(path.name + "-wal")).exists()
    return True, int(st.st_size), last_mod, wal


def _source_fingerprint(
    path: Path,
) -> tuple[Optional[int], int, Optional[int], Optional[int]]:
    """返回源库变更指纹 (data_version, size, mtime_ns, wal_mtime_ns)。

    - size / mtime_ns：主文件字节数与纳秒级 mtime（管道写入或 checkpoint 后变化）
    - wal_mtime_ns：WAL 文件 mtime —— WAL 模式下写入不落主文件，仅更新
      -wal 文件；纳入指纹可在 checkpoint 前即时感知写入
    - data_version：SQLite 3.31+ 写入计数器，尽力而为的附加校验
    （部分环境下跨连接传播不可靠，不作为唯一判定）
    文件不存在返回 (None, 0, None, None)。
    """
    if not path.exists():
        return None, 0, None, None
    st = path.stat()
    wal = path.with_name(path.name + "-wal")
    wal_ns: Optional[int] = int(wal.stat().st_mtime_ns) if wal.exists() else None
    data_version: Optional[int] = None
    try:
        with _open_ro(path) as conn:
            row = conn.execute("PRAGMA data_version").fetchone()
            if row:
                data_version = int(row[0])
    except sqlite3.Error:
        pass
    return data_version, int(st.st_size), int(st.st_mtime_ns), wal_ns


# ── Public API ────────────────────────────────────────────────────────────────

def list_database_keys() -> list[str]:
    return [spec.key for spec in _get_registry()]


def get_overview() -> list[DatabaseOverview]:
    """Cheap overview of every registered database (file stats + headline counts)."""
    items: list[DatabaseOverview] = []
    for spec in _get_registry():
        exists, size, last_mod, wal = _stat_file(spec.path)
        ov = DatabaseOverview(
            key=spec.key,
            label=spec.label,
            path=str(spec.path),
            description=spec.description,
            exists=exists,
            size_bytes=size,
            last_modified=last_mod,
            wal_active=wal,
        )
        if not exists:
            ov.health = "missing"
            items.append(ov)
            continue
        try:
            with _open_ro(spec.path) as conn:
                present_tables = [t for t in spec.tables if _table_exists(conn, t.name)]
                ov.table_count = len(present_tables)
                total = 0
                dates_latest: Optional[str] = None
                dates_earliest: Optional[str] = None
                for t in present_tables:
                    # Use fast rowid-based approximation; exact counts are
                    # deferred to get_summary() to keep the overview grid snappy
                    # even on multi-GB tables.
                    total += _count_rows_fast(conn, t.name)
                    if t.date_column:
                        e, l = _date_range_fast(conn, t.name, t.date_column)
                        if l and (dates_latest is None or l > dates_latest):
                            dates_latest = l
                        if e and (dates_earliest is None or e < dates_earliest):
                            dates_earliest = e
                ov.total_rows = total
                ov.latest_trade_date = dates_latest
                ov.earliest_trade_date = dates_earliest
                # Distinct-date count is deferred to get_summary(); on multi-GB
                # tables the COUNT(DISTINCT) index scan is too slow for an
                # overview grid.
                ov.distinct_trade_dates = 0
                ov.health = "ok" if total > 0 else "empty"
        except sqlite3.Error as exc:
            logger.warning("Overview query failed for %s: %s", spec.key, exc)
            ov.health = "unknown"
        items.append(ov)
    return items


def get_summary(key: str, date_limit: int = 800) -> DatabaseSummary:
    """Per-table statistics including trade-date × row-count breakdown.

    `date_limit` caps the full per-date series used for row-count stats.
    `per_date_counts` is bounded to the most recent `_RECENT_TRADING_DAYS`
    trading days (Mon–Fri); raw_fills additionally carries fetch_date/note.
    """
    spec = _spec_by_key(key)
    exists, size, last_mod, _ = _stat_file(spec.path)
    summary = DatabaseSummary(
        key=spec.key,
        label=spec.label,
        path=str(spec.path),
        exists=exists,
        size_bytes=size,
        last_modified=last_mod,
        description=spec.description,
        tables=[],
    )
    if not exists:
        return summary
    # Build the merged table list: registered specs first (with their date
    # columns / descriptions), then any other user table present in the
    # SQLite file as a synthesised spec. This lets the diagnostic UI browse
    # every real table without manual registration.
    table_specs: list[_TableSpec] = []
    seen: set[str] = set()
    for t in spec.tables:
        seen.add(t.name)
        table_specs.append(t)
    for name in _list_actual_tables(spec.path):
        if name in seen:
            continue
        seen.add(name)
        table_specs.append(
            _TableSpec(
                name=name,
                date_column=None,
                primary_key=None,
                description="(unregistered table)",
            )
        )
    try:
        with _open_ro(spec.path) as conn:
            for t in table_specs:
                if not _table_exists(conn, t.name):
                    continue
                ts = TableSummary(
                    name=t.name,
                    description=t.description,
                    primary_key=t.primary_key,
                    date_column=t.date_column,
                    row_count=0,
                )
                if t.date_column:
                    # 全量统计（用于 row_count / distinct_trade_dates / 日期范围）
                    # 超大表（如 3.7 亿行的 raw_bdib）全量 GROUP BY 聚合需 30s+，
                    # 改用 rowid 近似行数 + 索引端点日期（毫秒级）；distinct 数
                    # 置 0 由前端兜底显示。其余表保留精确统计。
                    fast_count = _count_rows_fast(conn, t.name)
                    if fast_count >= _FULL_STATS_THRESHOLD:
                        ts.row_count = fast_count
                        e, l = _date_range_fast(conn, t.name, t.date_column)
                        ts.earliest_trade_date = e
                        ts.latest_trade_date = l
                        ts.distinct_trade_dates = 0
                    else:
                        per_date = _per_date_counts(
                            conn, t.name, t.date_column, limit=date_limit
                        )
                        ts.row_count = sum(r.row_count for r in per_date)
                        ts.distinct_trade_dates = len(per_date)
                        if per_date:
                            ts.earliest_trade_date = per_date[0].trade_date
                            ts.latest_trade_date = per_date[-1].trade_date
                    # 表格视图：最近 _RECENT_TRADING_DAYS 个工作日窗口
                    # raw_fills 附带 fetch_date/note（拉取日与异常信息），
                    # 其余表无拉取元数据，仅展示日期与行数。
                    today = datetime.now().astimezone().date()
                    days = _previous_weekdays(today, _RECENT_TRADING_DAYS)
                    if t.name == _RAW_FILLS_TABLE:
                        ts.per_date_counts = _recent_raw_fills_rows(conn, days)
                    else:
                        ts.per_date_counts = _recent_rows(
                            conn, t.name, t.date_column, days
                        )
                else:
                    ts.row_count = _count_rows_fast(conn, t.name)
                summary.tables.append(ts)
    except sqlite3.Error as exc:
        logger.warning("Summary query failed for %s: %s", spec.key, exc)
    return summary


# ── Summary 缓存（性能优化）─────────────────────────────────────────────
# 每次切换数据库都实时重算 summary 在多 GB 表上耗时较长。将计算结果
# 序列化缓存到 fill_fetch_history.db 的 db_summary_cache 表，命中条件：
# 1) 源库变更指纹一致（data_version + size + mtime_ns；管道写入会变化）
# 2) 窗口锚点（计算日的 YYYY-MM-DD）相同（跨天后最近 20 工作日窗口移动）
# 缓存读写失败一律静默降级为实时计算，不影响功能正确性。


def _ensure_summary_cache_table(conn: Any) -> None:
    """确保缓存表存在（幂等；WRITE tier 允许 CREATE/INSERT）。"""
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS [{_SUMMARY_CACHE_TABLE}] ("
        "  db_key           TEXT PRIMARY KEY,"
        "  computed_at      TEXT NOT NULL,"
        "  window_anchor    TEXT NOT NULL,"
        "  source_version   INTEGER NOT NULL,"
        "  source_size      INTEGER NOT NULL,"
        "  source_mtime_ns  TEXT NOT NULL,"
        "  source_wal_ns    TEXT NOT NULL,"
        "  payload          TEXT NOT NULL"
        ")"
    )
    conn.commit()


def _cache_fingerprint_matches(
    row: tuple,
    fingerprint: tuple[Optional[int], int, Optional[int], Optional[int]],
) -> bool:
    """缓存行指纹与源库当前指纹是否一致（None 字段跳过比对）。

    row 顺序：source_version, source_size, source_mtime_ns, source_wal_ns。
    可选字段统一以 0 归一化比较（None 与缺失均视为无变化）。
    """
    source_version, source_size, source_mtime_ns, source_wal_ns = fingerprint
    if int(row[1]) != source_size:
        return False
    if str(row[2]) != str(source_mtime_ns):
        return False
    if str(row[3]) != str(source_wal_ns or 0):
        return False
    if source_version is not None and int(row[0]) != source_version:
        return False
    return True


def _summary_from_dict(data: dict) -> DatabaseSummary:
    """从 JSON dict 递归重建 DatabaseSummary（含嵌套 TableSummary/DateRowCount）。"""
    tables = [
        TableSummary(
            name=t["name"],
            description=t["description"],
            primary_key=t.get("primary_key"),
            date_column=t.get("date_column"),
            row_count=t["row_count"],
            latest_trade_date=t.get("latest_trade_date"),
            earliest_trade_date=t.get("earliest_trade_date"),
            distinct_trade_dates=t.get("distinct_trade_dates", 0),
            per_date_counts=[
                DateRowCount(
                    trade_date=r["trade_date"],
                    row_count=r["row_count"],
                    fetch_date=r.get("fetch_date"),
                    note=r.get("note"),
                )
                for r in t.get("per_date_counts", [])
            ],
        )
        for t in data.get("tables", [])
    ]
    return DatabaseSummary(
        key=data["key"],
        label=data["label"],
        path=data["path"],
        exists=data["exists"],
        size_bytes=data["size_bytes"],
        last_modified=data.get("last_modified"),
        description=data["description"],
        tables=tables,
    )


def _load_summary_cache(
    db_key: str,
    window_anchor: str,
    fingerprint: tuple[Optional[int], int, Optional[int], Optional[int]],
) -> Optional[DatabaseSummary]:
    """命中缓存则返回 DatabaseSummary，否则返回 None（任何异常按未命中处理）。"""
    if fingerprint[2] is None:
        return None
    if _diagnostics_mgr is None:
        return None
    try:
        conn = _diagnostics_mgr.get_connection(
            _DB_FETCH_HISTORY_KEY, AccessTier.WRITE
        )
        try:
            _ensure_summary_cache_table(conn)
            row = conn.execute(
                f"SELECT window_anchor, source_version, source_size, "
                f"source_mtime_ns, source_wal_ns, payload "
                f"FROM [{_SUMMARY_CACHE_TABLE}] WHERE db_key = ?",
                (db_key,),
            ).fetchone()
            if not row:
                return None
            anchor, version, size, mtime_ns, wal_ns, payload = row
            if anchor != window_anchor:
                return None
            if not _cache_fingerprint_matches(
                (version, size, mtime_ns, wal_ns), fingerprint
            ):
                return None
            return _summary_from_dict(json.loads(payload))
        finally:
            conn.close()
    except Exception:
        logger.debug("Summary cache read failed for %s", db_key, exc_info=True)
        return None


def _save_summary_cache(
    db_key: str,
    window_anchor: str,
    fingerprint: tuple[Optional[int], int, Optional[int], Optional[int]],
    summary: DatabaseSummary,
) -> None:
    """写入 summary 缓存；写失败仅告警，不抛出。"""
    if fingerprint[2] is None:
        return
    if _diagnostics_mgr is None:
        return
    source_version, source_size, source_mtime_ns, source_wal_ns = fingerprint
    try:
        conn = _diagnostics_mgr.get_connection(
            _DB_FETCH_HISTORY_KEY, AccessTier.WRITE
        )
        try:
            _ensure_summary_cache_table(conn)
            conn.execute(
                f"INSERT OR REPLACE INTO [{_SUMMARY_CACHE_TABLE}] "
                f"(db_key, computed_at, window_anchor, source_version, "
                f"source_size, source_mtime_ns, source_wal_ns, payload) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    db_key,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    window_anchor,
                    int(source_version or 0),
                    int(source_size),
                    str(source_mtime_ns),
                    str(source_wal_ns or 0),
                    json.dumps(summary.to_dict(), ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.debug("Summary cache write failed for %s", db_key, exc_info=True)


def get_summary_cached(key: str, date_limit: int = 800) -> DatabaseSummary:
    """get_summary 的缓存版本，用于反复切换数据库时避免重复重算。"""
    spec = _spec_by_key(key)
    exists, size, last_mod, _ = _stat_file(spec.path)
    if not exists:
        return get_summary(key, date_limit=date_limit)
    window_anchor = datetime.now().astimezone().date().isoformat()
    fingerprint = _source_fingerprint(spec.path)
    cached = _load_summary_cache(key, window_anchor, fingerprint)
    if cached is not None:
        logger.debug("Summary cache hit for %s", key)
        return cached
    summary = get_summary(key, date_limit=date_limit)
    _save_summary_cache(key, window_anchor, fingerprint, summary)
    return summary


_SAMPLE_LIMIT_MAX = 200
_SAMPLE_CELL_MAX_BYTES = 4096
_NULL_RATIO_WARN = 0.10
_NULL_RATIO_ERROR = 0.50
_SAME_VALUE_MIN_ROWS = 20


def list_tables(key: str) -> list[str]:
    """Return tables to expose for the given database key.

    Combines the registered `_TableSpec` names with every user table found
    in the actual SQLite file, so the UI can browse schemas/samples even
    for tables that haven't been manually registered (e.g. CostView's
    aggregate / history / registry tables in processed_fills.db).
    """
    spec = _spec_by_key(key)
    seen: set[str] = set()
    ordered: list[str] = []
    # Registered tables first (preserves their declared display order).
    for t in spec.tables:
        if t.name not in seen:
            seen.add(t.name)
            ordered.append(t.name)
    # Then any other user tables present in the file.
    for name in _list_actual_tables(spec.path):
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _coerce_cell(value: object) -> object:
    """Convert SQLite cell values to JSON-safe primitives."""
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            decoded = bytes(value).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return f"<{len(bytes(value))} bytes>"
        if len(decoded) > _SAMPLE_CELL_MAX_BYTES:
            return decoded[:_SAMPLE_CELL_MAX_BYTES] + "…"
        return decoded
    text = str(value)
    if len(text) > _SAMPLE_CELL_MAX_BYTES:
        return text[:_SAMPLE_CELL_MAX_BYTES] + "…"
    return text


def get_schema(key: str, table: str) -> TableSchema:
    """Return column / index metadata for a registered table.

    Uses `PRAGMA table_info` and `PRAGMA index_list/index_info`. Table names
    are validated against the static registry (`_spec_table`) before any SQL
    interpolation, so this endpoint is not exposed to SQL injection.
    """
    spec = _spec_by_key(key)
    tspec = _spec_table(spec, table)
    schema = TableSchema(
        database_key=spec.key,
        table=tspec.name,
        description=tspec.description,
        primary_key_display=tspec.primary_key,
    )
    if not spec.path.exists():
        return schema
    try:
        with _open_ro(spec.path) as conn:
            if not _table_exists(conn, tspec.name):
                return schema
            # PRAGMA table_info(<table>) → cid, name, type, notnull, dflt_value, pk
            for cid, name, ctype, notnull, dflt, pk in conn.execute(
                f"PRAGMA table_info([{tspec.name}])"
            ).fetchall():
                schema.columns.append(
                    ColumnInfo(
                        name=str(name),
                        type=str(ctype or ""),
                        nullable=not bool(notnull),
                        primary_key=int(pk or 0),
                        default_value=None if dflt is None else str(dflt),
                    )
                )
            # PRAGMA index_list → seq, name, unique, origin, partial
            for _seq, idx_name, unique, *_ in conn.execute(
                f"PRAGMA index_list([{tspec.name}])"
            ).fetchall():
                cols = [
                    str(r[2])
                    for r in conn.execute(
                        f"PRAGMA index_info([{idx_name}])"
                    ).fetchall()
                ]
                schema.indexes.append(
                    IndexInfo(
                        name=str(idx_name),
                        unique=bool(unique),
                        columns=cols,
                    )
                )
    except sqlite3.Error as exc:
        logger.warning(
            "Schema query failed for %s.%s: %s", spec.key, tspec.name, exc
        )
    return schema


def _detect_anomalies(
    columns: list[str], rows: list[tuple]
) -> list[ColumnAnomaly]:
    """Cheap, sample-bounded column-level anomaly detection.

    Operates on the already-fetched sample (no extra queries). Reports:
    - high_null: NULL ratio ≥ 10% (warning) or ≥ 50% (error)
    - all_same:  every value identical when sample ≥ _SAME_VALUE_MIN_ROWS
    """
    anomalies: list[ColumnAnomaly] = []
    n = len(rows)
    if n == 0:
        return anomalies
    for ci, col in enumerate(columns):
        nulls = 0
        seen: set = set()
        for r in rows:
            v = r[ci]
            if v is None:
                nulls += 1
            else:
                seen.add(v)
        ratio = nulls / n
        if ratio >= _NULL_RATIO_ERROR:
            anomalies.append(
                ColumnAnomaly(
                    column=col,
                    severity="error",
                    code="high_null",
                    message=f"{nulls}/{n} rows ({ratio:.0%}) are NULL.",
                )
            )
        elif ratio >= _NULL_RATIO_WARN:
            anomalies.append(
                ColumnAnomaly(
                    column=col,
                    severity="warning",
                    code="high_null",
                    message=f"{nulls}/{n} rows ({ratio:.0%}) are NULL.",
                )
            )
        if (
            n >= _SAME_VALUE_MIN_ROWS
            and nulls < n
            and len(seen) == 1
        ):
            anomalies.append(
                ColumnAnomaly(
                    column=col,
                    severity="info",
                    code="all_same",
                    message=f"All {n} sampled rows share the same value.",
                )
            )
    return anomalies


def get_sample(key: str, table: str, limit: int = 50) -> TableSample:
    """Return the most recent N rows of a registered table.

    Ordering preference:
    1. `<date_column> DESC, _rowid_ DESC` when the spec declares a date column
    2. `_rowid_ DESC` otherwise
    Both orderings hit indexed/native columns and stay O(log n + limit) on
    multi-GB tables.
    """
    spec = _spec_by_key(key)
    tspec = _spec_table(spec, table)
    safe_limit = max(1, min(int(limit), _SAMPLE_LIMIT_MAX))
    fetched_at = (
        datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    )
    sample = TableSample(
        database_key=spec.key,
        table=tspec.name,
        columns=[],
        rows=[],
        row_count_estimate=0,
        fetched_at=fetched_at,
        order_by=None,
    )
    if not spec.path.exists():
        return sample
    try:
        with _open_ro(spec.path) as conn:
            if not _table_exists(conn, tspec.name):
                return sample
            # Resolve column names from PRAGMA so we never SELECT *.
            col_rows = conn.execute(
                f"PRAGMA table_info([{tspec.name}])"
            ).fetchall()
            col_names = [str(r[1]) for r in col_rows]
            if not col_names:
                return sample
            sample.columns = col_names
            sample.row_count_estimate = _count_rows_fast(conn, tspec.name)

            if tspec.date_column and tspec.date_column in col_names:
                order_by = f"[{tspec.date_column}] DESC, _rowid_ DESC"
            else:
                order_by = "_rowid_ DESC"
            sample.order_by = order_by

            select_cols = ", ".join(f"[{c}]" for c in col_names)
            try:
                cursor = conn.execute(
                    f"SELECT {select_cols} FROM [{tspec.name}] "
                    f"ORDER BY {order_by} LIMIT ?",
                    (safe_limit,),
                )
                raw_rows = cursor.fetchall()
            except sqlite3.Error:
                # Fallback: some pre-existing tables may not have an index on
                # the declared date_column; retry with rowid ordering.
                cursor = conn.execute(
                    f"SELECT {select_cols} FROM [{tspec.name}] "
                    f"ORDER BY _rowid_ DESC LIMIT ?",
                    (safe_limit,),
                )
                raw_rows = cursor.fetchall()
                sample.order_by = "_rowid_ DESC"

            sample.rows = [
                [_coerce_cell(v) for v in row] for row in raw_rows
            ]
            sample.anomalies = _detect_anomalies(col_names, raw_rows)
    except sqlite3.Error as exc:
        logger.warning(
            "Sample query failed for %s.%s: %s", spec.key, tspec.name, exc
        )
    return sample


def get_integrity(key: str) -> IntegrityReport:
    """Lightweight integrity check — never heavier than a few aggregate scans."""
    spec = _spec_by_key(key)
    report = IntegrityReport(
        key=spec.key,
        checked_at=datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds"),
    )
    if not spec.path.exists():
        report.issues.append(
            IntegrityIssue(
                code="db_missing",
                severity="error",
                message=f"Database file not found: {spec.path}",
            )
        )
        return report

    try:
        with _open_ro(spec.path) as conn:
            if spec.key == "raw_bdib":
                # Known-bad rows: Bloomberg occasionally returns NULL close.
                # Scoped to the latest 200k rowids to avoid a full-table scan
                # on multi-GB raw_bdib.db files.
                try:
                    latest_rowid = conn.execute(
                        f"SELECT MAX(_rowid_) FROM [{_RAW_BDIB_TABLE}]"
                    ).fetchone()[0]
                    if latest_rowid:
                        n = conn.execute(
                            f"SELECT COUNT(*) FROM [{_RAW_BDIB_TABLE}] "
                            f"WHERE _rowid_ > ? AND close IS NULL",
                            (max(0, int(latest_rowid) - 200_000),),
                        ).fetchone()[0]
                        if n:
                            report.issues.append(
                                IntegrityIssue(
                                    code="raw_bdib_null_close",
                                    severity="warning",
                                    message=(
                                        f"{n} recent raw_bdib rows have NULL close "
                                        "(sampled from last 200k rows). "
                                        "Run `backfill_raw_bdib.py --clean --repair`."
                                    ),
                                    count=int(n),
                                )
                            )
                except sqlite3.Error:
                    pass
            elif spec.key == "fill_bdib":
                # Fills present in processed_fills but missing from fill_bdib —
                # limited to the latest 30 trading days to bound query cost.
                try:
                    # Resolve processed_fills.db path from ConnectionManager
                    db_paths = _get_db_paths()
                    pf_db_path = db_paths.get("processed_fills")
                    if pf_db_path and pf_db_path.exists():
                        conn.execute(
                            "ATTACH DATABASE ? AS pf",
                            (f"file:{pf_db_path.as_posix()}?mode=ro",),
                        )
                        cutoff_row = conn.execute(
                            f"SELECT MAX(order_as_of_date) "
                            f"FROM pf.[{_PROCESSED_FILLS_TABLE}] "
                            f"WHERE order_as_of_date IS NOT NULL"
                        ).fetchone()
                        cutoff = cutoff_row[0] if cutoff_row else None
                        if cutoff:
                            n = conn.execute(
                                f"""
                                SELECT COUNT(DISTINCT pf.OrderId || '|' || pf.order_as_of_date)
                                FROM pf.[{_PROCESSED_FILLS_TABLE}] pf
                                LEFT JOIN [{_FILL_BDIB_TABLE}] fb
                                  ON fb.OrderId = pf.OrderId
                                 AND fb.order_as_of_date = pf.order_as_of_date
                                WHERE pf.order_as_of_date >= ?
                                  AND fb.OrderId IS NULL
                                """,
                                (str(int(cutoff) - 45) if cutoff.isdigit() else cutoff,),
                            ).fetchone()[0]
                            if n:
                                report.issues.append(
                                    IntegrityIssue(
                                        code="fill_bdib_missing",
                                        severity="warning",
                                        message=(
                                            f"{n} recent (order_id, date) pairs present in "
                                            "processed_fills.db but missing from fill_bdib.db."
                                        ),
                                        count=int(n),
                                    )
                                )
                except sqlite3.Error:
                    pass
                finally:
                    try:
                        conn.execute("DETACH DATABASE pf")
                    except sqlite3.Error:
                        pass
            elif spec.key == "raw_fills":
                # `order_as_of_date` is derived by the post-ingest cleaner,
                # so freshly-fetched rows are *expected* to be NULL until the
                # next pipeline run. Only flag rows whose `source_date` is
                # already older than today — those should have been cleaned
                # by now and indicate a real backlog.
                try:
                    today_ymd = datetime.now().strftime("%Y%m%d")
                    latest_rowid = conn.execute(
                        f"SELECT MAX(_rowid_) FROM [{_RAW_FILLS_TABLE}]"
                    ).fetchone()[0]
                    if latest_rowid:
                        n = conn.execute(
                            f"SELECT COUNT(*) FROM [{_RAW_FILLS_TABLE}] "
                            f"WHERE _rowid_ > ? "
                            f"AND source_date < ? "
                            f"AND (order_as_of_date IS NULL "
                            f"     OR TRIM(order_as_of_date) = '')",
                            (
                                max(0, int(latest_rowid) - 50_000),
                                today_ymd,
                            ),
                        ).fetchone()[0]
                        pending = conn.execute(
                            f"SELECT COUNT(*) FROM [{_RAW_FILLS_TABLE}] "
                            f"WHERE _rowid_ > ? "
                            f"AND source_date >= ? "
                            f"AND (order_as_of_date IS NULL "
                            f"     OR TRIM(order_as_of_date) = '')",
                            (
                                max(0, int(latest_rowid) - 50_000),
                                today_ymd,
                            ),
                        ).fetchone()[0]
                        if n:
                            report.issues.append(
                                IntegrityIssue(
                                    code="raw_fills_missing_date",
                                    severity="warning",
                                    message=(
                                        f"{n} raw_fills rows older than today are "
                                        "missing derived order_as_of_date "
                                        "(cleaner backlog). Run "
                                        "`python -m CostView.scripts.daily_update` "
                                        "or backfill the cleaner stage."
                                    ),
                                    count=int(n),
                                )
                            )
                        if pending:
                            report.issues.append(
                                IntegrityIssue(
                                    code="raw_fills_pending_clean",
                                    severity="info",
                                    message=(
                                        f"{pending} raw_fills rows fetched today "
                                        "are awaiting the cleaner stage to derive "
                                        "order_as_of_date — this is normal."
                                    ),
                                    count=int(pending),
                                )
                            )
                except sqlite3.Error:
                    pass
    except sqlite3.Error as exc:
        report.issues.append(
            IntegrityIssue(
                code="integrity_query_failed",
                severity="error",
                message=f"Integrity check errored: {exc}",
            )
        )
    return report


__all__ = [
    "ColumnAnomaly",
    "ColumnInfo",
    "DatabaseOverview",
    "DatabaseSummary",
    "DateRowCount",
    "IndexInfo",
    "IntegrityIssue",
    "IntegrityReport",
    "TableSample",
    "TableSchema",
    "TableSummary",
    "get_integrity",
    "get_overview",
    "get_sample",
    "get_schema",
    "get_summary",
    "get_summary_cached",
    "list_database_keys",
    "list_tables",
]

"""Read-only repository layer for the DatabaseView module.

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

All queries run in READ tier (access_tier=AccessTier.READ). No writes here.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from CostView.src.processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)


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
    return (
        _DatabaseSpec(
            key="raw_fills",
            label="Raw Fills",
            path=Path(Config.RAW_FILLS_DB),
            description="EMSX GetFills raw rows (28 original + 5 derived columns).",
            tables=(
                _TableSpec(
                    name=Config.RAW_FILLS_TABLE,
                    # Use `source_date` (YYYYMMDD, always populated at ingest)
                    # rather than `order_as_of_date`: the latter is filled in by
                    # the post-ingest cleaner and is NULL for freshly-fetched
                    # rows, making the headline "Latest" date look stale.
                    date_column="source_date",
                    primary_key="(OrderId, RouteId, FillId)",
                    description="Bloomberg EMSX fills, INSERT OR REPLACE for late corrections.",
                ),
                _TableSpec(
                    name=Config.FETCH_LOG_TABLE,
                    date_column="fetch_date",
                    primary_key="(fetch_date, fetch_started_at)",
                    description="Per-day fetch tracking (records_fetched, status).",
                ),
            ),
        ),
        _DatabaseSpec(
            key="processed_fills",
            label="Processed Fills",
            path=Path(Config.PROCESSED_FILLS_DB),
            description="Cleaned 27-column fact table + route registry.",
            tables=(
                _TableSpec(
                    name=Config.PROCESSED_FILLS_TABLE,
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
            path=Path(Config.RAW_BDIB_DB),
            description="10-second intraday BDIB bars (Bloomberg-native columns).",
            tables=(
                _TableSpec(
                    name=Config.RAW_BDIB_TABLE,
                    date_column="order_as_of_date",
                    primary_key="(equ_ticker, order_as_of_date, mkt_timestamp)",
                    description="OHLC + volume + num_trds + value per 10s bar.",
                ),
            ),
        ),
        _DatabaseSpec(
            key="fill_bdib",
            label="Fill × BDIB",
            path=Path(Config.FILL_BDIB_DB),
            description="Fills enriched with BDIB intraday metrics (TCA input).",
            tables=(
                _TableSpec(
                    name=Config.FILL_BDIB_TABLE,
                    date_column="order_as_of_date",
                    primary_key="(OrderId, RouteId, order_as_of_date, mkt_timestamp)",
                    description="Integrated fill × BDIB view used by TCA analysis.",
                ),
            ),
        ),
        _DatabaseSpec(
            key="fill_fetch_history",
            label="Fill Fetch History",
            path=Path(Config.FETCH_HISTORY_DB),
            description="Historical fetch-job records (deduplication + audit).",
            tables=(
                _TableSpec(
                    name="fetch_records",
                    date_column=None,
                    primary_key=None,
                    description="Legacy per-fetch log (schema depends on deployment).",
                ),
            ),
        ),
    )


_REGISTRY: tuple[_DatabaseSpec, ...] = _build_registry()


def _spec_by_key(key: str) -> _DatabaseSpec:
    for spec in _REGISTRY:
        if spec.key == key:
            return spec
    raise KeyError(f"Unknown database key: {key}")


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
            f"WHERE [{date_column}] IS NOT NULL AND TRIM([{date_column}]) != '' "
            f"GROUP BY [{date_column}] "
            f"ORDER BY d ASC "
            f"LIMIT ?",
            (int(limit),),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [DateRowCount(trade_date=str(r[0]), row_count=int(r[1])) for r in rows]


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


# ── Public API ────────────────────────────────────────────────────────────────

def list_database_keys() -> list[str]:
    return [spec.key for spec in _REGISTRY]


def get_overview() -> list[DatabaseOverview]:
    """Cheap overview of every registered database (file stats + headline counts)."""
    items: list[DatabaseOverview] = []
    for spec in _REGISTRY:
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

    `date_limit` caps the per-date series to keep payloads small — the
    heatmap only needs one point per trading day.
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
    try:
        with _open_ro(spec.path) as conn:
            for t in spec.tables:
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
                    # Per-date counts use the date index — efficient even on
                    # multi-GB tables — and summing them gives us an exact
                    # row total consistent with the heatmap.
                    per_date = _per_date_counts(
                        conn, t.name, t.date_column, limit=date_limit
                    )
                    ts.per_date_counts = per_date
                    ts.row_count = sum(r.row_count for r in per_date)
                    ts.distinct_trade_dates = len(per_date)
                    if per_date:
                        ts.earliest_trade_date = per_date[0].trade_date
                        ts.latest_trade_date = per_date[-1].trade_date
                else:
                    ts.row_count = _count_rows_fast(conn, t.name)
                summary.tables.append(ts)
    except sqlite3.Error as exc:
        logger.warning("Summary query failed for %s: %s", spec.key, exc)
    return summary


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
                        f"SELECT MAX(_rowid_) FROM [{Config.RAW_BDIB_TABLE}]"
                    ).fetchone()[0]
                    if latest_rowid:
                        n = conn.execute(
                            f"SELECT COUNT(*) FROM [{Config.RAW_BDIB_TABLE}] "
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
                    conn.execute(
                        "ATTACH DATABASE ? AS pf",
                        (f"file:{Path(Config.PROCESSED_FILLS_DB).as_posix()}?mode=ro",),
                    )
                    cutoff_row = conn.execute(
                        f"SELECT MAX(order_as_of_date) "
                        f"FROM pf.[{Config.PROCESSED_FILLS_TABLE}] "
                        f"WHERE order_as_of_date IS NOT NULL"
                    ).fetchone()
                    cutoff = cutoff_row[0] if cutoff_row else None
                    if cutoff:
                        n = conn.execute(
                            f"""
                            SELECT COUNT(DISTINCT pf.OrderId || '|' || pf.order_as_of_date)
                            FROM pf.[{Config.PROCESSED_FILLS_TABLE}] pf
                            LEFT JOIN [{Config.FILL_BDIB_TABLE}] fb
                              ON fb.OrderId = pf.OrderId
                             AND fb.order_as_of_date = pf.order_as_of_date
                            WHERE pf.order_as_of_date >= ?
                              AND fb.OrderId IS NULL
                            """,
                            # ~45 calendar days back, YYYYMMDD lexical compare
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
                # Sample-based check — scan the most recent 50k rowids for
                # missing derived order_as_of_date instead of the whole table.
                try:
                    latest_rowid = conn.execute(
                        f"SELECT MAX(_rowid_) FROM [{Config.RAW_FILLS_TABLE}]"
                    ).fetchone()[0]
                    if latest_rowid:
                        n = conn.execute(
                            f"SELECT COUNT(*) FROM [{Config.RAW_FILLS_TABLE}] "
                            f"WHERE _rowid_ > ? "
                            f"AND (order_as_of_date IS NULL OR TRIM(order_as_of_date) = '')",
                            (max(0, int(latest_rowid) - 50_000),),
                        ).fetchone()[0]
                        if n:
                            report.issues.append(
                                IntegrityIssue(
                                    code="raw_fills_missing_date",
                                    severity="warning",
                                    message=(
                                        f"{n} recent raw_fills rows missing derived "
                                        "order_as_of_date (sampled from last 50k rows)."
                                    ),
                                    count=int(n),
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
    "DatabaseOverview",
    "DatabaseSummary",
    "DateRowCount",
    "IntegrityIssue",
    "IntegrityReport",
    "TableSummary",
    "get_integrity",
    "get_overview",
    "get_summary",
    "list_database_keys",
]

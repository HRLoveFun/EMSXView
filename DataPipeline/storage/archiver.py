"""Data lifecycle management — archive expired historical data.

Moves rows older than retention_months from main databases into compressed
archive databases, then VACUUMs the source to reclaim disk space.

Usage::

    from DataPipeline.storage.archiver import DataArchiver
    from DataPipeline.config import Config

    archiver = DataArchiver(Config.DATA_DIR)
    archiver.archive_expired("processed_fills", dry_run=True)  # preview
    archiver.archive_expired("processed_fills")                 # execute
    archiver.archive_all()
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Per-table retention config: date column name and retention in months.
ARCHIVE_CONFIG: Dict[str, Dict[str, int]] = {
    "raw_fills":          {"retention_months": 12},
    "processed_fills":    {"retention_months": 24},
    "agg_fills_10s":      {"retention_months": 24},
    "agg_fills_1min":     {"retention_months": 12},
    "route_event_history":{"retention_months": 36},
    "order_history":      {"retention_months": 36},
    "route_history":      {"retention_months": 36},
    "raw_bdib":           {"retention_months": 12},
    "processed_raw_bdib": {"retention_months": 12},
    "fill_bdib":          {"retention_months": 24},
}

ARCHIVE_DIR_NAME = "archive"


def _vacuum_incremental(conn: sqlite3.Connection, db_name: str) -> None:
    """增量VACUUM — 设置auto_vacuum=INCREMENTAL后逐页回收 (Phase C2).

    替代全量VACUUM, 避免大库长时间被锁。
    """
    logger.info("VACUUM %s (incremental)...", db_name)
    conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
    freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
    if freelist > 0:
        conn.execute(f"PRAGMA incremental_vacuum({freelist})")
        logger.info("  Freed %d pages from %s", freelist, db_name)
    else:
        logger.info("  No free pages in %s", db_name)


class DataArchiver:

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._archive_dir = self._data_dir / ARCHIVE_DIR_NAME
        self._archive_dir.mkdir(parents=True, exist_ok=True)

    def archive_expired(
        self,
        db_name: str,
        date_col: Optional[str] = None,
        retention_months: Optional[int] = None,
        dry_run: bool = False,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, int]:
        db_path = self._data_dir / f"{db_name}.db"
        if not db_path.exists():
            logger.warning("Database not found: %s", db_path)
            return {}

        # 心跳：开始处理该 DB 时回调（防止归档步骤整体耗时 > 5 分钟
        # 导致前端 watchdog 误判为 stalled）
        if progress_callback is not None:
            try:
                progress_callback(db_name, "start", 0)
            except Exception:
                logger.debug("archive progress_callback (start) failed", exc_info=True)

        archive_path = self._archive_dir / f"{db_name}_archive.db"
        retention = retention_months or 24

        cutoff = datetime.now().replace(day=1)
        for _ in range(retention):
            if cutoff.month == 1:
                cutoff = cutoff.replace(year=cutoff.year - 1, month=12)
            else:
                cutoff = cutoff.replace(month=cutoff.month - 1)
        cutoff_str = cutoff.strftime("%Y%m%d")

        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(archive_path))
        dst.execute("PRAGMA journal_mode=WAL")
        results: Dict[str, int] = {}

        try:
            tables = [
                t[0] for t in
                src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            ]

            for table in tables:
                actual_date_col = date_col or self._detect_date_column(src, table)
                if not actual_date_col:
                    continue

                if not self._ensure_table_in_archive(src, dst, table):
                    continue

                count = src.execute(
                    f"SELECT COUNT(*) FROM [{table}] WHERE [{actual_date_col}] < ?",
                    (cutoff_str,),
                ).fetchone()[0]

                if count == 0:
                    continue

                if not dry_run:
                    self._migrate_data(src, dst, table, actual_date_col, cutoff_str)

                results[table] = count
                logger.info(
                    "%s %d rows from %s.%s (cutoff=%s)",
                    "Would archive" if dry_run else "Archived",
                    count, db_name, table, cutoff_str,
                )

            if not dry_run and results:
                _vacuum_incremental(src, db_name)
        finally:
            src.close()
            dst.close()

        # 心跳：该 DB 处理完成时回调
        if progress_callback is not None:
            try:
                total_rows = sum(results.values()) if results else 0
                progress_callback(db_name, "done", total_rows)
            except Exception:
                logger.debug("archive progress_callback (done) failed", exc_info=True)

        return results

    def archive_all(
        self,
        dry_run: bool = False,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Dict[str, int]]:
        all_results: Dict[str, Dict[str, int]] = {}
        for db_name in ("processed_fills", "raw_fills", "raw_bdib",
                         "processed_raw_bdib", "fill_bdib"):
            try:
                res = self.archive_expired(
                    db_name, dry_run=dry_run, progress_callback=progress_callback,
                )
                if res:
                    all_results[db_name] = res
            except Exception:
                logger.exception("Archive failed for %s", db_name)
        return all_results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_date_column(conn: sqlite3.Connection, table: str) -> Optional[str]:
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info('{table}')")]
        for candidate in ("order_as_of_date", "trade_date", "event_date", "source_date"):
            if candidate in cols:
                return candidate
        return None

    @staticmethod
    def _ensure_table_in_archive(
        src: sqlite3.Connection, dst: sqlite3.Connection, table: str
    ) -> bool:
        exists = dst.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if exists:
            return True
        create_sql = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not create_sql:
            return False
        dst.execute(create_sql[0])
        return True

    @staticmethod
    def _migrate_data(
        src: sqlite3.Connection,
        dst: sqlite3.Connection,
        table: str,
        date_col: str,
        cutoff_str: str,
    ) -> None:
        """Safe two-step migration with idempotent archive insert.

        Uses separate transactions to avoid the cross-DB atomicity
        problem: if the process crashes between archive COMMIT and
        source DELETE, ``INSERT OR IGNORE`` prevents duplicate rows
        on retry (PK-based conflict resolution).

        Semantics: at-least-once on archive side — retries are safe.
        """
        # Step 1 — insert into archive idempotently
        dst.execute("BEGIN IMMEDIATE")
        try:
            dst.execute(
                f"INSERT OR IGNORE INTO [{table}] "
                f"SELECT * FROM [{table}] WHERE [{date_col}] < ?",
                (cutoff_str,),
            )
            dst.execute("COMMIT")
        except Exception:
            dst.execute("ROLLBACK")
            raise

        # Step 2 — delete from source (only after archive insert succeeded)
        src.execute("BEGIN IMMEDIATE")
        try:
            src.execute(
                f"DELETE FROM [{table}] WHERE [{date_col}] < ?",
                (cutoff_str,),
            )
            src.execute("COMMIT")
        except Exception:
            src.execute("ROLLBACK")
            raise

    def list_archives(self) -> List[Path]:
        return sorted(self._archive_dir.glob("*_archive.db"))

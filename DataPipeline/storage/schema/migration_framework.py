"""Unified migration framework extending formal migrations to all databases.

Works alongside the existing MigrationManager — provides MigrationPlan,
Migration data structures, and a MigrationRunner that discovers and applies
versioned SQL migration files for any database via PRAGMA user_version.

Migration files live in subdirectories named after the DB key:
    schema/migrations/raw_fills/v0_to_v1.sql
    schema/migrations/raw_fills/v1_to_v2.sql
    ...

Each migration file MUST be self-contained forward-only DDL with
``BEGIN; ... COMMIT;`` wrapping.  Idempotent via IF NOT EXISTS clauses.

Concurrency safety: ``migrate()`` acquires an exclusive file lock
(``.migration.lock``) before reading ``user_version`` to prevent races
when multiple processes or workers start simultaneously.

Usage::

    from DataPipeline.storage.schema.migration_framework import (
        MigrationRunner,
    )
    runner = MigrationRunner.discover()
    runner.migrate("processed_fills")
    status = runner.health_check()
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from DataPipeline.config import Config
from DataPipeline.storage.connection import ConnectionManager

logger = logging.getLogger(__name__)

_MIGRATIONS_ROOT = Path(__file__).resolve().parent / "migrations"

_MIGRATION_NAME_RE = re.compile(r"^v(\d+)_to_v(\d+)\.sql$")

MIGRATION_LOCK_TIMEOUT_SEC = 30
MIGRATION_LOCK_RETRY_INTERVAL_SEC = 1.0

_EXPECTED_CURRENT: Dict[str, int] = {
    "raw_fills": 4,  # v3->v4: order_as_of_date NOT NULL 约束 (2026-07-02 P1)
    "processed_fills": 1,
    "raw_bdib": 1,
    "processed_raw_bdib": 1,
    "fill_bdib": 1,
    "regime": 3,
}


@dataclass
class Migration:
    version: int
    description: str
    sql_path: Path
    up_sql: str = field(repr=False)

    @classmethod
    def from_file(cls, path: Path, description: str = "") -> "Migration":
        m = _MIGRATION_NAME_RE.match(path.name)
        if not m:
            raise ValueError(f"Bad migration filename: {path.name}")
        from_v = int(m.group(1))
        to_v = int(m.group(2))
        if to_v != from_v + 1:
            raise ValueError(f"Migrations must step +1: {path.name}")
        up_sql = path.read_text(encoding="utf-8")
        return cls(version=to_v, description=description or f"{path.stem}", sql_path=path, up_sql=up_sql)


@dataclass
class MigrationPlan:
    db_key: str
    db_path: Path
    migrations: List[Migration] = field(default_factory=list)


class MigrationRunner:

    def __init__(self, plans: List[MigrationPlan]) -> None:
        self._plans: Dict[str, MigrationPlan] = {p.db_key: p for p in plans}

    @classmethod
    def discover(cls, connection_manager: Optional[ConnectionManager] = None) -> "MigrationRunner":
        """Auto-discover migration plans from subdirectory layout.

        Scans schema/migrations/<db_key>/vN_to_vN+1.sql for each database
        that has a migration subdirectory.
        """
        cfg = Config()
        plans: List[MigrationPlan] = []
        db_path_map = {
            "raw_fills": cfg.RAW_FILLS_DB,
            "processed_fills": cfg.PROCESSED_FILLS_DB,
            "raw_bdib": cfg.RAW_BDIB_DB,
            "processed_raw_bdib": cfg.PROCESSED_RAW_BDIB_DB,
            "fill_bdib": cfg.FILL_BDIB_DB,
            "regime": cfg.DATA_DIR / "regime.db",
        }
        for db_key, db_path in db_path_map.items():
            mig_dir = _MIGRATIONS_ROOT / db_key
            if not mig_dir.is_dir():
                continue
            sql_files = sorted(mig_dir.glob("v*_to_v*.sql"))
            if not sql_files:
                continue
            plan = MigrationPlan(db_key=db_key, db_path=db_path)
            for sf in sql_files:
                try:
                    plan.migrations.append(Migration.from_file(sf))
                except ValueError:
                    logger.warning("Skipping bad migration file: %s", sf.name)
            plans.append(plan)
        return cls(plans)

    def get_current_version(self, db_key: str) -> int:
        plan = self._plans[db_key]
        conn = sqlite3.connect(str(plan.db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()

    def migrate(self, db_key: str, target_version: Optional[int] = None) -> int:
        """Apply pending migrations under exclusive file lock.

        Uses atomic lock-file creation (``os.O_CREAT | os.O_EXCL``) as a
        cross-platform mutex.  If another process already holds the lock
        the caller blocks for up to ``MIGRATION_LOCK_TIMEOUT_SEC``.
        """
        plan = self._plans[db_key]
        lock_path = Path(str(plan.db_path) + ".migration.lock")

        fd = self._acquire_lock(lock_path, db_key)
        try:
            conn = sqlite3.connect(str(plan.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

            try:
                current = conn.execute("PRAGMA user_version").fetchone()[0]
                pending = [
                    m for m in plan.migrations
                    if m.version > current
                    and (target_version is None or m.version <= target_version)
                ]
                if not pending:
                    logger.debug("%s already at v%d, nothing to migrate", db_key, current)
                    return current

                logger.info(
                    "Migrating %s from v%d to v%d (%d steps)",
                    db_key, current, pending[-1].version, len(pending),
                )
                for m in pending:
                    conn.executescript(m.up_sql)
                    conn.execute(f"PRAGMA user_version = {m.version}")
                    logger.info("  %s v%d applied", db_key, m.version)

                final = conn.execute("PRAGMA user_version").fetchone()[0]
                return final
            except Exception:
                logger.exception("Migration failed for %s", db_key)
                raise
            finally:
                conn.close()
        finally:
            self._release_lock(fd, lock_path)

    def migrate_all(self) -> Dict[str, int]:
        results: Dict[str, int] = {}
        for db_key in self._plans:
            try:
                results[db_key] = self.migrate(db_key)
            except Exception:
                logger.exception("Migration failed for %s", db_key)
                results[db_key] = -1
        return results

    def health_check(self) -> Dict[str, str]:
        results: Dict[str, str] = {}
        for db_key, plan in self._plans.items():
            try:
                if not plan.db_path.exists():
                    results[db_key] = "missing"
                    continue
                current = self.get_current_version(db_key)
                expected = _EXPECTED_CURRENT.get(db_key, 0)
                if current < expected:
                    results[db_key] = f"behind (v{current} -> v{expected})"
                elif current == expected:
                    results[db_key] = "current"
                else:
                    results[db_key] = f"ahead (v{current} > expected v{expected})"
            except Exception as e:
                results[db_key] = f"error: {e}"
        return results

    def ensure_current(self, db_key: str) -> int:
        return self.migrate(db_key)

    # ------------------------------------------------------------------
    # Lock helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _acquire_lock(lock_path: Path, db_key: str) -> int:
        """Acquire exclusive migration lock via atomic file creation.

        Uses ``os.O_CREAT | os.O_EXCL`` — the kernel guarantees that only
        one process can create a file with these flags.  Retries for up to
        ``MIGRATION_LOCK_TIMEOUT_SEC`` with back-off.

        Returns the file descriptor to be released by ``_release_lock``.
        """
        deadline = time.monotonic() + MIGRATION_LOCK_TIMEOUT_SEC
        while True:
            try:
                fd = os.open(
                    str(lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                return fd
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"Migration lock timeout for {db_key} "
                        f"after {MIGRATION_LOCK_TIMEOUT_SEC}s"
                    )
                time.sleep(MIGRATION_LOCK_RETRY_INTERVAL_SEC)

    @staticmethod
    def _release_lock(fd: int, lock_path: Path) -> None:
        os.close(fd)
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass

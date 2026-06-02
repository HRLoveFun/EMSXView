"""Database backup and recovery manager.

Provides consistent full backups via sqlite3 .backup API with optional
pre-backup WAL checkpoint for compact output.  SHA-256 integrity verification,
retention policy enforcement, and point-in-time restore for all 7 EMSXView
databases.

WAL incremental backups have been **removed** — SQLite's WAL pages are
only meaningful when paired with the exact DB file state at checkpoint
time.  Copying a standalone ``-wal`` file produces an unrestorable
artifact.  The ``sqlite3.Connection.backup()`` API already reads WAL
dirty pages internally, producing a self-consistent snapshot without
requiring a separate WAL backup.

Usage::

    from DataPipeline.storage.backup import BackupManager
    from DataPipeline.config import Config

    mgr = BackupManager(Config.DATA_DIR)
    mgr.backup_all()
    mgr.restore("processed_fills")
    mgr.cleanup_expired()
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from DataPipeline.config import (
    Config,
    DB_FETCH_HISTORY,
    DB_FILL_BDIB,
    DB_PROCESSED_FILLS,
    DB_PROCESSED_RAW_BDIB,
    DB_RAW_BDIB,
    DB_RAW_FILLS,
    DB_REGIME,
)
from DataPipeline.storage.connection import ConnectionManager

logger = logging.getLogger(__name__)

BACKUP_RETENTION_DAYS = 30
BACKUP_DIR_NAME = "backups"


class BackupManager:

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        connection_manager: Optional[ConnectionManager] = None,
        retention_days: int = BACKUP_RETENTION_DAYS,
    ) -> None:
        cfg = Config()
        self._data_dir = data_dir or cfg.DATA_DIR
        self._backup_root = self._data_dir / BACKUP_DIR_NAME
        self._backup_root.mkdir(parents=True, exist_ok=True)
        self._retention = retention_days
        self._mgr = connection_manager or ConnectionManager()
        self._db_paths: Dict[str, Path] = {
            DB_RAW_FILLS: cfg.RAW_FILLS_DB,
            DB_PROCESSED_FILLS: cfg.PROCESSED_FILLS_DB,
            DB_RAW_BDIB: cfg.RAW_BDIB_DB,
            DB_PROCESSED_RAW_BDIB: cfg.PROCESSED_RAW_BDIB_DB,
            DB_FILL_BDIB: cfg.FILL_BDIB_DB,
            DB_REGIME: cfg.DATA_DIR / "regime.db",
            DB_FETCH_HISTORY: cfg.FETCH_HISTORY_DB,
        }

    @property
    def connection_manager(self) -> ConnectionManager:
        return self._mgr

    # ------------------------------------------------------------------
    # Full backup
    # ------------------------------------------------------------------

    def full_backup(self, db_name: str) -> Path:
        src = self._db_paths[db_name]
        if not src.exists():
            raise FileNotFoundError(f"Database not found: {src}")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest_dir = self._backup_root / db_name / "full"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{src.stem}_{timestamp}.db"

        src_conn = sqlite3.connect(str(src))
        dst_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dst_conn)
        finally:
            src_conn.close()
            dst_conn.close()

        checksum = self._sha256_file(dest)
        meta = {
            "db_name": db_name,
            "timestamp": timestamp,
            "source_path": str(src),
            "backup_path": str(dest),
            "checksum_sha256": checksum,
            "backup_type": "full",
            "source_size_bytes": src.stat().st_size,
        }
        self._write_meta(dest_dir / f"{src.stem}_{timestamp}.meta.json", meta)
        logger.info(
            "Full backup: %s -> %s (sha256=%s, size=%d)",
            db_name, dest.name, checksum[:16], src.stat().st_size,
        )
        return dest

    def backup_all(self) -> Dict[str, Optional[Path]]:
        results: Dict[str, Optional[Path]] = {}
        for db_name in self._db_paths:
            try:
                results[db_name] = self.full_backup(db_name)
            except Exception:
                logger.exception("Full backup failed for %s", db_name)
                results[db_name] = None
        return results

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore(self, db_name: str, timestamp: Optional[str] = None) -> Path:
        full_dir = self._backup_root / db_name / "full"
        if not full_dir.exists():
            raise FileNotFoundError(f"No backups found for {db_name}")

        backups = sorted(full_dir.glob("*.db"), reverse=True)
        if timestamp:
            backups = [b for b in backups if timestamp in b.name]
        if not backups:
            raise FileNotFoundError(
                f"No matching full backup for {db_name}@{timestamp or 'latest'}"
            )

        source = backups[0]
        dest = self._db_paths[db_name]

        meta_path = full_dir / source.name.replace(".db", ".meta.json")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            actual = self._sha256_file(source)
            if actual != meta.get("checksum_sha256", ""):
                raise RuntimeError(
                    f"Checksum mismatch for {source.name}: "
                    f"expected={meta.get('checksum_sha256', '?')[:16]}, actual={actual[:16]}"
                )

        # Backup current DB before overwriting (safety net)
        if dest.exists():
            safety = dest.with_suffix(f".pre_restore_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.bak")
            shutil.copy2(str(dest), str(safety))
            logger.info("Pre-restore safety backup: %s", safety.name)

        shutil.copy2(str(source), str(dest))
        logger.info("Restored %s from %s", db_name, source.name)
        return dest

    def restore_latest_all(self) -> Dict[str, Path]:
        results: Dict[str, Path] = {}
        for db_name in self._db_paths:
            results[db_name] = self.restore(db_name)
        return results

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_expired(self) -> List[Path]:
        cutoff = datetime.now() - timedelta(days=self._retention)
        removed: List[Path] = []
        for db_dir in self._backup_root.iterdir():
            if not db_dir.is_dir():
                continue
            full_dir = db_dir / "full"
            if not full_dir.exists():
                continue
            for f in list(full_dir.iterdir()):
                if f.is_file():
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime < cutoff:
                        f.unlink()
                        removed.append(f)
        if removed:
            logger.info("Cleaned up %d expired backups", len(removed))
        return removed

    # ------------------------------------------------------------------
    # Integrity verification
    # ------------------------------------------------------------------

    def verify_integrity(self, db_name: str) -> Dict[str, str]:
        conn = self._mgr.get_admin_connection(db_name)
        try:
            cursor = conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            return {"status": "ok" if result == "ok" else "corrupt", "detail": str(result)}
        finally:
            conn.close()

    def verify_all(self) -> Dict[str, Dict[str, str]]:
        return {name: self.verify_integrity(name) for name in self._db_paths}

    # ------------------------------------------------------------------
    # Health check (backup freshness)
    # ------------------------------------------------------------------

    def health_check(self, max_age_hours: int = 25) -> Dict[str, str]:
        results: Dict[str, str] = {}
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        for db_name in self._db_paths:
            full_dir = self._backup_root / db_name / "full"
            if not full_dir.exists():
                results[db_name] = "no_backups"
                continue
            backups = sorted(full_dir.glob("*.db"), reverse=True)
            if not backups:
                results[db_name] = "no_backups"
                continue
            latest = backups[0]
            mtime = datetime.fromtimestamp(latest.stat().st_mtime)
            if mtime < cutoff:
                results[db_name] = f"stale ({mtime.isoformat()})"
            else:
                results[db_name] = "fresh"
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sha256_file(path: Path) -> str:
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest()

    @staticmethod
    def _write_meta(meta_path: Path, meta: dict) -> None:
        meta_path.write_text(json.dumps(meta, indent=2, default=str))

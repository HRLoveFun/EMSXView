"""Unified migration manager for all CostView databases.

Tracks schema versions via PRAGMA user_version for each database,
and provides a centralized interface for applying pending migrations.

Currently, only regime.db has a formal migration system.
Other databases use inline ALTER TABLE in their _init_db() methods.
This manager provides a unified interface to track and verify
schema versions across all databases.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from ...connection import ConnectionManager

logger = logging.getLogger(__name__)

# Expected schema versions for each database.
# -1 means "not tracked" (uses inline DDL).
# These should be updated when formal migrations are added.
EXPECTED_VERSIONS: Dict[str, int] = {
    "raw_fills": -1,
    "processed_fills": -1,
    "raw_bdib": -1,
    "processed_raw_bdib": -1,
    "fill_bdib": -1,
    "regime": 3,  # regime.db uses formal migrations (currently at v3)
}


class MigrationManager:
    """Unified migration management for all CostView databases.

    Responsibilities:
    1. Track schema version (PRAGMA user_version) for each database
    2. Verify schema versions match expected values
    3. Apply pending migrations for databases with formal migration systems
    4. Provide a health check across all databases

    Usage:
        mgr = MigrationManager()
        mgr.ensure_current("regime")
        status = mgr.get_all_versions()
    """

    def __init__(self, connection_manager: Optional[ConnectionManager] = None):
        self._mgr = connection_manager or ConnectionManager()

    def get_version(self, database: str) -> int:
        """Return PRAGMA user_version for a database."""
        conn = self._mgr.get_admin_connection(database)
        try:
            cursor = conn.execute("PRAGMA user_version")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def set_version(self, database: str, version: int) -> None:
        """Set PRAGMA user_version for a database."""
        conn = self._mgr.get_admin_connection(database)
        try:
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
        finally:
            conn.close()

    def ensure_current(self, database: str) -> None:
        """Ensure the specified database's schema is at the expected version.

        For regime.db, delegates to its own migration system.
        For other databases, triggers _init_db() which handles inline DDL.
        """
        if not self._mgr.database_exists(database):
            logger.info(f"Database '{database}' does not exist; will be created on first use")
            return

        if database == "regime":
            self._ensure_regime_current()
        else:
            # For other DBs, trigger schema init via their DB classes
            self._ensure_inline_schema(database)

    def _ensure_regime_current(self) -> None:
        """Apply regime.db migrations using its formal system."""
        try:
            from CostView.src.regime.schema import ensure_schema_current
            db_path = self._mgr.get_path("regime")
            ensure_schema_current(db_path)
            logger.info("regime.db schema ensured current")
        except Exception as e:
            logger.warning(f"Failed to ensure regime.db schema: {e}")

    def _ensure_inline_schema(self, database: str) -> None:
        """Trigger inline schema initialization for databases without formal migrations."""
        try:
            if database == "raw_fills":
                from CostView.src.raw_fills_db import RawFillsDB
                RawFillsDB()
            elif database == "processed_fills":
                from CostView.src.processed_fills_db import init_processed_fills_schema
                init_processed_fills_schema()
            elif database == "raw_bdib":
                from CostView.src.raw_bdib_db import RawBDIBDB
                RawBDIBDB()
            elif database == "processed_raw_bdib":
                from CostView.src.processed_raw_bdib_db import ProcessedRawBDIBDB
                ProcessedRawBDIBDB()
            elif database == "fill_bdib":
                from CostView.src.fill_bdib_db import FillBDIBDB
                FillBDIBDB()
        except Exception as e:
            logger.warning(f"Failed to ensure inline schema for {database}: {e}")

    def get_all_versions(self) -> Dict[str, Dict[str, object]]:
        """Return schema version status for all databases."""
        result: Dict[str, Dict[str, object]] = {}
        for db_name in self._mgr.registry:
            path = self._mgr.get_path(db_name)
            exists = path.exists()
            version = self.get_version(db_name) if exists else None
            expected = EXPECTED_VERSIONS.get(db_name, -1)
            result[db_name] = {
                "path": str(path),
                "exists": exists,
                "user_version": version,
                "expected_version": expected,
                "needs_migration": (
                    exists and expected > 0 and (version or 0) < expected
                ),
            }
        return result

    def apply_pending(self, database: str) -> int:
        """Apply pending migrations for a database. Returns new version."""
        self.ensure_current(database)
        return self.get_version(database)

    def health_check(self) -> Dict[str, str]:
        """Return health status for all databases.

        Status values: "ok", "needs_migration", "missing", "error".
        """
        result: Dict[str, str] = {}
        for db_name in self._mgr.registry:
            path = self._mgr.get_path(db_name)
            if not path.exists():
                result[db_name] = "missing"
                continue
            try:
                version = self.get_version(db_name)
                expected = EXPECTED_VERSIONS.get(db_name, -1)
                if expected > 0 and (version or 0) < expected:
                    result[db_name] = "needs_migration"
                else:
                    result[db_name] = "ok"
            except Exception as e:
                result[db_name] = f"error: {e}"
        return result

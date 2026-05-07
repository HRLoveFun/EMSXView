"""Backward-compatible facade for CostView database access.

Provides a unified entry point that delegates to the new
repository implementations while maintaining the same API
that existing code depends on.

This facade is intended for callers that need cross-database
operations. Domain-specific code should import individual
repositories from db.repositories instead.

During the migration period (Iteration 1-3), the facade also
provides lazy-initialized instances of the legacy DB classes
(RawFillsDB, ProcessedFillsDB, etc.) so that pipeline stages
can access the full method set while new Repository implementations
are being completed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .connection import ConnectionManager, AccessTier
from .repositories.fills_read import SqliteFillReadRepository
from .repositories.fills_write import SqliteFillWriteRepository
from .repositories.raw_fills_read import SqliteRawFillReadRepository
from .repositories.raw_fills_write import SqliteRawFillWriteRepository
from .repositories.market_data_read import SqliteMarketDataReadRepository
from .repositories.market_data_write import SqliteMarketDataWriteRepository
from .repositories.integrated import (
    SqliteIntegratedReadRepository,
    SqliteIntegratedWriteRepository,
)
from .repositories.regime import (
    SqliteRegimeReadRepository,
    SqliteRegimeWriteRepository,
)
from .schema.migrations.manager import MigrationManager

logger = logging.getLogger(__name__)


class CostViewDatabase:
    """Unified database facade for CostView.

    Provides convenient access to all database repositories
    through a single object. Internally delegates to individual
    repository implementations.

    During the migration period, also exposes lazy-initialized
    legacy DB class instances for methods not yet available in
    the new Repository implementations.

    Usage:
        db = CostViewDatabase()

        # New Repository API:
        fills = db.fills_read.get_fills_for_date("20260408")

        # Legacy DB API (migration period):
        proc_db = db.proc_db   # ProcessedFillsDB facade
        raw_db = db.raw_db     # RawFillsDB instance
    """

    def __init__(self, connection_manager: Optional[ConnectionManager] = None):
        self._mgr = connection_manager or ConnectionManager()

        # Initialize all repositories with shared ConnectionManager
        self.fills_read = SqliteFillReadRepository(self._mgr)
        self.fills_write = SqliteFillWriteRepository(self._mgr)
        self.raw_fills_read = SqliteRawFillReadRepository(self._mgr)
        self.raw_fills_write = SqliteRawFillWriteRepository(self._mgr)
        self.market_data_read = SqliteMarketDataReadRepository(self._mgr)
        self.market_data_write = SqliteMarketDataWriteRepository(self._mgr)
        self.integrated_read = SqliteIntegratedReadRepository(self._mgr)
        self.integrated_write = SqliteIntegratedWriteRepository(self._mgr)
        self.regime_read = SqliteRegimeReadRepository(self._mgr)
        self.regime_write = SqliteRegimeWriteRepository(self._mgr)
        self.migrations = MigrationManager(self._mgr)

        # Legacy DB instances (lazy-initialized on first access)
        self._raw_db = None
        self._proc_db = None
        self._raw_bdib_db = None
        self._processed_raw_bdib_db = None
        self._fill_bdib_db = None

    @property
    def connection_manager(self) -> ConnectionManager:
        return self._mgr

    # ── Legacy DB class access (migration period) ────────────────────

    @property
    def raw_db(self):
        """Lazy-initialized RawFillsDB instance (legacy, migration period).

        Prefer using db.raw_fills_read / db.raw_fills_write for new code.
        """
        if self._raw_db is None:
            from ..raw_fills_db import RawFillsDB
            self._raw_db = RawFillsDB()
        return self._raw_db

    @property
    def proc_db(self):
        """Lazy-initialized ProcessedFillsDB facade instance (legacy, migration period).

        Prefer using db.fills_read / db.fills_write for new code.
        """
        if self._proc_db is None:
            from ..processed_fills_db import ProcessedFillsDB
            self._proc_db = ProcessedFillsDB()
        return self._proc_db

    @property
    def raw_bdib_db(self):
        """Lazy-initialized RawBDIBDB instance (legacy, migration period).

        Prefer using db.market_data_read / db.market_data_write for new code.
        """
        if self._raw_bdib_db is None:
            from ..raw_bdib_db import RawBDIBDB
            self._raw_bdib_db = RawBDIBDB()
        return self._raw_bdib_db

    @property
    def processed_raw_bdib_db(self):
        """Lazy-initialized ProcessedRawBDIBDB instance (legacy, migration period).

        Prefer using db.market_data_write for new code.
        """
        if self._processed_raw_bdib_db is None:
            from ..processed_raw_bdib_db import ProcessedRawBDIBDB
            self._processed_raw_bdib_db = ProcessedRawBDIBDB()
        return self._processed_raw_bdib_db

    @property
    def fill_bdib_db(self):
        """Lazy-initialized FillBDIBDB instance (legacy, migration period).

        Prefer using db.integrated_write for new code.
        """
        if self._fill_bdib_db is None:
            from ..fill_bdib_db import FillBDIBDB
            self._fill_bdib_db = FillBDIBDB()
        return self._fill_bdib_db

    # ── General utilities ────────────────────────────────────────────

    def get_all_paths(self) -> Dict[str, Path]:
        """Return all registered database paths."""
        return self._mgr.get_all_paths()

    def get_existing_databases(self) -> List[str]:
        """Return names of databases whose files exist."""
        return self._mgr.get_existing_databases()

    def health_check(self) -> Dict[str, str]:
        """Return health status for all databases."""
        return self.migrations.health_check()

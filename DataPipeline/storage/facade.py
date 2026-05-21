"""Unified entry point for all database repositories.

Provides ``fills_read``, ``fills_write``, ``raw_fills_read``, etc.
as direct attributes.

Legacy properties (``raw_db``, ``raw_bdib_db``, etc.) removed — use
the corresponding repository attributes.

"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from DataPipeline.storage.connection import ConnectionManager
from DataPipeline.storage.repositories.fills import SqliteFillReadRepository, SqliteFillWriteRepository
from DataPipeline.storage.repositories.raw_fills import SqliteRawFillReadRepository, SqliteRawFillWriteRepository
from DataPipeline.storage.repositories.market_data import SqliteMarketDataReadRepository, SqliteMarketDataWriteRepository
from DataPipeline.storage.repositories.integrated import (
    SqliteIntegratedReadRepository,
    SqliteIntegratedWriteRepository,
)
from DataPipeline.storage.repositories.regime import (
    SqliteRegimeReadRepository,
    SqliteRegimeWriteRepository,
)
from DataPipeline.storage.schema.migrations.manager import MigrationManager

logger = logging.getLogger(__name__)

class DatabaseFacade:
    """Unified entry point for all database repositories.

    Usage:
        db = DatabaseFacade()
        fills = db.fills_read.get_fills_for_date("20260408")
        df = db.fills_write.upsert_processed_fills(df)
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

    @property
    def connection_manager(self) -> ConnectionManager:
        return self._mgr

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


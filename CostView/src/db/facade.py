"""Backward-compatible facade for CostView database access.

Provides a unified entry point that delegates to the new
repository implementations while maintaining the same API
that existing code depends on.

This facade is intended for callers that need cross-database
operations. Domain-specific code should import individual
repositories from db.repositories instead.
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

    Usage:
        db = CostViewDatabase()
        fills = db.fills_read.get_fills_for_date("20260408")
        status = db.migrations.health_check()
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

    def get_all_paths(self) -> Dict[str, Path]:
        """Return all registered database paths."""
        return self._mgr.get_all_paths()

    def get_existing_databases(self) -> List[str]:
        """Return names of databases whose files exist."""
        return self._mgr.get_existing_databases()

    def health_check(self) -> Dict[str, str]:
        """Return health status for all databases."""
        return self.migrations.health_check()

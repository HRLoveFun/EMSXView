"""Base class for all database subsystem repositories.

Provides shared connection management via ConnectionManager,
standardizing pragmas and access tier enforcement.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from DataPipeline.src.storage.connection import (
    AccessControlledConnection,
    AccessTier,
    ConnectionManager,
)

# ── Bloomberg-native BDIB columns (no derived fields) ──
# Moved here from raw_bdib_db.py (deprecated) so market_data_write.py
# and other repos that need this constant do not depend on the legacy module.
RAW_BDIB_COLUMNS = [
    "equ_ticker",
    "order_as_of_date",
    "mkt_timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "num_trds",
    "value",
]

logger = logging.getLogger(__name__)


class BaseRepository:
    """Base class providing shared DB connection management via ConnectionManager.

    All concrete repositories inherit from this class to reuse
    connection setup, access control, and database name resolution.

    Parameters
    ----------
    connection_manager : ConnectionManager, optional
        Shared connection manager. If None, creates a new one.
    database : str
        Database name key (e.g. "raw_fills", "processed_fills").
    """

    def __init__(
        self,
        connection_manager: Optional[ConnectionManager] = None,
        database: str = "processed_fills",
    ):
        self._mgr = connection_manager or ConnectionManager()
        self._database = database

    def _get_conn(
        self,
        tier: Optional[AccessTier] = None,
    ) -> AccessControlledConnection:
        """Create an access-controlled connection."""
        return self._mgr.get_connection(self._database, tier)

    def _get_read_conn(self) -> AccessControlledConnection:
        """Create a READ connection."""
        return self._mgr.get_connection(self._database, AccessTier.READ)

    def _get_write_conn(self) -> AccessControlledConnection:
        """Create a WRITE connection."""
        return self._mgr.get_connection(self._database, AccessTier.WRITE)

    def _get_admin_conn(self):
        """Create a raw admin connection for DDL operations."""
        return self._mgr.get_admin_connection(self._database)

    @staticmethod
    def _build_column_defs(columns: List[str], type_map: Dict[str, str]) -> str:
        """Build SQL column definition string from column list."""
        parts = []
        for col in columns:
            col_type = type_map.get(col, "TEXT")
            parts.append(f"[{col}] {col_type}")
        return ",\n                    ".join(parts)

    @property
    def database(self) -> str:
        return self._database

    @property
    def connection_manager(self) -> ConnectionManager:
        return self._mgr

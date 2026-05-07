"""Base class for all database subsystem repositories.

Provides shared connection management via ConnectionManager,
standardizing pragmas and access tier enforcement.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..connection import (
    AccessControlledConnection,
    AccessTier,
    ConnectionManager,
)

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

    @property
    def database(self) -> str:
        return self._database

    @property
    def connection_manager(self) -> ConnectionManager:
        return self._mgr

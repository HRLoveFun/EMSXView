"""Abstract protocols for DataPipeline interfaces.

Defines typing.Protocol interfaces that CostView and backend modules should
code against, rather than importing DataPipeline internals directly.

Usage:
    from platform_data.contracts.protocols import ConnectionManagerProtocol

    def my_service(cm: ConnectionManagerProtocol) -> None:
        with cm.connect() as conn:
            ...

This allows unit tests to mock the ConnectionManager without importing
DataPipeline, and keeps the dependency direction correct:
    backend → platform_data → DataPipeline
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class AccessTier(Enum):
    """Lightweight access-tier enum — mirrors DataPipeline.storage.connection.AccessTier.

    Defined here so that platform_data consumers do not need to import from
    DataPipeline directly; DataPipeline.AccessTier is compatible via duck-typing
    because ConnectionManagerProtocol accepts ``Any`` for access_tier.
    """

    READ = "read"
    WRITE = "write"


@runtime_checkable
class ConnectionManagerProtocol(Protocol):
    """Protocol for database connection management.

    Implemented by ``DataPipeline.storage.connection.ConnectionManager``.
    New code should depend on this protocol rather than the concrete class.
    """

    def get_connection(
        self, db_name: str, access_tier: Any = None, row_factory: Any = None
    ) -> Any:
        """Return a database connection for the given database and access tier."""
        ...

    def connect(self) -> Any:
        """Return a context-managed database connection."""
        ...

    def database_exists(self, db_name: str) -> bool:
        """Return True if the named database file exists."""
        ...

    def get_path(self, db_name: str) -> Path:
        """Return the filesystem path for the named database."""
        ...

    def connection(self, db_name: str) -> Any:
        """Return a context-managed read-only connection for the named database."""
        ...

    @property
    def db_path(self) -> str:
        """Path to the primary database file."""
        ...


@runtime_checkable
class ConfigProtocol(Protocol):
    """Protocol for DataPipeline configuration.

    Implemented by ``DataPipeline.config.Config``.
    """

    # Class-level table name constants
    RAW_FILLS_TABLE: str
    PROCESSED_FILLS_TABLE: str

    @property
    def data_dir(self) -> str:
        """Root data directory for pipeline outputs."""
        ...

    @property
    def raw_fills_db(self) -> str:
        """Path to raw_fills.db."""
        ...

    @property
    def processed_fills_db(self) -> str:
        """Path to processed_fills.db."""
        ...

    @property
    def fill_bdib_db(self) -> str:
        """Path to fill_bdib.db."""
        ...

    @property
    def bdib_daily_summary_db(self) -> str:
        """Path to bdib_daily_summary table / database."""
        ...

    @property
    def raw_bdib_table(self) -> str:
        """Name of the raw BDIB table."""
        ...

    @property
    def bdib_daily_summary_table(self) -> str:
        """Name of the BDIB daily summary table."""
        ...

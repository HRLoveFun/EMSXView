"""CostView database subsystem — unified connection management, protocols,
repositories, schema management, and facade.

Usage:
    # Connection management
    from CostView.src.db import ConnectionManager, AccessTier

    # Repository access (new code)
    from CostView.src.db.repositories import SqliteFillReadRepository

    # Unified facade
    from CostView.src.db.facade import CostViewDatabase

    # Schema management
    from CostView.src.db.schema import MigrationManager
"""

from .connection import (
    AccessControlledConnection,
    AccessTier,
    ConnectionManager,
    backup_database,
    resolve_access_tier,
)

__all__ = [
    "AccessControlledConnection",
    "AccessTier",
    "ConnectionManager",
    "backup_database",
    "resolve_access_tier",
]

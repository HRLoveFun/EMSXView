"""CostView database subsystem — re-export layer.

All storage primitives have been migrated to DataPipeline/src/storage/.
This module re-exports them for backward compatibility.

Usage:
    # Connection management (new import path)
    from DataPipeline.src.storage.connection import ConnectionManager, AccessTier

    # Unified facade (CostView concept, kept here)
    from CostView.src.db.facade import CostViewDatabase
"""

from DataPipeline.src.storage.connection import (
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

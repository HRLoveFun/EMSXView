"""Backward-compatible re-export module.

All database access primitives have been migrated to
``CostView.src.db.connection``.  This module re-exports them
so that existing import paths continue to work during the
transition period (Phase 1–2).

New code should import from ``CostView.src.db`` directly.

Deprecated since: 2026-05-07 (Phase 1 database subsystem refactoring)
"""

from DataPipeline.src.storage.connection import (  # noqa: F401 — re-exports for backward compat
    AccessControlledConnection,
    AccessTier,
    backup_database,
    resolve_access_tier,
)

# Also expose ConnectionManager for callers that have already migrated
from DataPipeline.src.storage.connection import ConnectionManager  # noqa: F401

__all__ = [
    "AccessControlledConnection",
    "AccessTier",
    "ConnectionManager",
    "backup_database",
    "resolve_access_tier",
]

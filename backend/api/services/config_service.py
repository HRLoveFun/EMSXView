"""
Configuration service — versioned server-side config store.

Wraps BrokerAlgorithmStorageService with version tracking and freshness
semantics so that the frontend reads through a typed API first and falls
back to localStorage only when the server is unreachable.

Currently backed by the JSON file store (``data/broker_algorithms.json``).
When P1-S1 database persistence is activated, this service can switch to
a DB-backed repository without changing the API contract.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import List, Optional

from schemas import BrokerAlgorithmConfig, BrokerAlgorithmStorage

logger = logging.getLogger("main")


class ConfigService:
    """Server-owned configuration store with version tracking.

    Parameters
    ----------
    storage : BrokerAlgorithmStorageService
        The underlying storage backend (currently JSON file).
    """

    def __init__(self, storage):
        self._storage = storage

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_configs(self) -> List[BrokerAlgorithmConfig]:
        """Return all stored broker algorithm configurations."""
        return await self._storage.get_configs()

    async def get_last_updated(self) -> Optional[datetime]:
        """Return the last-updated timestamp, or None if no data."""
        return await self._storage.get_last_updated()

    async def needs_refresh(self) -> bool:
        """Return True if the stored data is stale (older than 1 day)."""
        return await self._storage.needs_refresh()

    async def get_version_hash(self) -> Optional[str]:
        """Return a deterministic hash of the current config for ETag / cache-busting."""
        configs = await self._storage.get_configs()
        if not configs:
            return None
        payload = json.dumps(
            [c.model_dump() for c in configs], sort_keys=True
        ).encode()
        return hashlib.sha256(payload).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save_configs(self, configs: List[BrokerAlgorithmConfig]) -> bool:
        """Persist a new set of configs (replaces existing)."""
        ok = await self._storage.save(configs)
        if ok:
            version = await self.get_version_hash()
            logger.info(f"[ConfigService] Saved {len(configs)} configs, version={version}")
        return ok

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def status_summary(self) -> dict:
        """Return a status dict suitable for the /api/broker-algorithms/status endpoint."""
        last_updated = await self.get_last_updated()
        return {
            "lastUpdated": last_updated.isoformat() if last_updated else None,
            "needsRefresh": await self.needs_refresh(),
            "hasData": last_updated is not None,
            "version": await self.get_version_hash(),
        }

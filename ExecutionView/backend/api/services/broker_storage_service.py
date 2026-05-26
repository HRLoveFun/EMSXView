"""
Persistent storage for broker algorithm configuration.

Stores data in a JSON file and provides freshness checking.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

try:
    import aiofiles
except ImportError:
    aiofiles = None

from schemas import BrokerAlgorithmConfig, BrokerAlgorithmStorage

logger = logging.getLogger(__name__)


class BrokerAlgorithmStorageService:
    """
    Persistent storage for broker algorithm configuration.
    Stores data in a JSON file and provides freshness checking.
    """

    def __init__(self, storage_dir: str = "./data"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_file = self.storage_dir / "broker_algorithms.json"
        self._cache: Optional[BrokerAlgorithmStorage] = None
        self._lock = asyncio.Lock()

    async def load(self) -> Optional[BrokerAlgorithmStorage]:
        """Load stored configuration from disk"""
        async with self._lock:
            if self._cache is not None:
                return self._cache

            try:
                if self.storage_file.exists():
                    if aiofiles:
                        async with aiofiles.open(self.storage_file, 'r') as f:
                            content = await f.read()
                    else:
                        # Fallback to synchronous file I/O
                        with open(self.storage_file, 'r') as f:
                            content = f.read()
                    data = json.loads(content)
                    self._cache = BrokerAlgorithmStorage(**data)
                    logger.info(f"[BrokerAlgorithmStorage] Loaded {len(self._cache.configs)} broker configs")
                    return self._cache
            except Exception as e:
                logger.error(f"[BrokerAlgorithmStorage] Failed to load: {e}")

            return None

    async def save(self, configs: List[BrokerAlgorithmConfig]) -> bool:
        """Save configuration to disk"""
        async with self._lock:
            try:
                storage = BrokerAlgorithmStorage(configs=configs)
                self._cache = storage

                content = json.dumps(storage.model_dump(), indent=2)
                if aiofiles:
                    async with aiofiles.open(self.storage_file, 'w') as f:
                        await f.write(content)
                else:
                    # Fallback to synchronous file I/O
                    with open(self.storage_file, 'w') as f:
                        f.write(content)

                logger.info(f"[BrokerAlgorithmStorage] Saved {len(configs)} broker configs")
                return True
            except Exception as e:
                logger.error(f"[BrokerAlgorithmStorage] Failed to save: {e}")
                return False

    async def get_configs(self) -> List[BrokerAlgorithmConfig]:
        """Get all stored configurations"""
        storage = await self.load()
        return storage.configs if storage else []

    async def get_last_updated(self) -> Optional[datetime]:
        """Get last update timestamp"""
        storage = await self.load()
        if storage and storage.lastUpdated:
            try:
                return datetime.fromisoformat(storage.lastUpdated)
            except Exception:
                pass
        return None

    async def needs_refresh(self) -> bool:
        """Check if data needs refresh (older than 1 day)"""
        last_updated = await self.get_last_updated()
        if not last_updated:
            return True

        now = datetime.now()
        last_update_day = last_updated.replace(hour=0, minute=0, second=0, microsecond=0)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        return last_update_day < today

    def clear_cache(self):
        """Clear in-memory cache"""
        self._cache = None

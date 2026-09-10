"""Two-level TCA query result cache.

Level 1: In-process thread-safe LRU (128 entries, fast path)
Level 2: Redis distributed cache (optional, TTL-aware)

Cache keys are SHA-256 digests of normalized request parameters.
TTL adapts based on market hours (shorter during trading, longer post-market).

Usage::

    from CostView.src.tca_cache import TcaCacheManager, CacheConfig
    cache = TcaCacheManager(CacheConfig())

    key = cache.make_key("tca_report", {"order_ids": ["123"], "date": "20260601"})
    result = await cache.get(key)
    if result is None:
        result = compute_expensive_tca_report(...)
        await cache.set(key, result)

    # Invalidate all cached results after pipeline update:
    await cache.invalidate("tca:")
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis  # type: ignore[import-untyped]
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

# P3-2 余项：市场时段按美东时区判定（原实现用服务器本地时间，非 ET 部署时
# TTL 策略失准）。Windows 上 zoneinfo 依赖 tzdata 包，缺失时回退本地时间。
try:
    from zoneinfo import ZoneInfo
    _MARKET_TZ = ZoneInfo("America/New_York")
except Exception:
    _MARKET_TZ = None


@dataclass
class CacheConfig:
    redis_url: str = "redis://localhost:6379/1"
    lru_max_size: int = 128
    ttl_seconds: int = 300
    market_hours_ttl: int = 60
    enable_redis: bool = True
    enable_lru: bool = True


class LRUCache:

    def __init__(self, max_size: int = 128) -> None:
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            value, expiry = self._cache[key]
            if expiry < time.monotonic():
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (value, time.monotonic() + ttl)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self, key_prefix: Optional[str] = None) -> int:
        with self._lock:
            if key_prefix is None:
                count = len(self._cache)
                self._cache.clear()
                return count
            to_remove = [k for k in self._cache if k.startswith(key_prefix)]
            for k in to_remove:
                del self._cache[k]
            return len(to_remove)

    def stats(self) -> dict:
        with self._lock:
            return {"size": len(self._cache), "max_size": self._max_size}


class TcaCacheManager:
    """Two-level cache: LRU (L1) -> Redis (L2)."""

    def __init__(self, config: Optional[CacheConfig] = None) -> None:
        self._config = config or CacheConfig()
        self._lru = LRUCache(self._config.lru_max_size) if self._config.enable_lru else None
        self._redis: Optional[Any] = None
        # P3-2：client 创建锁，避免并发协程竞态创建多个 client（其一泄漏）
        self._redis_lock = asyncio.Lock()

    async def _get_redis(self) -> Optional[Any]:
        if not HAS_REDIS or not self._config.enable_redis:
            return None
        if self._redis is None:
            async with self._redis_lock:
                if self._redis is None:
                    try:
                        # 注意：from_url 为惰性连接，此处捕获不到真实连接失败；
                        # 连接错误由 get/set 处的 try/except 降级。
                        self._redis = aioredis.from_url(
                            self._config.redis_url, decode_responses=True
                        )
                    except Exception:
                        logger.warning("Redis connection failed, disabling L2 cache", exc_info=True)
                        return None
        return self._redis

    @staticmethod
    def make_key(prefix: str, params: dict) -> str:
        normalized = json.dumps(params, sort_keys=True, default=str)
        digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        return f"{prefix}:{digest}"

    def _get_ttl(self) -> int:
        """按美股常规时段（周一~周五 9:30-16:00 ET）取短 TTL，其余取长 TTL。"""
        now = datetime.now(_MARKET_TZ) if _MARKET_TZ else datetime.now()
        is_market_hours = (
            now.weekday() < 5
            and datetime(now.year, now.month, now.day, 9, 30, tzinfo=now.tzinfo) <= now
            and now <= datetime(now.year, now.month, now.day, 16, 0, tzinfo=now.tzinfo)
        )
        return self._config.market_hours_ttl if is_market_hours else self._config.ttl_seconds

    async def get(self, key: str) -> Optional[Any]:
        if self._lru:
            value = self._lru.get(key)
            if value is not None:
                return value

        redis = await self._get_redis()
        if redis:
            try:
                raw = await redis.get(key)
                if raw:
                    value = json.loads(raw)
                    if self._lru:
                        self._lru.set(key, value, ttl=self._get_ttl())
                    return value
            except Exception:
                logger.debug("Redis get failed for key %s", key, exc_info=True)
        return None

    async def set(self, key: str, value: Any) -> None:
        ttl = self._get_ttl()
        if self._lru:
            self._lru.set(key, value, ttl=ttl)
        redis = await self._get_redis()
        if redis:
            try:
                await redis.setex(key, ttl, json.dumps(value, default=str))
            except Exception:
                logger.debug("Redis set failed for key %s", key, exc_info=True)

    async def invalidate(self, prefix: Optional[str] = None) -> int:
        """失效缓存。

        prefix 给定时同时清 L1 与 Redis（P2-7：SCAN 增量迭代替代 KEYS，
        避免阻塞整个 Redis 键空间）；prefix 为 None 时仅清 L1
        （不 flushdb——Redis 实例可能承载 handoff 等其他数据）。
        """
        count = 0
        if self._lru:
            count += self._lru.invalidate(prefix)
        redis = await self._get_redis()
        if redis and prefix:
            try:
                keys = [key async for key in redis.scan_iter(match=f"{prefix}*")]
                for i in range(0, len(keys), 500):
                    count += await redis.delete(*keys[i:i + 500])
            except Exception:
                logger.debug("Redis invalidate failed", exc_info=True)
        return count

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def stats(self) -> dict:
        lru_stats = self._lru.stats() if self._lru else {"size": 0, "max_size": 0}
        return {"lru": lru_stats, "redis_available": HAS_REDIS and self._config.enable_redis}

/**
 * Data Cache Manager - Unified caching layer for EMSX application
 * 
 * Supports two-level caching:
 * - Memory cache: Fast access, session-only
 * - LocalStorage: Persistent across sessions
 * 
 * Features:
 * - TTL (Time To Live) expiration
 * - Manual invalidation
 * - Automatic fallback from cache to API
 * - Type-safe cache entries
 */

// Cache storage types
export type CacheStorage = 'memory' | 'localStorage';

// Cache entry metadata
interface CacheEntry<T> {
  data: T;
  timestamp: number;
  expiresAt: number;
}

// Cache configuration
export interface CacheConfig {
  key: string;
  ttl: number; // Time to live in milliseconds
  storage: CacheStorage;
}

// Default TTL values (in milliseconds)
export const DEFAULT_TTL = {
  HIGH_FREQUENCY: 2000,      // 2 seconds - orders, routes
  MEDIUM_FREQUENCY: 30000,   // 30 seconds - connection status
  LOW_FREQUENCY: 86400000,   // 24 hours - broker strategies
  VERY_LOW_FREQUENCY: 86400000 * 7, // 7 days - trader info
} as const;

// Cache key prefixes to avoid collisions
const CACHE_PREFIX = 'emsx_cache_';

// In-memory cache store
const memoryCache = new Map<string, CacheEntry<unknown>>();

/**
 * Get cache key with prefix
 */
function getFullKey(key: string): string {
  return `${CACHE_PREFIX}${key}`;
}

/**
 * Check if running in browser environment
 */
function isBrowser(): boolean {
  return typeof window !== 'undefined' && typeof localStorage !== 'undefined';
}

/**
 * Get current timestamp
 */
function now(): number {
  return Date.now();
}

/**
 * Cache Manager class for managing cached data with TTL
 */
export class CacheManager<T> {
  private config: CacheConfig;

  constructor(config: CacheConfig) {
    this.config = config;
  }

  /**
   * Get cached data if valid
   * @returns Cached data or null if expired/not found
   */
  get(): T | null {
    const fullKey = getFullKey(this.config.key);
    const entry = this.getEntry(fullKey);

    if (!entry) {
      return null;
    }

    // Check if expired
    if (now() > entry.expiresAt) {
      this.delete(fullKey);
      return null;
    }

    return entry.data as T;
  }

  /**
   * Store data in cache
   */
  set(data: T): void {
    const fullKey = getFullKey(this.config.key);
    const timestamp = now();
    const expiresAt = timestamp + this.config.ttl;

    const entry: CacheEntry<T> = {
      data,
      timestamp,
      expiresAt,
    };

    if (this.config.storage === 'memory') {
      memoryCache.set(fullKey, entry as CacheEntry<unknown>);
    } else if (this.config.storage === 'localStorage' && isBrowser()) {
      try {
        localStorage.setItem(fullKey, JSON.stringify(entry));
      } catch (e) {
        console.warn(`[CacheManager] Failed to write to localStorage: ${e}`);
        // Fallback to memory cache
        memoryCache.set(fullKey, entry as CacheEntry<unknown>);
      }
    }
  }

  /**
   * Check if cache is valid (exists and not expired)
   */
  isValid(): boolean {
    return this.get() !== null;
  }

  /**
   * Get cache age in milliseconds
   * @returns Age in ms, or -1 if not found
   */
  getAge(): number {
    const fullKey = getFullKey(this.config.key);
    const entry = this.getEntry(fullKey);
    
    if (!entry) {
      return -1;
    }

    return now() - entry.timestamp;
  }

  /**
   * Get remaining TTL in milliseconds
   * @returns Remaining TTL in ms, or 0 if expired/not found
   */
  getRemainingTtl(): number {
    const fullKey = getFullKey(this.config.key);
    const entry = this.getEntry(fullKey);
    
    if (!entry) {
      return 0;
    }

    const remaining = entry.expiresAt - now();
    return remaining > 0 ? remaining : 0;
  }

  /**
   * Invalidate/delete cache
   */
  invalidate(): void {
    const fullKey = getFullKey(this.config.key);
    this.delete(fullKey);
  }

  /**
   * Refresh cache with new data
   */
  refresh(data: T): void {
    this.set(data);
  }

  /**
   * Get cache entry from appropriate storage
   */
  private getEntry(fullKey: string): CacheEntry<T> | null {
    if (this.config.storage === 'memory') {
      const entry = memoryCache.get(fullKey);
      return entry ? (entry as CacheEntry<T>) : null;
    }

    if (this.config.storage === 'localStorage' && isBrowser()) {
      try {
        const raw = localStorage.getItem(fullKey);
        if (!raw) return null;
        return JSON.parse(raw) as CacheEntry<T>;
      } catch (e) {
        console.warn(`[CacheManager] Failed to read from localStorage: ${e}`);
        return null;
      }
    }

    return null;
  }

  /**
   * Delete cache entry from all storages
   */
  private delete(fullKey: string): void {
    memoryCache.delete(fullKey);
    
    if (isBrowser()) {
      try {
        localStorage.removeItem(fullKey);
      } catch (e) {
        // Ignore errors
      }
    }
  }
}

/**
 * Predefined cache configurations for EMSX data types
 */
export const CACHE_CONFIGS = {
  // High frequency - short TTL, memory only
  ORDERS: { key: 'orders', ttl: DEFAULT_TTL.HIGH_FREQUENCY, storage: 'memory' as CacheStorage },
  ROUTES: { key: 'routes', ttl: DEFAULT_TTL.HIGH_FREQUENCY, storage: 'memory' as CacheStorage },

  // Medium frequency - longer TTL, memory only
  CONNECTION_STATUS: { key: 'connection_status', ttl: DEFAULT_TTL.MEDIUM_FREQUENCY, storage: 'memory' as CacheStorage },

  // Low frequency - long TTL, persist to localStorage
  TRADER_INFO: { key: 'trader_info', ttl: DEFAULT_TTL.VERY_LOW_FREQUENCY, storage: 'localStorage' as CacheStorage },
  BROKER_STRATEGIES: (broker: string) => ({
    key: `broker_strategies_${broker}`,
    ttl: DEFAULT_TTL.LOW_FREQUENCY,
    storage: 'localStorage' as CacheStorage,
  }),
  STRATEGY_INFO: (broker: string, strategy: string) => ({
    key: `strategy_info_${broker}_${strategy}`,
    ttl: DEFAULT_TTL.LOW_FREQUENCY,
    storage: 'localStorage' as CacheStorage,
  }),
} as const;

/**
 * Create a cache manager instance with predefined config
 */
export function createCache<T>(config: CacheConfig): CacheManager<T> {
  return new CacheManager<T>(config);
}

/**
 * Get or fetch pattern - try cache first, fallback to fetch function
 */
export async function getOrFetch<T>(
  cache: CacheManager<T>,
  fetchFn: () => Promise<T>,
  options: {
    forceRefresh?: boolean;
    onError?: (error: Error) => void;
  } = {}
): Promise<T> {
  const { forceRefresh = false, onError } = options;

  // Try cache first (unless force refresh)
  if (!forceRefresh) {
    const cached = cache.get();
    if (cached !== null) {
      return cached;
    }
  }

  // Fetch new data
  try {
    const data = await fetchFn();
    cache.set(data);
    return data;
  } catch (error) {
    // On error, try to return stale cache if available
    const stale = cache.get();
    if (stale !== null) {
      console.warn('[CacheManager] Fetch failed, using stale cache:', error);
      return stale;
    }

    // No cache available, propagate error
    if (onError) {
      onError(error as Error);
    }
    throw error;
  }
}

/**
 * Clear all EMSX caches
 */
export function clearAllCaches(): void {
  // Clear memory cache
  memoryCache.clear();

  // Clear localStorage cache
  if (isBrowser()) {
    const keysToRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key?.startsWith(CACHE_PREFIX)) {
        keysToRemove.push(key);
      }
    }
    keysToRemove.forEach(key => {
      try {
        localStorage.removeItem(key);
      } catch (e) {
        // Ignore errors
      }
    });
  }
}

/**
 * Get cache statistics
 */
export function getCacheStats(): {
  memoryEntries: number;
  localStorageEntries: number;
} {
  let localStorageEntries = 0;
  
  if (isBrowser()) {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key?.startsWith(CACHE_PREFIX)) {
        localStorageEntries++;
      }
    }
  }

  return {
    memoryEntries: memoryCache.size,
    localStorageEntries,
  };
}

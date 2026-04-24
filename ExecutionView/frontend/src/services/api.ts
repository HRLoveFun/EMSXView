import type {
  Order,
  Route,
  OrderFilters,
  BatchUpdateRequest,
  BatchUpdateResponse,
  ApiResponse,
  BrokerAlgorithmConfig,
  CancelRouteRequest,
  ModifyRouteRequest,
  ModifyOrderRequest,
  RouteOrderRequest,
  TraderInfo,
  StartupStatusSnapshot,
  BrokerStrategiesResponse,
  BrokerStrategyInfoResponse,
} from '@/types';
import { createCache, CACHE_CONFIGS, getOrFetch } from '@/lib/cache-manager';
import {
  getBrokerStrategiesFromFile,
  getStrategyInfoFromFile,
  mergeWithDefaults,
} from './strategy-data-service';

// ============================================================
// Configuration
// VITE_API_URL: if set, used as base URL for all API calls.
// If empty, Vite dev-server proxy forwards /api/* to localhost:3000.
// ============================================================

const API_BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? '';

const TOKEN_KEY = 'emsx_token';

function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

function getAuthHeaders(): HeadersInit {
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
  return headers;
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const url = `${API_BASE_URL}${path}`;
  try {
    const response = await fetch(url, {
      ...options,
      headers: { ...getAuthHeaders(), ...(options.headers ?? {}) },
    });

    // Guard against empty bodies (204 No Content, chunked with no payload, etc.)
    const contentType = response.headers.get('content-type') ?? '';
    const hasJsonBody = contentType.includes('application/json');
    const text = await response.text();

    if (!response.ok) {
      // Try to parse error details from response body first
      if (text && hasJsonBody) {
        try {
          const err = JSON.parse(text);
          // Use backend's error message if available
          const errorMsg = err.error ?? err.detail ?? response.statusText;
          // For proxy/gateway errors, add context but preserve backend message
          if (response.status === 502 || response.status === 503 || response.status === 504) {
            if (errorMsg.includes('Bloomberg')) {
              return { success: false, error: errorMsg };
            }
            return { success: false, error: `Backend unavailable: ${errorMsg}` };
          }
          return { success: false, error: errorMsg };
        } catch {
          // fall through to default handling
        }
      }
      // Proxy/gateway errors without JSON body
      if (response.status === 502 || response.status === 503 || response.status === 504) {
        return { success: false, error: 'Backend unavailable — please start the backend service' };
      }
      if (response.status === 500 && (!text || !hasJsonBody)) {
        // Vite proxy returns 500 with HTML/empty body when it gets ECONNREFUSED
        return { success: false, error: 'Cannot connect to backend (ECONNREFUSED)' };
      }
      return { success: false, error: text || response.statusText };
    }

    if (!text) {
      // Empty success body — treat as successful with no data
      return { success: true } as ApiResponse<T>;
    }

    const data = JSON.parse(text);
    return data as ApiResponse<T>;
  } catch (err) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

// ============================================================
// Token management (used by login flows)
// ============================================================

export const tokenService = {
  setToken: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  getToken,
  clearToken: () => localStorage.removeItem(TOKEN_KEY),
};

// ============================================================
// API Service — always connects to the real Bloomberg backend
// ============================================================

export const apiService = {
  async getOrders(filters?: OrderFilters): Promise<ApiResponse<Order[]>> {
    const params = new URLSearchParams();
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== '' && value !== null) {
          params.append(key, String(value));
        }
      });
    }
    const query = params.toString();
    return apiFetch<Order[]>(`/api/orders${query ? `?${query}` : ''}`);
  },

  async batchUpdate(request: BatchUpdateRequest): Promise<ApiResponse<BatchUpdateResponse>> {
    return apiFetch<BatchUpdateResponse>('/api/orders/batch-update', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  async getStartupStatus(): Promise<ApiResponse<StartupStatusSnapshot>> {
    return apiFetch<StartupStatusSnapshot>('/api/startup-status');
  },

  async checkConnection(): Promise<ApiResponse<{ status: 'connected' | 'disconnected' }>> {
    const result = await apiFetch<StartupStatusSnapshot>('/api/startup-status');
    if (result.success && result.data) {
      const s = result.data.bloomberg.status === 'connected' ? 'connected' : 'disconnected';
      return { success: true, data: { status: s } };
    }
    return { success: true, data: { status: 'disconnected' } };
  },

  async refreshOrders(): Promise<ApiResponse<Order[]>> {
    return apiFetch<Order[]>('/api/orders/refresh');
  },

  async getOrdersStatus(): Promise<ApiResponse<{
    init_paint_done: boolean;
    order_count: number;
    route_count: number;
    subscription_failed: boolean;
    is_connected: boolean;
  }>> {
    return apiFetch('/api/orders/status');
  },

  async getRoutes(): Promise<ApiResponse<Route[]>> {
    return apiFetch<Route[]>('/api/routes');
  },

  async cancelRoute(request: CancelRouteRequest): Promise<ApiResponse<void>> {
    return apiFetch<void>('/api/routes/cancel', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  async modifyRoute(request: ModifyRouteRequest): Promise<ApiResponse<void>> {
    return apiFetch<void>('/api/routes/modify', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  async modifyOrder(request: ModifyOrderRequest): Promise<ApiResponse<void>> {
    return apiFetch<void>('/api/orders/modify', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  async routeOrder(request: RouteOrderRequest): Promise<ApiResponse<{
    success: boolean;
    orderId: string;
    routeId?: number;
    broker: string;
    quantity: number;
  }>> {
    return apiFetch('/api/orders/route', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  async getAssetClass(ticker: string): Promise<ApiResponse<{ ticker: string; assetClass: string }>> {
    const params = new URLSearchParams({ ticker });
    return apiFetch<{ ticker: string; assetClass: string }>(`/api/asset-class?${params}`);
  },

  async getBrokers(assetClass: string = 'EQTY'): Promise<ApiResponse<{ brokers: string[] }>> {
    const params = new URLSearchParams({ assetClass });
    return apiFetch<{ brokers: string[] }>(`/api/brokers?${params}`);
  },

  async getStoredBrokerAlgorithms(): Promise<ApiResponse<{
    configs: BrokerAlgorithmConfig[];
    lastUpdated: string;
    needsRefresh: boolean;
    count: number;
  }>> {
    return apiFetch('/api/broker-algorithms');
  },

  async refreshBrokerAlgorithms(): Promise<ApiResponse<{
    configs: BrokerAlgorithmConfig[];
    count: number;
    lastUpdated: string;
  }>> {
    return apiFetch('/api/broker-algorithms/refresh', {
      method: 'POST',
    });
  },

  async getBrokerAlgorithmsStatus(): Promise<ApiResponse<{
    lastUpdated: string | null;
    needsRefresh: boolean;
    hasData: boolean;
  }>> {
    return apiFetch('/api/broker-algorithms/status');
  },

  async getTraderInfo(): Promise<ApiResponse<TraderInfo>> {
    return apiFetch<TraderInfo>('/api/trader-info');
  },

  async getBrokerStrategies(broker: string, assetClass: string = 'EQTY'): Promise<ApiResponse<BrokerStrategiesResponse>> {
    const params = new URLSearchParams({ broker, assetClass });
    return apiFetch<BrokerStrategiesResponse>(`/api/broker-strategies?${params}`);
  },

  async getBrokerStrategyInfo(broker: string, strategy: string, assetClass: string = 'EQTY'): Promise<ApiResponse<BrokerStrategyInfoResponse>> {
    const params = new URLSearchParams({ broker, strategy, assetClass });
    return apiFetch<BrokerStrategyInfoResponse>(`/api/broker-strategy-info?${params}`);
  },
};

// ============================================================
// Cached API Service — wraps apiService with caching for low-frequency data
// ============================================================

// Cache instances for broker strategies
const brokerStrategiesCache = new Map<string, ReturnType<typeof createCache<BrokerStrategiesResponse>>>();
const strategyInfoCache = new Map<string, ReturnType<typeof createCache<BrokerStrategyInfoResponse>>>();
const assetClassCache = new Map<string, string>();

function getBrokerStrategiesCacheKey(broker: string, assetClass: string): string {
  return `${broker}_${assetClass}`;
}

function getStrategyInfoCacheKey(broker: string, strategy: string, assetClass: string): string {
  return `${broker}_${strategy}_${assetClass}`;
}

export const cachedApiService = {
  async resolveAssetClass(ticker?: string, fallback: string = 'EQTY'): Promise<string> {
    const normalizedTicker = ticker?.trim();
    if (!normalizedTicker) return fallback;

    const cacheKey = normalizedTicker.toUpperCase();
    const cached = assetClassCache.get(cacheKey);
    if (cached) return cached;

    const res = await apiService.getAssetClass(normalizedTicker);
    const assetClass = res.success && res.data?.assetClass ? res.data.assetClass : fallback;
    assetClassCache.set(cacheKey, assetClass);
    return assetClass;
  },

  /**
   * Get broker strategies with caching and file fallback
   * @param broker - Broker code
   * @param assetClass - Asset class (default: EQTY)
   * @param forceRefresh - Force refresh from API even if cache is valid
   * @param preferFile - Prefer file data over API (for offline/quick loading)
   */
  async getBrokerStrategies(
    broker: string,
    assetClass: string = 'EQTY',
    forceRefresh: boolean = false,
    preferFile: boolean = false
  ): Promise<ApiResponse<BrokerStrategiesResponse>> {
    const cacheKey = getBrokerStrategiesCacheKey(broker, assetClass);

    // If preferFile is true, try file first before checking cache
    if (preferFile && !forceRefresh) {
      const fileData = await getBrokerStrategiesFromFile(broker, assetClass);
      if (fileData) {
        console.log(`[cachedApiService] Using file data for ${broker} strategies`);
        return {
          success: true,
          data: fileData,
          message: 'From file defaults',
        };
      }
    }

    // Get or create cache for this broker+assetClass
    let cache = brokerStrategiesCache.get(cacheKey);
    if (!cache) {
      cache = createCache<BrokerStrategiesResponse>(CACHE_CONFIGS.BROKER_STRATEGIES(broker));
      brokerStrategiesCache.set(cacheKey, cache);
    }

    try {
      const data = await getOrFetch(
        cache,
        async () => {
          const res = await apiService.getBrokerStrategies(broker, assetClass);
          if (!res.success || !res.data) {
            throw new Error(res.error || 'Failed to fetch broker strategies');
          }
          return res.data;
        },
        { forceRefresh }
      );

      return {
        success: true,
        data,
        message: forceRefresh ? 'Refreshed from API' : (cache.isValid() ? 'From cache' : 'From API'),
      };
    } catch (error) {
      // On error, try to fallback to file data
      const fileData = await getBrokerStrategiesFromFile(broker, assetClass);
      if (fileData) {
        console.log(`[cachedApiService] API failed, using file fallback for ${broker} strategies`);
        return {
          success: true,
          data: fileData,
          message: 'From file (API unavailable)',
        };
      }

      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error',
      };
    }
  },

  /**
   * Get broker strategy info with caching and file fallback
   * @param broker - Broker code
   * @param strategy - Strategy name
   * @param assetClass - Asset class (default: EQTY)
   * @param forceRefresh - Force refresh from API even if cache is valid
   * @param preferFile - Prefer file data over API (for offline/quick loading)
   */
  async getBrokerStrategyInfo(
    broker: string,
    strategy: string,
    assetClass: string = 'EQTY',
    forceRefresh: boolean = false,
    preferFile: boolean = false
  ): Promise<ApiResponse<BrokerStrategyInfoResponse>> {
    const cacheKey = getStrategyInfoCacheKey(broker, strategy, assetClass);

    // If preferFile is true, try file first before checking cache
    if (preferFile && !forceRefresh) {
      const fileData = await getStrategyInfoFromFile(broker, strategy, assetClass);
      if (fileData) {
        console.log(`[cachedApiService] Using file data for ${broker}/${strategy} params`);
        return {
          success: true,
          data: fileData,
          message: 'From file defaults',
        };
      }
    }

    // Get or create cache for this broker+strategy+assetClass
    let cache = strategyInfoCache.get(cacheKey);
    if (!cache) {
      cache = createCache<BrokerStrategyInfoResponse>(CACHE_CONFIGS.STRATEGY_INFO(broker, strategy));
      strategyInfoCache.set(cacheKey, cache);
    }

    try {
      const data = await getOrFetch(
        cache,
        async () => {
          const res = await apiService.getBrokerStrategyInfo(broker, strategy, assetClass);
          if (!res.success || !res.data) {
            throw new Error(res.error || 'Failed to fetch strategy info');
          }
          return res.data;
        },
        { forceRefresh }
      );

      // Merge with file defaults if available (file values take precedence for defaults)
      const fileData = await getStrategyInfoFromFile(broker, strategy, assetClass);
      if (fileData && data.fields) {
        const mergedFields = mergeWithDefaults(data.fields, fileData.fields);
        return {
          success: true,
          data: { ...data, fields: mergedFields },
          message: forceRefresh ? 'Refreshed from API (with defaults)' : (cache.isValid() ? 'From cache (with defaults)' : 'From API (with defaults)'),
        };
      }

      return {
        success: true,
        data,
        message: forceRefresh ? 'Refreshed from API' : (cache.isValid() ? 'From cache' : 'From API'),
      };
    } catch (error) {
      // On error, try to fallback to file data
      const fileData = await getStrategyInfoFromFile(broker, strategy, assetClass);
      if (fileData) {
        console.log(`[cachedApiService] API failed, using file fallback for ${broker}/${strategy}`);
        return {
          success: true,
          data: fileData,
          message: 'From file (API unavailable)',
        };
      }

      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error',
      };
    }
  },

  /**
   * Clear all broker strategy caches
   */
  clearBrokerStrategyCaches(): void {
    brokerStrategiesCache.clear();
    strategyInfoCache.clear();
    assetClassCache.clear();
  },

  /**
   * Get cache status for debugging
   */
  getCacheStatus(): {
    brokerStrategiesCached: number;
    strategyInfoCached: number;
  } {
    return {
      brokerStrategiesCached: brokerStrategiesCache.size,
      strategyInfoCached: strategyInfoCache.size,
    };
  },
};


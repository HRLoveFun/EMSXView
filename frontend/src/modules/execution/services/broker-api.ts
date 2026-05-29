/** Broker, strategy, trader & asset-class API methods. */

import type {
  TraderInfo, BrokerStrategiesResponse, BrokerStrategyInfoResponse, BrokerAlgorithmConfig,
} from '@execution/types';
import type { ApiResponse } from '@shared/types';
import { createCache, CACHE_CONFIGS, getOrFetch } from '@execution/lib';
import { getBrokerStrategiesFromFile, getStrategyInfoFromFile, mergeWithDefaults } from './strategy-data-service';
import { apiFetch } from './http-client';

export const brokerApi = {
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
    return apiFetch('/api/broker-algorithms/refresh', { method: 'POST' });
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
// Cached Broker API — wraps brokerApi with caching + file fallback
// ============================================================

const brokerStrategiesCache = new Map<string, ReturnType<typeof createCache<BrokerStrategiesResponse>>>();
const strategyInfoCache = new Map<string, ReturnType<typeof createCache<BrokerStrategyInfoResponse>>>();
const assetClassCache = new Map<string, string>();

function getBrokerStrategiesCacheKey(broker: string, assetClass: string): string {
  return `${broker}_${assetClass}`;
}

function getStrategyInfoCacheKey(broker: string, strategy: string, assetClass: string): string {
  return `${broker}_${strategy}_${assetClass}`;
}

export const cachedBrokerApi = {
  async resolveAssetClass(ticker?: string, fallback: string = 'EQTY'): Promise<string> {
    const normalizedTicker = ticker?.trim();
    if (!normalizedTicker) return fallback;

    const cacheKey = normalizedTicker.toUpperCase();
    const cached = assetClassCache.get(cacheKey);
    if (cached) return cached;

    const res = await brokerApi.getAssetClass(normalizedTicker);
    const assetClass = res.success && res.data?.assetClass ? res.data.assetClass : fallback;
    assetClassCache.set(cacheKey, assetClass);
    return assetClass;
  },

  async getBrokerStrategies(
    broker: string,
    assetClass: string = 'EQTY',
    forceRefresh: boolean = false,
    preferFile: boolean = false
  ): Promise<ApiResponse<BrokerStrategiesResponse>> {
    const cacheKey = getBrokerStrategiesCacheKey(broker, assetClass);

    if (preferFile && !forceRefresh) {
      const fileData = await getBrokerStrategiesFromFile(broker, assetClass);
      if (fileData) {
        console.log(`[cachedApiService] Using file data for ${broker} strategies`);
        return { success: true, data: fileData, message: 'From file defaults' };
      }
    }

    let cache = brokerStrategiesCache.get(cacheKey);
    if (!cache) {
      cache = createCache<BrokerStrategiesResponse>(CACHE_CONFIGS.BROKER_STRATEGIES(broker));
      brokerStrategiesCache.set(cacheKey, cache);
    }

    try {
      const data = await getOrFetch(
        cache,
        async () => {
          const res = await brokerApi.getBrokerStrategies(broker, assetClass);
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
      const fileData = await getBrokerStrategiesFromFile(broker, assetClass);
      if (fileData) {
        console.log(`[cachedApiService] API failed, using file fallback for ${broker} strategies`);
        return { success: true, data: fileData, message: 'From file (API unavailable)' };
      }
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
    }
  },

  async getBrokerStrategyInfo(
    broker: string,
    strategy: string,
    assetClass: string = 'EQTY',
    forceRefresh: boolean = false,
    preferFile: boolean = false
  ): Promise<ApiResponse<BrokerStrategyInfoResponse>> {
    const cacheKey = getStrategyInfoCacheKey(broker, strategy, assetClass);

    if (preferFile && !forceRefresh) {
      const fileData = await getStrategyInfoFromFile(broker, strategy, assetClass);
      if (fileData) {
        console.log(`[cachedApiService] Using file data for ${broker}/${strategy} params`);
        return { success: true, data: fileData, message: 'From file defaults' };
      }
    }

    let cache = strategyInfoCache.get(cacheKey);
    if (!cache) {
      cache = createCache<BrokerStrategyInfoResponse>(CACHE_CONFIGS.STRATEGY_INFO(broker, strategy));
      strategyInfoCache.set(cacheKey, cache);
    }

    try {
      const data = await getOrFetch(
        cache,
        async () => {
          const res = await brokerApi.getBrokerStrategyInfo(broker, strategy, assetClass);
          if (!res.success || !res.data) {
            throw new Error(res.error || 'Failed to fetch strategy info');
          }
          return res.data;
        },
        { forceRefresh }
      );

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
      const fileData = await getStrategyInfoFromFile(broker, strategy, assetClass);
      if (fileData) {
        console.log(`[cachedApiService] API failed, using file fallback for ${broker}/${strategy}`);
        return { success: true, data: fileData, message: 'From file (API unavailable)' };
      }
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
    }
  },

  clearBrokerStrategyCaches(): void {
    brokerStrategiesCache.clear();
    strategyInfoCache.clear();
    assetClassCache.clear();
  },

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

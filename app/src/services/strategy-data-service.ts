/**
 * Strategy Data Service - File-based storage for broker strategies and parameters
 * 
 * This service provides:
 * 1. Offline access to strategy data via JSON files
 * 2. User-customizable default parameter values
 * 3. Fallback when Bloomberg API is unavailable
 * 4. Import/export functionality for sharing configurations
 */

import type { BrokerStrategyField, BrokerStrategiesResponse, BrokerStrategyInfoResponse } from '@/types';

// File paths (relative to public directory)
const STRATEGIES_FILE = '/strategy-data/default-strategies.json';
const STRATEGY_PARAMS_FILE = '/strategy-data/default-strategy-params.json';

// Cache for file data
let fileCache: {
  strategies: Map<string, BrokerStrategiesResponse>;
  params: Map<string, BrokerStrategyInfoResponse>;
  lastLoaded: Date | null;
} = {
  strategies: new Map(),
  params: new Map(),
  lastLoaded: null,
};

/**
 * Load strategy data from JSON files
 */
async function loadStrategyFiles(): Promise<{
  strategies: Record<string, { assetClasses: string[]; strategies: string[] }>;
  params: Record<string, Record<string, { fields: BrokerStrategyField[] }>>;
}> {
  try {
    const [strategiesRes, paramsRes] = await Promise.all([
      fetch(STRATEGIES_FILE),
      fetch(STRATEGY_PARAMS_FILE),
    ]);

    if (!strategiesRes.ok || !paramsRes.ok) {
      throw new Error('Failed to load strategy data files');
    }

    const strategiesData = await strategiesRes.json();
    const paramsData = await paramsRes.json();

    return {
      strategies: strategiesData.brokers || {},
      params: paramsData.strategies || {},
    };
  } catch (error) {
    console.warn('[StrategyDataService] Failed to load strategy files:', error);
    return { strategies: {}, params: {} };
  }
}

/**
 * Initialize the file cache
 */
async function initializeCache(): Promise<void> {
  if (fileCache.lastLoaded) {
    return; // Already loaded
  }

  const data = await loadStrategyFiles();

  // Populate strategies cache
  for (const [broker, config] of Object.entries(data.strategies)) {
    fileCache.strategies.set(broker, {
      broker,
      assetClass: config.assetClasses[0] || 'EQTY',
      strategies: config.strategies,
    });
  }

  // Populate params cache
  for (const [broker, strategies] of Object.entries(data.params)) {
    for (const [strategy, info] of Object.entries(strategies)) {
      const key = `${broker}_${strategy}`;
      fileCache.params.set(key, {
        broker,
        strategy,
        assetClass: 'EQTY',
        fields: info.fields || [],
      });
    }
  }

  fileCache.lastLoaded = new Date();
  console.log('[StrategyDataService] File cache initialized:', {
    strategies: fileCache.strategies.size,
    params: fileCache.params.size,
  });
}

/**
 * Get broker strategies from file
 */
export async function getBrokerStrategiesFromFile(
  broker: string,
  assetClass: string = 'EQTY'
): Promise<BrokerStrategiesResponse | null> {
  await initializeCache();
  
  const data = fileCache.strategies.get(broker);
  if (!data) {
    return null;
  }

  return {
    broker,
    assetClass,
    strategies: data.strategies,
  };
}

/**
 * Get strategy info from file
 */
export async function getStrategyInfoFromFile(
  broker: string,
  strategy: string,
  assetClass: string = 'EQTY'
): Promise<BrokerStrategyInfoResponse | null> {
  await initializeCache();

  const key = `${broker}_${strategy}`;
  const data = fileCache.params.get(key);
  if (!data) {
    return null;
  }

  return {
    broker,
    strategy,
    assetClass,
    fields: data.fields,
  };
}

/**
 * Check if file data exists for a broker
 */
export async function hasBrokerStrategiesInFile(broker: string): Promise<boolean> {
  await initializeCache();
  return fileCache.strategies.has(broker);
}

/**
 * Check if file data exists for a strategy
 */
export async function hasStrategyInfoInFile(
  broker: string,
  strategy: string
): Promise<boolean> {
  await initializeCache();
  return fileCache.params.has(`${broker}_${strategy}`);
}

/**
 * Get all available brokers from file
 */
export async function getAvailableBrokersFromFile(): Promise<string[]> {
  await initializeCache();
  return Array.from(fileCache.strategies.keys());
}

/**
 * Export current configuration to a downloadable JSON file
 * This exports data from LocalStorage (which contains real API data)
 */
export function exportConfiguration(): void {
  // Collect strategies from LocalStorage
  const brokers: Record<string, { assetClasses: string[]; strategies: string[] }> = {};
  const params: Record<string, Record<string, { fields: BrokerStrategyField[] }>> = {};

  console.log('[StrategyDataService] Starting LocalStorage scan for cached API data...');

  // Scan LocalStorage for cached strategy data
  if (typeof window !== 'undefined' && window.localStorage) {
    const totalKeys = localStorage.length;
    console.log(`[StrategyDataService] Scanning ${totalKeys} LocalStorage entries...`);

    let strategiesFound = 0;
    let paramsFound = 0;

    for (let i = 0; i < totalKeys; i++) {
      const key = localStorage.key(i);
      if (!key) continue;

      // Parse broker strategies cache keys: emsx_cache_broker_strategies_{broker}
      const strategiesMatch = key.match(/^emsx_cache_broker_strategies_(.+)$/);
      if (strategiesMatch) {
        try {
          const broker = strategiesMatch[1];
          const rawData = localStorage.getItem(key);
          const data = JSON.parse(rawData || '{}');
          console.log(`[StrategyDataService] Found strategies cache for broker: ${broker}`, data);
          if (data.data && data.data.strategies) {
            brokers[broker] = {
              assetClasses: [data.data.assetClass || 'EQTY'],
              strategies: data.data.strategies,
            };
            strategiesFound++;
          }
        } catch (e) {
          console.warn('[StrategyDataService] Failed to parse strategies cache:', e);
        }
      }

      // Parse strategy info cache keys: emsx_cache_strategy_info_{broker}_{strategy}
      const infoMatch = key.match(/^emsx_cache_strategy_info_(.+)_(.+)$/);
      if (infoMatch) {
        try {
          const broker = infoMatch[1];
          const strategy = infoMatch[2];
          const rawData = localStorage.getItem(key);
          const data = JSON.parse(rawData || '{}');
          console.log(`[StrategyDataService] Found strategy info cache: ${broker}/${strategy}`, data);
          if (data.data && data.data.fields) {
            if (!params[broker]) {
              params[broker] = {};
            }
            params[broker][strategy] = {
              fields: data.data.fields,
            };
            paramsFound++;
          }
        } catch (e) {
          console.warn('[StrategyDataService] Failed to parse strategy info cache:', e);
        }
      }
    }

    console.log(`[StrategyDataService] Scan complete: ${strategiesFound} brokers, ${paramsFound} strategy params found`);
  } else {
    console.warn('[StrategyDataService] LocalStorage not available');
  }

  const exportData = {
    version: '1.0',
    exportedAt: new Date().toISOString(),
    description: 'Exported from LocalStorage cache. Copy this data to default-strategies.json and default-strategy-params.json',
    source: 'Bloomberg API via LocalStorage cache',
    brokers,
    strategies: params,
  };

  const blob = new Blob([JSON.stringify(exportData, null, 2)], {
    type: 'application/json',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `emsx-strategy-export-${new Date().toISOString().split('T')[0]}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);

  console.log('[StrategyDataService] Exported configuration:', { brokers: Object.keys(brokers).length, strategies: Object.keys(params).length });
}

/**
 * Import configuration from a file
 */
export async function importConfiguration(
  file: File
): Promise<{ success: boolean; error?: string }> {
  try {
    const text = await file.text();
    const data = JSON.parse(text);

    // Validate structure
    if (!data.brokers || typeof data.brokers !== 'object') {
      return { success: false, error: 'Invalid configuration format: missing brokers' };
    }

    // TODO: Apply imported configuration
    // This would require backend support to write to the public directory
    // For now, we just validate and return success

    return { success: true };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to parse file',
    };
  }
}

/**
 * Merge API data with file defaults
 * File defaults take precedence for user-customized values
 */
export function mergeWithDefaults(
  apiFields: BrokerStrategyField[],
  fileFields: BrokerStrategyField[]
): BrokerStrategyField[] {
  // Create a map of file fields for quick lookup
  const fileFieldMap = new Map(fileFields.map(f => [f.fieldName, f]));

  // Merge: API fields as base, file values override
  return apiFields.map(apiField => {
    const fileField = fileFieldMap.get(apiField.fieldName);
    if (fileField && fileField.stringValue) {
      // Use file value as default if it exists and is not empty
      return {
        ...apiField,
        stringValue: fileField.stringValue,
      };
    }
    return apiField;
  });
}

/**
 * Clear the file cache (useful for development/hot reload)
 */
export function clearFileCache(): void {
  fileCache = {
    strategies: new Map(),
    params: new Map(),
    lastLoaded: null,
  };
  console.log('[StrategyDataService] File cache cleared');
}

/**
 * Get cache status for debugging
 */
export function getFileCacheStatus(): {
  initialized: boolean;
  strategiesCount: number;
  paramsCount: number;
  lastLoaded: string | null;
} {
  return {
    initialized: fileCache.lastLoaded !== null,
    strategiesCount: fileCache.strategies.size,
    paramsCount: fileCache.params.size,
    lastLoaded: fileCache.lastLoaded?.toISOString() || null,
  };
}

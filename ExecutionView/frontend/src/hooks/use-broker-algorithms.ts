/**
 * useBrokerAlgorithms Hook
 * 
 * Manages broker algorithm configuration data with:
 * - Initial data loading from backend storage
 * - Daily freshness checks
 * - Automatic refresh from Bloomberg API when needed
 * - Hierarchical data structure (Exchange -> Broker -> Strategy)
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { apiService } from '@/services/api';

// Types
export interface BrokerAlgorithmConfig {
  broker: string;
  assetClass: string;
  strategies: StrategyConfig[];
}

export interface StrategyConfig {
  name: string;
  parameters: StrategyParameter[];
}

export interface StrategyParameter {
  fieldName: string;
  stringValue: string;
  disable: string;
  order: number;
  dataType: 'string' | 'number' | 'boolean';
  description: string;
}

export interface BrokerAlgorithmState {
  configs: BrokerAlgorithmConfig[];
  isLoading: boolean;
  isRefreshing: boolean;
  lastUpdated: Date | null;
  error: string | null;
}

// Storage keys
const STORAGE_KEY_DATA = 'emsx_broker_algorithm_data';
const STORAGE_KEY_TIMESTAMP = 'emsx_broker_algorithm_timestamp';
const STORAGE_KEY_VERSION = 'emsx_broker_algorithm_version';

// Current data version (bump when structure changes)
const DATA_VERSION = '1.1';


/**
 * Check if data needs refresh (older than 1 day or not from today)
 */
function needsRefresh(lastUpdated: Date | null): boolean {
  if (!lastUpdated) return true;
  
  const now = new Date();
  const lastUpdateDay = new Date(lastUpdated).setHours(0, 0, 0, 0);
  const today = new Date(now).setHours(0, 0, 0, 0);
  
  return lastUpdateDay < today;
}

/**
 * Load data from localStorage
 */
function loadStoredData(): { data: BrokerAlgorithmConfig[] | null; timestamp: Date | null } {
  try {
    const storedVersion = localStorage.getItem(STORAGE_KEY_VERSION);
    if (storedVersion !== DATA_VERSION) {
      // Version mismatch, clear old data
      localStorage.removeItem(STORAGE_KEY_DATA);
      localStorage.removeItem(STORAGE_KEY_TIMESTAMP);
      return { data: null, timestamp: null };
    }

    const storedData = localStorage.getItem(STORAGE_KEY_DATA);
    const storedTimestamp = localStorage.getItem(STORAGE_KEY_TIMESTAMP);
    
    if (storedData && storedTimestamp) {
      return {
        data: JSON.parse(storedData),
        timestamp: new Date(storedTimestamp),
      };
    }
  } catch (error) {
    console.error('[useBrokerAlgorithms] Failed to load stored data:', error);
  }
  
  return { data: null, timestamp: null };
}

/**
 * Save data to localStorage
 */
function saveStoredData(data: BrokerAlgorithmConfig[], timestamp: Date): void {
  try {
    localStorage.setItem(STORAGE_KEY_DATA, JSON.stringify(data));
    localStorage.setItem(STORAGE_KEY_TIMESTAMP, timestamp.toISOString());
    localStorage.setItem(STORAGE_KEY_VERSION, DATA_VERSION);
  } catch (error) {
    console.error('[useBrokerAlgorithms] Failed to save data:', error);
  }
}

/**
 * Main hook for managing broker algorithm configuration
 */
export function useBrokerAlgorithms() {
  const [state, setState] = useState<BrokerAlgorithmState>({
    configs: [],
    isLoading: true,
    isRefreshing: false,
    lastUpdated: null,
    error: null,
  });

  const refreshInProgress = useRef(false);

  /**
   * Load broker algorithm data from backend stored endpoint.
   * Falls back to individual API calls only if stored data unavailable.
   */
  const fetchFromBackendStorage = useCallback(async (): Promise<{ configs: BrokerAlgorithmConfig[]; lastUpdated: Date | null }> => {
    // Try the stored broker algorithms endpoint first (fast, single request)
    try {
      const storedRes = await apiService.getStoredBrokerAlgorithms();
      if (storedRes.success && storedRes.data?.configs && storedRes.data.configs.length > 0) {
        const backendConfigs: BrokerAlgorithmConfig[] = storedRes.data.configs.map(c => ({
          broker: c.broker,
          assetClass: c.assetClass || 'EQTY',
          strategies: (c.strategies || []).map(s => ({
            name: s.name,
            parameters: (s.parameters || []).map(p => ({
              fieldName: p.fieldName,
              stringValue: p.stringValue,
              disable: p.disable,
              order: p.order ?? 0,
              dataType: inferDataType(p.fieldName, p.stringValue),
              description: getFieldDescription(p.fieldName),
            })),
          })),
        }));
        const ts = storedRes.data.lastUpdated ? new Date(storedRes.data.lastUpdated) : null;
        console.log(`[useBrokerAlgorithms] Loaded ${backendConfigs.length} configs from backend storage`);
        return { configs: backendConfigs, lastUpdated: ts };
      }
    } catch (err) {
      console.warn('[useBrokerAlgorithms] Backend stored data unavailable:', err);
    }
    return { configs: [], lastUpdated: null };
  }, []);

  /**
   * Trigger a backend-side refresh (single POST request that refreshes all brokers on the server)
   */
  const triggerBackendRefresh = useCallback(async (): Promise<BrokerAlgorithmConfig[]> => {
    const refreshRes = await apiService.refreshBrokerAlgorithms();
    if (refreshRes.success && refreshRes.data?.configs) {
      return refreshRes.data.configs.map(c => ({
        broker: c.broker,
        assetClass: c.assetClass || 'EQTY',
        strategies: (c.strategies || []).map(s => ({
          name: s.name,
          parameters: (s.parameters || []).map(p => ({
            fieldName: p.fieldName,
            stringValue: p.stringValue,
            disable: p.disable || '0',
            order: p.order ?? 0,
            dataType: inferDataType(p.fieldName, p.stringValue),
            description: getFieldDescription(p.fieldName),
          })),
        })),
      }));
    }
    throw new Error(refreshRes.error || 'Failed to refresh broker algorithms from backend');
  }, []);

  /**
   * Refresh data from backend API
   */
  const refreshData = useCallback(async () => {
    if (refreshInProgress.current) return;
    refreshInProgress.current = true;

    setState(prev => ({ ...prev, isRefreshing: true, error: null }));

    try {
      const configs = await triggerBackendRefresh();
      const now = new Date();
      
      saveStoredData(configs, now);
      
      setState({
        configs,
        isLoading: false,
        isRefreshing: false,
        lastUpdated: now,
        error: null,
      });
    } catch (error) {
      console.error('[useBrokerAlgorithms] Refresh failed:', error);
      setState(prev => ({
        ...prev,
        isLoading: false,
        isRefreshing: false,
        error: error instanceof Error ? error.message : 'Failed to refresh data',
      }));
    } finally {
      refreshInProgress.current = false;
    }
  }, [triggerBackendRefresh]);

  /**
   * Load data on mount - check freshness and refresh if needed
   */
  useEffect(() => {
    const initialize = async () => {
      setState(prev => ({ ...prev, isLoading: true }));

      try {
        // 1. Try localStorage cache first (instant, no network)
        const { data: localData, timestamp: localTs } = loadStoredData();
        if (localData && !needsRefresh(localTs)) {
          setState({
            configs: localData,
            isLoading: false,
            isRefreshing: false,
            lastUpdated: localTs,
            error: null,
          });
          return;
        }

        // Show stale local data while loading fresh data
        if (localData) {
          setState({
            configs: localData,
            isLoading: false,
            isRefreshing: true,
            lastUpdated: localTs,
            error: null,
          });
        }

        // 2. Try backend stored data (single fast request)
        const { configs: backendConfigs, lastUpdated: backendTs } = await fetchFromBackendStorage();
        if (backendConfigs.length > 0) {
          const ts = backendTs || new Date();
          saveStoredData(backendConfigs, ts);
          setState({
            configs: backendConfigs,
            isLoading: false,
            isRefreshing: false,
            lastUpdated: ts,
            error: null,
          });

          // If backend data is stale, trigger background refresh
          if (needsRefresh(backendTs)) {
            refreshData();
          }
          return;
        }

        // 3. No stored data anywhere — trigger full refresh from Bloomberg
        await refreshData();

        // 4. If refresh failed and we still have no data, try fetching just the broker list
        //    as a minimal fallback so the UI is at least partially functional
        setState(prev => {
          if (prev.configs.length === 0 && prev.error) {
            // Attempt a lightweight broker list fetch
            apiService.getBrokers('EQTY').then(res => {
              if (res.success && res.data?.brokers && res.data.brokers.length > 0) {
                const minimalConfigs: BrokerAlgorithmConfig[] = res.data.brokers.map(broker => ({
                  broker,
                  assetClass: 'EQTY',
                  strategies: [],
                }));
                setState(s => ({
                  ...s,
                  configs: minimalConfigs,
                  error: 'Loaded broker list only — strategy data unavailable. Click "Refresh Now" to retry.',
                }));
              }
            }).catch(() => { /* Best-effort fallback, silently ignore */ });
          }
          return prev;
        });
      } catch (error) {
        console.error('[useBrokerAlgorithms] Initialization failed:', error);
        setState(prev => ({
          ...prev,
          isLoading: false,
          error: error instanceof Error ? error.message : 'Failed to initialize',
        }));
      }
    };

    // Idle-schedule initial hydration so that the first paint of the
    // execution view is not blocked by broker/algorithm fetching.
    // Fallback to setTimeout(0) on browsers without requestIdleCallback.
    const ric = (window as unknown as {
      requestIdleCallback?: (cb: () => void, opts?: { timeout?: number }) => number;
      cancelIdleCallback?: (id: number) => void;
    });
    let idleHandle: number | null = null;
    let timeoutHandle: ReturnType<typeof setTimeout> | null = null;
    if (ric.requestIdleCallback) {
      idleHandle = ric.requestIdleCallback(
        () => {
          initialize();
        },
        { timeout: 1500 },
      );
    } else {
      timeoutHandle = setTimeout(initialize, 0);
    }
    return () => {
      if (idleHandle !== null && ric.cancelIdleCallback) {
        ric.cancelIdleCallback(idleHandle);
      }
      if (timeoutHandle !== null) {
        clearTimeout(timeoutHandle);
      }
    };
  }, [refreshData, fetchFromBackendStorage]);

  /**
   * Force refresh data
   */
  const forceRefresh = useCallback(async () => {
    await refreshData();
  }, [refreshData]);

  /**
   * Get strategies for a specific broker
   */
  const getStrategiesForBroker = useCallback((broker: string): StrategyConfig[] => {
    const config = state.configs.find(c => c.broker === broker);
    return config?.strategies || [];
  }, [state.configs]);

  /**
   * Get parameters for a specific strategy
   */
  const getParametersForStrategy = useCallback((broker: string, strategy: string): StrategyParameter[] => {
    const config = state.configs.find(c => c.broker === broker);
    const strategyConfig = config?.strategies.find(s => s.name === strategy);
    return strategyConfig?.parameters || [];
  }, [state.configs]);

  return {
    ...state,
    refreshData: forceRefresh,
    getStrategiesForBroker,
    getParametersForStrategy,
  };
}

// Helper functions
function inferDataType(fieldName: string, value: string): 'string' | 'number' | 'boolean' {
  const lowerName = fieldName.toLowerCase();
  if (lowerName.includes('rate') || lowerName.includes('qty') || lowerName.includes('amount') || lowerName.includes('price')) {
    return 'number';
  }
  if (lowerName.includes('enabled') || lowerName.includes('active') || lowerName.includes('flag')) {
    return 'boolean';
  }
  if (value === 'Y' || value === 'N' || value === 'true' || value === 'false') {
    return 'boolean';
  }
  if (!isNaN(parseFloat(value)) && isFinite(Number(value))) {
    return 'number';
  }
  return 'string';
}

function getFieldDescription(fieldName: string): string {
  const descriptions: Record<string, string> = {
    'StartTime': 'Algorithm start time (HH:MM)',
    'EndTime': 'Algorithm end time (HH:MM)',
    'ParticipationRate': 'Target participation rate (%)',
    'Aggression': 'Trading aggression level (Passive/Neutral/Aggressive)',
    'PriceLimit': 'Maximum price limit for executions',
    'VWAP_Benchmark': 'VWAP benchmark type',
    'Completion': 'Target completion percentage',
    'Urgency': 'Execution urgency level',
  };
  return descriptions[fieldName] || `${fieldName} parameter`;
}

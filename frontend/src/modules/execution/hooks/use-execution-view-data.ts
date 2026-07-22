/**
 * useExecutionViewData — core hook for execution view data management.
 *
 * Holds all state and fetch functions, delegates polling effects to
 * useExecutionPoller and mutation callbacks to useExecutionMutations.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { apiService } from '@execution/services/execution-api';
import { CACHE_CONFIGS, createCache, getOrFetch } from '@execution/lib';
import type {
  Order,
  Route,
  TraderInfo,
} from '@execution/types';
import type { Toast } from '@shared/types';

import { useExecutionPoller } from './use-execution-poller';
import { useExecutionMutations } from './use-execution-mutations';

// ── Module-level cache (shared with poller) ──────────────────────────────
export const traderInfoCache = createCache<TraderInfo>(CACHE_CONFIGS.TRADER_INFO);

interface UseExecutionViewDataOptions {
  isAuthenticated: boolean;
  isBackendReady: boolean;
  streamConnected: boolean;
  allowFallbackFetch?: boolean;
  onAuthenticationFailure: () => void;
  onToast: (type: Toast['type'], message: string) => void;
}

export function useExecutionViewData({
  isAuthenticated,
  isBackendReady,
  streamConnected,
  allowFallbackFetch = false,
  onAuthenticationFailure,
  onToast,
}: UseExecutionViewDataOptions) {
  // ── Core state ─────────────────────────────────────────────────────────
  const [allOrders, setAllOrders] = useState<Order[]>([]);
  const [allRoutes, setAllRoutes] = useState<Route[]>([]);
  const [currentTrader, setCurrentTrader] = useState('');
  const [selectedOrders, setSelectedOrders] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(false);

  // ── Shared refs ────────────────────────────────────────────────────────
  const initialDataLoadedRef = useRef(false);
  // Mutual exclusion: counts of in-flight user mutations.
  const inflightMutationsRef = useRef(0);
  // Dedup guard for manual refresh.
  const refreshInflightRef = useRef(false);

  // ── Fetch functions ────────────────────────────────────────────────────
  const fetchTraderInfo = useCallback(async (forceRefresh = false) => {
    try {
      const traderData = await getOrFetch(
        traderInfoCache,
        async () => {
          const res = await apiService.getTraderInfo();
          if (res.success && res.data) return res.data;
          throw new Error(res.error || 'Failed to fetch trader info');
        },
        { forceRefresh },
      );
      setCurrentTrader(traderData.traderName);
    } catch (error) {
      console.error('Fetch trader info error:', error);
    }
  }, []);

  const fetchOrdersAndRoutes = useCallback(async () => {
    try {
      const [ordersRes, routesRes] = await Promise.all([
        apiService.getOrders(),
        apiService.getRoutes(),
      ]);

      if (ordersRes.success && ordersRes.data) {
        setAllOrders(ordersRes.data);
      } else if (ordersRes.error?.toLowerCase().includes('authentication') || ordersRes.error?.toLowerCase().includes('401')) {
        onAuthenticationFailure();
        return;
      }

      if (routesRes.success && routesRes.data) {
        setAllRoutes(routesRes.data);
      }
    } catch (error) {
      console.error('Fetch orders/routes error:', error);
    }
  }, [onAuthenticationFailure]);

  const fetchOrders = useCallback(async () => {
    setIsLoading(true);
    try {
      const [response, routesRes] = await Promise.all([
        apiService.getOrders(),
        apiService.getRoutes(),
      ]);
      if (response.success && response.data) {
        setAllOrders(response.data);
        setSelectedOrders(new Set());
      } else if (response.error?.toLowerCase().includes('authentication') || response.error?.toLowerCase().includes('401')) {
        onAuthenticationFailure();
      } else {
        const msg = response.error || 'Failed to fetch orders';
        if (!msg.toLowerCase().includes('econnrefused') && !msg.toLowerCase().includes('unavailable')) {
          onToast('error', msg);
        } else {
          onToast('error', 'Cannot reach backend — is it running?');
        }
      }
      if (routesRes.success && routesRes.data) {
        setAllRoutes(routesRes.data);
      }
      await fetchTraderInfo(true);
    } catch (error) {
      onToast('error', 'Network error while fetching orders');
      console.error('Fetch orders error:', error);
    } finally {
      setIsLoading(false);
    }
  }, [fetchTraderInfo, onAuthenticationFailure, onToast]);

  // ── Initial data load ──────────────────────────────────────────────────
  useEffect(() => {
    if (!isAuthenticated) {
      initialDataLoadedRef.current = false;
      setAllOrders([]);
      setAllRoutes([]);
      setCurrentTrader('');
      setSelectedOrders(new Set());
      setIsLoading(false);
      return;
    }
    const canFetch = isBackendReady || allowFallbackFetch;
    if (!canFetch || initialDataLoadedRef.current) {
      return;
    }

    initialDataLoadedRef.current = true;
    fetchOrders();
    fetchTraderInfo();
  }, [allowFallbackFetch, fetchOrders, fetchTraderInfo, isAuthenticated, isBackendReady]);

  // ── Polling effects (delegated) ────────────────────────────────────────
  useExecutionPoller({
    isAuthenticated,
    isBackendReady,
    streamConnected,
    allowFallbackFetch,
    fetchOrdersAndRoutes,
    fetchTraderInfo,
    traderInfoCache,
    inflightMutationsRef,
    onToast,
  });

  // ── Mutations (delegated) ──────────────────────────────────────────────
  const mutations = useExecutionMutations({
    setAllOrders,
    setSelectedOrders,
    setIsLoading,
    fetchOrders,
    fetchOrdersAndRoutes,
    fetchTraderInfo,
    inflightMutationsRef,
    refreshInflightRef,
    onToast,
  });

  return {
    allOrders,
    allRoutes,
    currentTrader,
    selectedOrders,
    isLoading,
    fetchOrders,
    ...mutations,
  };
}

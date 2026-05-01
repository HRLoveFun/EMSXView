import { useCallback, useEffect, useRef, useState } from 'react';

import { apiService } from '@/services/api';
import { CACHE_CONFIGS, clearAllCaches, createCache, getOrFetch } from '@/lib/cache-manager';
import { getReconcileIntervalMs } from '@/lib/reconcile-settings';
import type {
  BatchUpdateRequest,
  CancelRouteRequest,
  ModifyOrderRequest,
  ModifyRouteRequest,
  Order,
  Route,
  RouteOrderRequest,
  Toast,
  TraderInfo,
} from '@/types';

interface UseExecutionViewDataOptions {
  isAuthenticated: boolean;
  isBackendReady: boolean;
  streamConnected: boolean;
  /**
   * If true, REST fetching is permitted even when the backend is not yet
   * marked ready. Used as a degraded-mode fallback when EMSX subscription
   * warming has exceeded the timeout but HTTP is reachable.
   */
  allowFallbackFetch?: boolean;
  onAuthenticationFailure: () => void;
  onToast: (type: Toast['type'], message: string) => void;
}

const traderInfoCache = createCache<TraderInfo>(CACHE_CONFIGS.TRADER_INFO);

export function useExecutionViewData({
  isAuthenticated,
  isBackendReady,
  streamConnected,
  allowFallbackFetch = false,
  onAuthenticationFailure,
  onToast,
}: UseExecutionViewDataOptions) {
  const [allOrders, setAllOrders] = useState<Order[]>([]);
  const [allRoutes, setAllRoutes] = useState<Route[]>([]);
  const [currentTrader, setCurrentTrader] = useState('');
  const [selectedOrders, setSelectedOrders] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(false);
  const initialDataLoadedRef = useRef(false);
  // Mutual exclusion: counts of in-flight user mutations. While > 0 the
  // background reconcile poll skips its tick so it can't clobber the
  // post-mutation snapshot the mutation handler is about to fetch itself.
  const inflightMutationsRef = useRef(0);
  // Dedup guard for manual refresh — second click while the first is still
  // running becomes a no-op instead of double-hitting the backend.
  const refreshInflightRef = useRef(false);
  // Consecutive reconcile failures. Surfaces a single warning toast at the
  // threshold so users know the table may be stale.
  const reconcileFailuresRef = useRef(0);
  const reconcileWarnedRef = useRef(false);

  const fetchTraderInfo = useCallback(async (forceRefresh = false) => {
    try {
      const traderData = await getOrFetch(
        traderInfoCache,
        async () => {
          const res = await apiService.getTraderInfo();
          if (res.success && res.data) {
            return res.data;
          }
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

  useEffect(() => {
    const canPoll = isBackendReady || allowFallbackFetch;
    if (!isAuthenticated || streamConnected || !canPoll) {
      return;
    }

    let active = true;
    let consecutiveErrors = 0;
    const maxConsecutiveErrors = 5;
    const baseInterval = 2000;
    const backoffInterval = 5000;

    const getInterval = () => {
      if (consecutiveErrors >= maxConsecutiveErrors) {
        return backoffInterval;
      }
      if (document.hidden) {
        return baseInterval * 2;
      }
      return baseInterval;
    };

    const poll = async () => {
      const startTime = Date.now();
      try {
        await fetchOrdersAndRoutes();
        consecutiveErrors = 0;
      } catch {
        consecutiveErrors += 1;
        if (consecutiveErrors === maxConsecutiveErrors) {
          console.warn('Multiple polling errors detected, backing off...');
        }
      }

      if (active) {
        const elapsed = Date.now() - startTime;
        const interval = getInterval();
        const delay = Math.max(0, interval - elapsed);
        timer = setTimeout(poll, delay);
      }
    };

    let timer = setTimeout(poll, baseInterval);

    const handleVisibilityChange = () => {
      clearTimeout(timer);
      if (active) {
        timer = setTimeout(poll, document.hidden ? baseInterval * 2 : baseInterval);
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      active = false;
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [allowFallbackFetch, fetchOrdersAndRoutes, isAuthenticated, isBackendReady, streamConnected]);

  // Reconcile poll — runs even while the WebSocket stream is connected, to
  // catch order/route status changes that the stream may have dropped.
  // Cadence is user-configurable (5/15/30/60s) and doubled when tab hidden.
  // Skipped while a user mutation is in flight so optimistic post-mutation
  // state is not clobbered by a stale backend read.
  useEffect(() => {
    if (!isAuthenticated || !isBackendReady || !streamConnected) {
      return;
    }

    let active = true;

    const tick = async () => {
      const base = getReconcileIntervalMs();
      if (inflightMutationsRef.current === 0) {
        try {
          await fetchOrdersAndRoutes();
          if (reconcileWarnedRef.current) {
            onToast('success', 'Data refresh recovered');
          }
          reconcileFailuresRef.current = 0;
          reconcileWarnedRef.current = false;
        } catch {
          reconcileFailuresRef.current += 1;
          if (reconcileFailuresRef.current >= 3 && !reconcileWarnedRef.current) {
            reconcileWarnedRef.current = true;
            onToast('error', 'Background refresh failing — table data may be stale');
          }
        }
      }
      if (active) {
        timer = setTimeout(tick, document.hidden ? base * 2 : base);
      }
    };

    let timer = setTimeout(tick, getReconcileIntervalMs());
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [fetchOrdersAndRoutes, isAuthenticated, isBackendReady, streamConnected, onToast]);

  useEffect(() => {
    if (!isAuthenticated || !isBackendReady) {
      return;
    }

    let active = true;
    const checkInterval = 30000;

    const checkAndRefresh = async () => {
      if (!traderInfoCache.isValid()) {
        await fetchTraderInfo();
      }

      if (active) {
        timer = setTimeout(checkAndRefresh, checkInterval);
      }
    };

    let timer = setTimeout(checkAndRefresh, checkInterval);

    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [fetchTraderInfo, isAuthenticated, isBackendReady]);

  const handleRefresh = useCallback(async () => {
    if (refreshInflightRef.current) return;
    refreshInflightRef.current = true;
    setIsLoading(true);
    try {
      const [response, routesRes] = await Promise.all([
        apiService.refreshOrders(),
        apiService.getRoutes(),
      ]);
      if (response.success && response.data) {
        setAllOrders(response.data);
        setSelectedOrders(new Set());
        onToast('success', 'Orders refreshed successfully');
      } else {
        onToast('error', response.error || 'Failed to refresh orders');
      }
      if (routesRes.success && routesRes.data) {
        setAllRoutes(routesRes.data);
      }
      await fetchTraderInfo(true);
    } catch (error) {
      onToast('error', 'Network error while refreshing orders');
      console.error('Refresh error:', error);
    } finally {
      setIsLoading(false);
      refreshInflightRef.current = false;
    }
  }, [fetchTraderInfo, onToast]);

  const handleBatchUpdate = useCallback(async (request: BatchUpdateRequest) => {
    setIsLoading(true);
    try {
      const response = await apiService.batchUpdate(request);
      if (response.success && response.data) {
        const result = response.data;
        if (result.success) {
          onToast('success', result.message || 'Batch update successful');
        } else {
          onToast('error', result.message || 'Some orders failed to update');
        }
        await fetchOrders();
        setSelectedOrders(new Set());
      } else {
        onToast('error', response.error || 'Batch update failed');
      }
    } catch (error) {
      onToast('error', 'Network error during batch update');
      console.error('Batch update error:', error);
    } finally {
      setIsLoading(false);
    }
  }, [fetchOrders, onToast]);

  const handleSelectionChange = useCallback((selectedIds: Set<string>) => {
    setSelectedOrders(selectedIds);
  }, []);

  const handleClearSelection = useCallback(() => {
    setSelectedOrders(new Set());
  }, []);

  const handleClearCache = useCallback(() => {
    clearAllCaches();
    fetchTraderInfo(true);
    onToast('info', 'Cache cleared');
  }, [fetchTraderInfo, onToast]);

  const handleCancelRoute = useCallback(async (request: CancelRouteRequest) => {
    inflightMutationsRef.current += 1;
    try {
      const response = await apiService.cancelRoute(request);
      if (response.success) {
        onToast('success', `Route ${request.routeId} cancel request sent`);
      } else {
        onToast('error', response.error || `Failed to cancel route ${request.routeId}`);
      }
    } catch (error) {
      onToast('error', 'Network error while cancelling route');
      console.error('Cancel route error:', error);
    } finally {
      inflightMutationsRef.current = Math.max(0, inflightMutationsRef.current - 1);
    }
  }, [onToast]);

  const handleModifyRoute = useCallback(async (request: ModifyRouteRequest) => {
    inflightMutationsRef.current += 1;
    try {
      const response = await apiService.modifyRoute(request);
      if (response.success) {
        onToast('success', `Route ${request.routeId} modify request sent`);
      } else {
        onToast('error', response.error || `Failed to modify route ${request.routeId}`);
      }
    } catch (error) {
      onToast('error', 'Network error while modifying route');
      console.error('Modify route error:', error);
    } finally {
      inflightMutationsRef.current = Math.max(0, inflightMutationsRef.current - 1);
    }
  }, [onToast]);

  const handleModifyOrder = useCallback(async (request: ModifyOrderRequest) => {
    inflightMutationsRef.current += 1;
    try {
      const response = await apiService.modifyOrder(request);
      if (response.success) {
        onToast('success', `Order ${request.orderId} modified successfully`);
        await fetchOrders();
      } else {
        onToast('error', response.error || `Failed to modify order ${request.orderId}`);
      }
    } catch (error) {
      onToast('error', 'Network error while modifying order');
      console.error('Modify order error:', error);
    } finally {
      inflightMutationsRef.current = Math.max(0, inflightMutationsRef.current - 1);
    }
  }, [fetchOrders, onToast]);

  const handleRouteOrder = useCallback(async (request: RouteOrderRequest) => {
    try {
      const response = await apiService.routeOrder(request);
      if (response.success) {
        onToast('success', `Route created for order ${request.orderId} to broker ${request.broker}`);
        await fetchOrders();
      } else {
        onToast('error', response.error || `Failed to route order ${request.orderId}`);
      }
    } catch (error) {
      onToast('error', 'Network error while routing order');
      console.error('Route order error:', error);
    }
  }, [fetchOrders, onToast]);

  return {
    allOrders,
    allRoutes,
    currentTrader,
    selectedOrders,
    isLoading,
    fetchOrders,
    handleRefresh,
    handleBatchUpdate,
    handleSelectionChange,
    handleClearSelection,
    handleClearCache,
    handleCancelRoute,
    handleModifyRoute,
    handleModifyOrder,
    handleRouteOrder,
  };
}

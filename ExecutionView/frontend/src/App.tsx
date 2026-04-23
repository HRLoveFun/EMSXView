import { Suspense, lazy, useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { Toolbar } from './sections/Toolbar';
import { MonitorBoard } from './sections/MonitorBoard';
import { LazyOrderBoard } from './sections/LazyOrderBoard';
import { ExecutionBoard } from './sections/ExecutionBoard';
import { SettingsBoard } from './sections/SettingsBoard';
import { ToastContainer } from './sections/ToastContainer';
import { apiService, tokenService } from './services/api';
import type { ModifyOrderRequest, RouteOrderRequest } from './types';
import { loadConditions, saveConditions, matchesAnyCondition, type MonitorConditions } from './lib/monitor-conditions';
import { createCache, CACHE_CONFIGS, getOrFetch, clearAllCaches } from './lib/cache-manager';
import { createRealtimeClient, type RealtimeClient } from './services/realtime';
import { useOrdersStream } from './hooks/use-orders-stream';
import { useRoutesStream } from './hooks/use-routes-stream';
import type { Order, Route, OrderFilters, BatchUpdateRequest, Toast, CancelRouteRequest, ModifyRouteRequest, TraderInfo } from './types';
import './App.css';

// Create cache instances for low-frequency data
const traderInfoCache = createCache<TraderInfo>(CACHE_CONFIGS.TRADER_INFO);
const CostViewModule = lazy(() => import('./modules/costview/CostViewModule'));
const MarketViewModule = lazy(() => import('./modules/marketview/MarketViewModule'));

// ─── Main App ────────────────────────────────────────────────────────────────
function App() {
  // Bloomberg Terminal is already authenticated locally — no login required
  const [isAuthenticated, setIsAuthenticated] = useState(true);

  // State - top-level modules plus execution sub-tabs
  const [activeModule, setActiveModule] = useState<'marketview' | 'execution' | 'costview'>('execution');
  const [activeTab, setActiveTab] = useState<'monitor' | 'execution' | 'settings'>('monitor');
  const [allOrders, setAllOrders] = useState<Order[]>([]);
  const [allRoutes, setAllRoutes] = useState<Route[]>([]);
  const [currentTrader, setCurrentTrader] = useState<string>('');
  const [selectedOrders, setSelectedOrders] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [currentFilters, setCurrentFilters] = useState<OrderFilters>({});
  const [monitorConditions, setMonitorConditions] = useState<MonitorConditions>(loadConditions);
  const [streamConnected, setStreamConnected] = useState(false);

  // ─── Realtime client ─────────────────────────────────────────────────────
  const rtClientRef = useRef<RealtimeClient | null>(null);

  useEffect(() => {
    // Build WS URL from current page location (works behind proxy)
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsBase = import.meta.env.VITE_API_URL
      ? import.meta.env.VITE_API_URL.replace(/^http/, 'ws')
      : `${proto}//${window.location.host}`;
    const client = createRealtimeClient({ url: `${wsBase}/ws/orders` });
    rtClientRef.current = client;

    client.onStatus((s) => setStreamConnected(s === 'connected'));
    client.connect();

    return () => { client.disconnect(); };
  }, []);

  // Stream hooks — merge deltas into local state
  const { orders: streamOrders } = useOrdersStream({
    client: rtClientRef.current,
    initialOrders: allOrders,
    enabled: streamConnected,
  });
  const { routes: streamRoutes } = useRoutesStream({
    client: rtClientRef.current,
    initialRoutes: allRoutes,
    enabled: streamConnected,
  });

  // When stream is connected, use stream-driven state
  const effectiveOrders = streamConnected ? streamOrders : allOrders;
  const effectiveRoutes = streamConnected ? streamRoutes : allRoutes;

  // Persist monitor conditions to localStorage
  useEffect(() => { saveConditions(monitorConditions); }, [monitorConditions]);

  // Monitor alert count (uses configurable conditions)
  const monitorCount = useMemo(
    () => effectiveOrders.filter(o => matchesAnyCondition(o, monitorConditions)).length,
    [effectiveOrders, monitorConditions],
  );

  // Get order count based on active tab (per UI description)
  const getOrderCountForToolbar = () => {
    if (activeModule === 'marketview') {
      return 0;
    }

    if (activeModule === 'costview') {
      return effectiveOrders.length;
    }

    switch (activeTab) {
      case 'monitor':
        return monitorCount;
      case 'execution':
        return filteredOrders.length;
      case 'settings':
        return effectiveOrders.length;
      default:
        return effectiveOrders.length;
    }
  };

  const handleLogout = useCallback(() => {
    tokenService.clearToken();
    setIsAuthenticated(false);
    setAllOrders([]);
  }, []);

  const addToast = useCallback((type: Toast['type'], message: string) => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts(prev => [...prev, { id, type, message }]);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  // Fetch trader info with caching (low frequency)
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
        { forceRefresh }
      );
      setCurrentTrader(traderData.traderName);
    } catch (error) {
      console.error('Fetch trader info error:', error);
      // Don't show toast for trader info errors - non-critical
    }
  }, []);

  // Fetch high-frequency data: orders and routes
  const fetchOrdersAndRoutes = useCallback(async () => {
    try {
      const [ordersRes, routesRes] = await Promise.all([
        apiService.getOrders(),
        apiService.getRoutes(),
      ]);
      
      if (ordersRes.success && ordersRes.data) {
        setAllOrders(ordersRes.data);
      } else if (ordersRes.error?.toLowerCase().includes('authentication') || ordersRes.error?.toLowerCase().includes('401')) {
        handleLogout();
        return;
      }
      
      if (routesRes.success && routesRes.data) {
        setAllRoutes(routesRes.data);
      }
    } catch (error) {
      console.error('Fetch orders/routes error:', error);
      // Silent fail for polling - will retry
    }
  }, [handleLogout]);

  // Fetch ALL orders from backend (no server-side filtering) - manual refresh only
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
        handleLogout();
      } else {
        const msg = response.error || 'Failed to fetch orders';
        // Only show one toast for connection errors (avoid duplicate messages)
        if (!msg.toLowerCase().includes('econnrefused') && !msg.toLowerCase().includes('unavailable')) {
          addToast('error', msg);
        } else {
          addToast('error', 'Cannot reach backend — is it running?');
        }
      }
      if (routesRes.success && routesRes.data) {
        setAllRoutes(routesRes.data);
      }
      // Also refresh trader info on manual refresh
      await fetchTraderInfo(true);
    } catch (error) {
      addToast('error', 'Network error while fetching orders');
      console.error('Fetch orders error:', error);
    } finally {
      setIsLoading(false);
    }
  }, [handleLogout, fetchTraderInfo, addToast]);

  // Client-side filtering — instant, no network calls
  const filteredOrders = useMemo(() => {
    let result = effectiveOrders;
    const f = currentFilters;
    if (f.symbol) {
      const sym = f.symbol.toUpperCase();
      result = result.filter(o => o.symbol.toUpperCase().includes(sym));
    }
    if (f.side) result = result.filter(o => o.side === f.side);
    if (f.statusMulti?.length) result = result.filter(o => f.statusMulti!.includes(o.status));
    else if (f.status) result = result.filter(o => o.status === f.status);
    if (f.orderTypeMulti?.length) result = result.filter(o => f.orderTypeMulti!.includes(o.orderType));
    else if (f.orderType) result = result.filter(o => o.orderType === f.orderType);
    if (f.portfolio) {
      const port = f.portfolio.toUpperCase();
      result = result.filter(o => o.portfolio.toUpperCase().includes(port));
    }
    if (f.traderMulti?.length) result = result.filter(o => f.traderMulti!.includes(o.trader));
    else if (f.trader) {
      const tr = f.trader.toUpperCase();
      result = result.filter(o => o.trader.toUpperCase().includes(tr));
    }
    if (f.exchange) {
      const ex = f.exchange.toUpperCase();
      result = result.filter(o => (o.exchange || '').toUpperCase().includes(ex));
    }
    if (f.currency) {
      const cur = f.currency.toUpperCase();
      result = result.filter(o => o.currency.toUpperCase().includes(cur));
    }
    return result;
  }, [effectiveOrders, currentFilters]);

  // Initial load after login - fetch all data including cached low-frequency data
  useEffect(() => {
    if (isAuthenticated) {
      // Fetch high-frequency data with loading indicator
      fetchOrders();
      // Fetch low-frequency cached data (trader info)
      fetchTraderInfo();
    }
  }, [isAuthenticated, fetchOrders, fetchTraderInfo]);

  // High-frequency polling: orders and routes only — FALLBACK when stream disconnected
  useEffect(() => {
    if (!isAuthenticated) return;
    // Skip polling entirely when stream is providing data
    if (streamConnected) return;
    
    let active = true;
    let consecutiveErrors = 0;
    const MAX_CONSECUTIVE_ERRORS = 5;
    const BASE_INTERVAL = 2000; // 2 seconds base interval
    const BACKOFF_INTERVAL = 5000; // 5 seconds after errors
    
    const getInterval = () => {
      // Back off if too many errors
      if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
        return BACKOFF_INTERVAL;
      }
      // Slower updates when tab is hidden
      if (document.hidden) {
        return BASE_INTERVAL * 2; // 4 seconds when hidden
      }
      return BASE_INTERVAL;
    };
    
    const poll = async () => {
      const startTime = Date.now();
      try {
        await fetchOrdersAndRoutes();
        consecutiveErrors = 0; // Reset error count on success
      } catch {
        // Silently ignore polling errors but track them
        consecutiveErrors++;
        if (consecutiveErrors === MAX_CONSECUTIVE_ERRORS) {
          console.warn('Multiple polling errors detected, backing off...');
        }
      }
      
      // Schedule next poll with adaptive interval
      if (active) {
        const elapsed = Date.now() - startTime;
        const interval = getInterval();
        const delay = Math.max(0, interval - elapsed);
        timer = setTimeout(poll, delay);
      }
    };
    
    let timer = setTimeout(poll, BASE_INTERVAL);
    
    // Handle visibility change to adjust polling
    const handleVisibilityChange = () => {
      // Reset timer with new interval when visibility changes
      clearTimeout(timer);
      if (active) {
        timer = setTimeout(poll, document.hidden ? BASE_INTERVAL * 2 : BASE_INTERVAL);
      }
    };
    
    document.addEventListener('visibilitychange', handleVisibilityChange);
    
    return () => { 
      active = false; 
      clearTimeout(timer); 
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [isAuthenticated, streamConnected, fetchOrdersAndRoutes]);

  // Low-frequency polling: trader info (30s interval, only if cache expired)
  useEffect(() => {
    if (!isAuthenticated) return;
    
    let active = true;
    const CHECK_INTERVAL = 30000; // 30 seconds check interval
    
    const checkAndRefresh = async () => {
      // Only fetch if cache is invalid
      if (!traderInfoCache.isValid()) {
        await fetchTraderInfo();
      }
      
      if (active) {
        timer = setTimeout(checkAndRefresh, CHECK_INTERVAL);
      }
    };
    
    let timer = setTimeout(checkAndRefresh, CHECK_INTERVAL);
    
    return () => { 
      active = false; 
      clearTimeout(timer); 
    };
  }, [isAuthenticated, fetchTraderInfo]);

  // Handle filter changes — purely client-side, instant
  const handleFilterChange = useCallback((filters: OrderFilters) => {
    setCurrentFilters(filters);
  }, []);

  // Handle refresh
  const handleRefresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const [response, routesRes] = await Promise.all([
        apiService.refreshOrders(),
        apiService.getRoutes(),
      ]);
      if (response.success && response.data) {
        setAllOrders(response.data);
        setSelectedOrders(new Set());
        addToast('success', 'Orders refreshed successfully');
      } else {
        addToast('error', response.error || 'Failed to refresh orders');
      }
      if (routesRes.success && routesRes.data) {
        setAllRoutes(routesRes.data);
      }
      // Also refresh cached data
      await fetchTraderInfo(true);
    } catch (error) {
      addToast('error', 'Network error while refreshing orders');
      console.error('Refresh error:', error);
    } finally {
      setIsLoading(false);
    }
  }, [fetchTraderInfo, addToast]);

  // Handle batch update
  const handleBatchUpdate = useCallback(async (request: BatchUpdateRequest) => {
    setIsLoading(true);
    try {
      const response = await apiService.batchUpdate(request);
      if (response.success && response.data) {
        const result = response.data;
        if (result.success) {
          addToast('success', result.message || 'Batch update successful');
        } else {
          addToast('error', result.message || 'Some orders failed to update');
        }
        await fetchOrders();
        setSelectedOrders(new Set());
      } else {
        addToast('error', response.error || 'Batch update failed');
      }
    } catch (error) {
      addToast('error', 'Network error during batch update');
      console.error('Batch update error:', error);
    } finally {
      setIsLoading(false);
    }
  }, [fetchOrders, addToast]);

  const handleSelectionChange = useCallback((selectedIds: Set<string>) => {
    setSelectedOrders(selectedIds);
  }, []);

  const handleClearSelection = useCallback(() => {
    setSelectedOrders(new Set());
  }, []);

  // Handle clear cache - moved after addToast definition
  const handleClearCache = useCallback(() => {
    clearAllCaches();
    // Refetch low-frequency data
    fetchTraderInfo(true);
    addToast('info', 'Cache cleared');
  }, [fetchTraderInfo, addToast]);

  // Handle route cancel
  const handleCancelRoute = useCallback(async (request: CancelRouteRequest) => {
    try {
      const response = await apiService.cancelRoute(request);
      if (response.success) {
        addToast('success', `Route ${request.routeId} cancel request sent`);
      } else {
        addToast('error', response.error || `Failed to cancel route ${request.routeId}`);
      }
    } catch (error) {
      addToast('error', 'Network error while cancelling route');
      console.error('Cancel route error:', error);
    }
  }, [addToast]);

  // Handle route modify
  const handleModifyRoute = useCallback(async (request: ModifyRouteRequest) => {
    try {
      const response = await apiService.modifyRoute(request);
      if (response.success) {
        addToast('success', `Route ${request.routeId} modify request sent`);
      } else {
        addToast('error', response.error || `Failed to modify route ${request.routeId}`);
      }
    } catch (error) {
      addToast('error', 'Network error while modifying route');
      console.error('Modify route error:', error);
    }
  }, [addToast]);

  // Handle order modify
  const handleModifyOrder = useCallback(async (request: ModifyOrderRequest) => {
    try {
      const response = await apiService.modifyOrder(request);
      if (response.success) {
        addToast('success', `Order ${request.orderId} modified successfully`);
        // Refresh orders to show updated data
        await fetchOrders();
      } else {
        addToast('error', response.error || `Failed to modify order ${request.orderId}`);
      }
    } catch (error) {
      addToast('error', 'Network error while modifying order');
      console.error('Modify order error:', error);
    }
  }, [addToast, fetchOrders]);

  // Handle order route
  const handleRouteOrder = useCallback(async (request: RouteOrderRequest) => {
    try {
      const response = await apiService.routeOrder(request);
      if (response.success) {
        addToast('success', `Route created for order ${request.orderId} to broker ${request.broker}`);
        // Refresh orders and routes to show updated data
        await fetchOrders();
      } else {
        addToast('error', response.error || `Failed to route order ${request.orderId}`);
      }
    } catch (error) {
      addToast('error', 'Network error while routing order');
      console.error('Route order error:', error);
    }
  }, [addToast, fetchOrders]);

  // Login screen bypassed — Bloomberg Terminal session is the auth source

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Toolbar
        onRefresh={handleRefresh}
        onClearCache={handleClearCache}
        isLoading={isLoading}
        orderCount={getOrderCountForToolbar()}
        onLogout={handleLogout}
      />

      <main className="flex-1 p-4 space-y-4">
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card p-1.5">
            <button
              className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                activeModule === 'marketview'
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
              onClick={() => setActiveModule('marketview')}
            >
              MarketView
            </button>
            <button
              className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                activeModule === 'execution'
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
              onClick={() => setActiveModule('execution')}
            >
              Execution Workspace
            </button>
            <button
              className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                activeModule === 'costview'
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
              onClick={() => setActiveModule('costview')}
            >
              CostView
            </button>
          </div>

          {activeModule === 'marketview' ? (
            <Suspense
              fallback={
                <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
                  Loading MarketView module...
                </div>
              }
            >
              <MarketViewModule />
            </Suspense>
          ) : activeModule === 'execution' ? (
            <>
              <div className="flex items-center gap-1 border-b border-border">
                <button
                  className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                    activeTab === 'monitor'
                      ? 'border-primary text-primary'
                      : 'border-transparent text-muted-foreground hover:text-foreground'
                  }`}
                  onClick={() => setActiveTab('monitor')}
                >
                  Monitor
                </button>
                <button
                  className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                    activeTab === 'execution'
                      ? 'border-primary text-primary'
                      : 'border-transparent text-muted-foreground hover:text-foreground'
                  }`}
                  onClick={() => setActiveTab('execution')}
                >
                  Execution
                </button>
                <button
                  className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                    activeTab === 'settings'
                      ? 'border-primary text-primary'
                      : 'border-transparent text-muted-foreground hover:text-foreground'
                  }`}
                  onClick={() => setActiveTab('settings')}
                >
                  Settings
                </button>
              </div>

              {activeTab === 'monitor' ? (
                <div className="space-y-4">
                  <MonitorBoard
                    allOrders={effectiveOrders}
                    isLoading={isLoading}
                    conditions={monitorConditions}
                    onConditionsChange={setMonitorConditions}
                  />
                  <LazyOrderBoard
                    allOrders={effectiveOrders}
                    isLoading={isLoading}
                  />
                </div>
              ) : activeTab === 'execution' ? (
                <ExecutionBoard
                  orders={filteredOrders}
                  allOrders={effectiveOrders}
                  routes={effectiveRoutes}
                  selectedOrders={selectedOrders}
                  onSelectionChange={handleSelectionChange}
                  isLoading={isLoading}
                  filters={currentFilters}
                  onFilterChange={handleFilterChange}
                  currentTrader={currentTrader}
                  onBatchUpdate={handleBatchUpdate}
                  onClearSelection={handleClearSelection}
                  onCancelRoute={handleCancelRoute}
                  onModifyRoute={handleModifyRoute}
                  onModifyOrder={handleModifyOrder}
                  onRouteOrder={handleRouteOrder}
                  onRefresh={fetchOrders}
                />
              ) : (
                <SettingsBoard />
              )}
            </>
          ) : (
            <Suspense
              fallback={
                <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
                  Loading CostView module...
                </div>
              }
            >
              <CostViewModule />
            </Suspense>
          )}
        </div>
      </main>

      <ToastContainer toasts={toasts} onRemove={removeToast} />

      <footer className="border-t border-border px-4 py-2 bg-card">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <div>EMSX Trading Tool v1.0.0</div>
          <div className="flex items-center gap-4">
            <span>Connected to EMSX API</span>
            <span className="text-primary">Bloomberg Terminal</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default App;

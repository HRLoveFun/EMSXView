import { Suspense, lazy, useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Toolbar } from './sections/Toolbar';
import { MonitorBoard } from './sections/MonitorBoard';
import { ExecutionBoard } from './sections/ExecutionBoard';
import { ExecutionViewTabs } from './sections/ExecutionViewTabs';
import { SettingsBoard } from './sections/SettingsBoard';
import { ToastContainer } from './sections/ToastContainer';
import { StartupGate } from './components/startup-gate';
import { SubOrderReviewPanel } from './components/sub-order-review-panel';
import { WorkspaceModuleTabs } from './sections/WorkspaceModuleTabs';
import { Spinner } from './components/ui/spinner';
import { ErrorBoundary } from './components/error-boundary';
import { tokenService } from './services/api';
import { createRealtimeClient, type RealtimeClient } from './services/realtime';
import { useAppShellState } from './hooks/use-app-shell-state';
import { useStartupStatus } from './hooks/use-startup-status';
import { useExecutionViewData } from './hooks/use-execution-view-data';
import { useOrdersStream } from './hooks/use-orders-stream';
import { useRoutesStream } from './hooks/use-routes-stream';
import { HandoffContractsProvider } from './hooks/use-handoff-contracts';
import type { Toast } from './types';
import './App.css';

const CostViewModule = lazy(() => import('./modules/costview/CostViewModule'));
const MarketViewModule = lazy(() => import('./modules/marketview/MarketViewModule'));
const DatabaseViewModule = lazy(() => import('./modules/databaseview/DatabaseViewModule'));

/** Skeleton shown while a lazy-loaded module's chunk is downloading.
 *  Replaces the previous static "Loading..." text which gave no progress
 *  feedback and looked indistinguishable from a frozen tab. */
function ModuleLoadingSkeleton({ name }: { name: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground"
    >
      <Spinner className="h-6 w-6" />
      <div>正在加载 {name} 模块…</div>
    </div>
  );
}

// ─── Main App ────────────────────────────────────────────────────────────────
function App() {
  // Bloomberg Terminal is already authenticated locally — no login required
  const [isAuthenticated, setIsAuthenticated] = useState(true);

  // State - top-level modules plus execution sub-tabs
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [streamConnected, setStreamConnected] = useState(false);
  // Track whether the WS has *ever* opened during this session. Lets the UI
  // distinguish "never connected" (cold start) from "previously connected,
  // currently reconnecting" (recovery).
  const [streamEverConnected, setStreamEverConnected] = useState(false);
  // Real timestamp (ms) of the most recent successful data refresh. Used by
  // the toolbar to render an honest "Last Updated" label — replaces the old
  // `new Date()`-on-every-render placeholder which always read "just now".
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [settingsInitialSection, setSettingsInitialSection] = useState<
    'global' | 'monitor-conditions' | 'broker-algo' | 'parameter-frequency' | 'route-plans' | 'data-manager' | 'about'
  >('global');
  const [monitorExceptionCount, setMonitorExceptionCount] = useState(0);

  // ─── Realtime client ─────────────────────────────────────────────────────
  const rtClientRef = useRef<RealtimeClient | null>(null);
  const {
    startupStatus,
    connectionStatus,
    elapsedSeconds: backendBootstrapElapsedSec,
    isChecking: checkingStartup,
    retry: retryBackendBootstrap,
    isReady: isBackendReady,
  } = useStartupStatus({ enabled: isAuthenticated });

  // Toast helper is declared *before* the realtime useEffect so the WS
  // security-downgrade warning below can reach the user instead of going
  // only to the console where non-technical traders never see it.
  const addToast = useCallback((type: Toast['type'], message: string) => {
    // Collision-resistant id; falls back to a non-crypto id on older browsers
    // so dev environments without `crypto.randomUUID` don't break.
    const id = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    // Cap visible toasts to keep the screen readable when many errors arrive
    // back-to-back (e.g. network outage producing one toast per failed poll).
    const MAX_TOASTS = 5;
    setToasts(prev => {
      const next = [...prev, { id, type, message }];
      if (next.length > MAX_TOASTS) {
        // Track drops so the container can render a "+N more" badge —
        // without it, a network outage looks like only 5 errors happened
        // when in reality dozens were silently truncated.
        setDroppedToastCount(c => c + (next.length - MAX_TOASTS));
        return next.slice(next.length - MAX_TOASTS);
      }
      return next;
    });
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const clearDroppedToastCount = useCallback(() => setDroppedToastCount(0), []);

  // True when the toast list has been truncated due to back-pressure — we
  // surface this in ToastContainer so the user sees that older alerts were
  // dropped instead of believing only 5 errors occurred during an outage.
  const [droppedToastCount, setDroppedToastCount] = useState(0);


  useEffect(() => {
    // Build WS URL from current page location (works behind proxy).
    // Security: when serving over HTTPS we must connect via WSS — a configured
    // VITE_API_URL pointing at plain HTTP would otherwise downgrade the
    // realtime channel. We refuse to talk to non-secure origins on a secure
    // page rather than silently leaking auth-bearing frames over plaintext.
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const envUrl = import.meta.env.VITE_API_URL;
    let wsBase: string;
    if (envUrl) {
      const isPageSecure = window.location.protocol === 'https:';
      const envIsInsecure = /^http:\/\//i.test(envUrl) || /^ws:\/\//i.test(envUrl);
      if (isPageSecure && envIsInsecure) {
        console.error('[realtime] Refusing to use insecure VITE_API_URL on https page');
        // Surface the downgrade to the user instead of failing silently —
        // they may have configured the URL on purpose and need to know we
        // overrode it, otherwise data flowing from a different origin would
        // look like a config mismatch with no explanation.
        addToast(
          'error',
          '检测到 VITE_API_URL 为非安全协议（http/ws），已自动切换为同源 WSS。请检查环境配置。',
        );
        wsBase = `${proto}//${window.location.host}`;
      } else {
        wsBase = envUrl.replace(/^http/i, 'ws');
      }
    } else {
      wsBase = `${proto}//${window.location.host}`;
    }
    const client = createRealtimeClient({ url: `${wsBase}/ws/orders` });
    rtClientRef.current = client;

    client.onStatus((s) => {
      const isConnected = s === 'connected';
      setStreamConnected(isConnected);
      if (isConnected) {
        setStreamEverConnected(true);
      }
    });
    client.connect();

    // Visibility-aware reconnect: when the tab returns to foreground and we
    // are not connected, force an immediate reconnect attempt instead of
    // waiting for the exponential backoff timer (which may be far in the
    // future after the browser throttled the tab in the background).
    const handleVisibility = () => {
      if (document.visibilityState !== 'visible') return;
      const c = rtClientRef.current;
      if (c && !c.connected) {
        c.forceReconnect();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      client.disconnect();
    };
  }, []);

  const handleLogout = useCallback(() => {
    tokenService.clearToken();
    setIsAuthenticated(false);
  }, []);

  // Degraded-mode flag: HTTP is up, but EMSX subscriptions warming has
  // exceeded the timeout window. Allow REST polling so users see data even
  // before INIT_PAINT completes.
  const subscriptionsWarmingTimedOut =
    (startupStatus?.backend.httpReady ?? false)
    && !isBackendReady
    && backendBootstrapElapsedSec > 60;

  const {
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
  } = useExecutionViewData({
    isAuthenticated,
    isBackendReady,
    streamConnected,
    allowFallbackFetch: subscriptionsWarmingTimedOut,
    onAuthenticationFailure: handleLogout,
    onToast: addToast,
  });

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

  // When the WS first opens, `streamOrders` is briefly empty before the
  // server replays a snapshot — switching to it eagerly causes the table to
  // flash empty for a few hundred ms. Keep the REST list as a fallback until
  // the stream has actually populated, eliminating that flicker.
  const effectiveOrders = useMemo(() => {
    if (streamConnected && streamOrders.length > 0) return streamOrders;
    return allOrders;
  }, [streamConnected, streamOrders, allOrders]);
  const effectiveRoutes = useMemo(() => {
    if (streamConnected && streamRoutes.length > 0) return streamRoutes;
    return allRoutes;
  }, [streamConnected, streamRoutes, allRoutes]);

  // Refresh `lastUpdatedAt` whenever the underlying data references change —
  // covers both REST refresh and WS deltas through a single signal.
  useEffect(() => {
    if (effectiveOrders.length > 0 || effectiveRoutes.length > 0) {
      setLastUpdatedAt(Date.now());
    }
  }, [effectiveOrders, effectiveRoutes]);

  const {
    activeModule,
    setActiveModule,
    activeTab,
    setActiveTab,
    currentFilters,
    monitorConditions,
    setMonitorConditions,
    filteredOrders,
    toolbarOrderCount,
    shouldShowStartupGate,
    subscriptionsWarming,
    subscriptionsWarmingMode,
    footerConnectionText,
    handleFilterChange,
  } = useAppShellState({
    effectiveOrders,
    effectiveRoutes,
    startupStatus,
    isBackendReady,
    streamConnected,
    streamEverConnected,
    startupElapsedSeconds: backendBootstrapElapsedSec,
  });

  // Handle filter changes — purely client-side, instant
  // Login screen bypassed — Bloomberg Terminal session is the auth source

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <HandoffContractsProvider>
      <Toolbar
        onRefresh={handleRefresh}
        onClearCache={handleClearCache}
        isLoading={isLoading || !isBackendReady}
        orderCount={toolbarOrderCount}
        onLogout={handleLogout}
        startupStatus={startupStatus}
        connectionStatus={connectionStatus}
        checkingStartup={checkingStartup}
        lastUpdatedAt={lastUpdatedAt}
      />

      <main className="flex-1 p-4 space-y-4">
        <ErrorBoundary label="MainContent">
        {shouldShowStartupGate ? (
          <StartupGate
            phase={startupStatus?.phase ?? 'backend_starting'}
            elapsedSeconds={backendBootstrapElapsedSec}
            message={startupStatus?.message}
            httpReady={startupStatus?.backend.httpReady ?? false}
            bloombergStatus={startupStatus?.bloomberg.status ?? 'connecting'}
            subscriptionsReady={startupStatus?.subscriptions.ready ?? false}
            onRetry={retryBackendBootstrap}
          />
        ) : (
          <WorkspaceModuleTabs
            activeModule={activeModule}
            onModuleChange={setActiveModule}
            marketView={
              <Suspense fallback={<ModuleLoadingSkeleton name="MarketView" />}>
                <MarketViewModule />
              </Suspense>
            }
            executionView={
              <div className="space-y-3">
                {subscriptionsWarming ? (
                  <div
                    className={
                      subscriptionsWarmingMode === 'timed-out'
                        ? 'rounded-xl border border-dashed border-amber-500/50 bg-amber-500/5 px-4 py-3 text-xs text-amber-700 dark:text-amber-300'
                        : 'rounded-xl border border-dashed border-primary/40 bg-primary/5 px-4 py-3 text-xs text-muted-foreground'
                    }
                  >
                    {subscriptionsWarmingMode === 'initial' && (
                      <>
                        Establishing EMSX subscriptions — order &amp; route streams will populate momentarily.
                        You can explore CostView, MarketView, and Database tabs while we wait.
                      </>
                    )}
                    {subscriptionsWarmingMode === 'reconnecting' && (
                      <>
                        Realtime stream interrupted — reconnecting and resuming order &amp; route updates.
                      </>
                    )}
                    {subscriptionsWarmingMode === 'timed-out' && (
                      <>
                        EMSX subscription warm-up is taking longer than expected ({backendBootstrapElapsedSec}s).
                        Falling back to REST polling so the table stays populated. Realtime updates will
                        resume automatically once the subscription is healthy.
                      </>
                    )}
                  </div>
                ) : null}
                <ExecutionViewTabs
                activeTab={activeTab}
                onTabChange={setActiveTab}
                monitorExceptionCount={monitorExceptionCount}
                monitorView={
                  <div className="space-y-4">
                    <MonitorBoard
                      allOrders={effectiveOrders}
                      allRoutes={effectiveRoutes}
                      isLoading={isLoading}
                      conditions={monitorConditions}
                      onConditionsChange={setMonitorConditions}
                      onOpenConditionsSettings={() => {
                        setSettingsInitialSection('monitor-conditions');
                        setActiveTab('settings');
                      }}
                      onExceptionCountChange={setMonitorExceptionCount}
                    />
                  </div>
                }
                executionView={
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
                    onRefresh={fetchOrders}
                  />
                }
                routeEngineView={
                  <SubOrderReviewPanel
                    currentTrader={currentTrader}
                    onRefresh={fetchOrders}
                  />
                }
                settingsView={
                  <SettingsBoard
                    monitorConditions={monitorConditions}
                    onMonitorConditionsChange={setMonitorConditions}
                    initialSection={settingsInitialSection}
                  />
                }
              />
              </div>
            }
            costView={
              <Suspense fallback={<ModuleLoadingSkeleton name="CostView" />}>
                <CostViewModule onNavigateToDatabase={() => setActiveModule('database')} />
              </Suspense>
            }
            databaseView={
              <Suspense fallback={<ModuleLoadingSkeleton name="Database" />}>
                <DatabaseViewModule />
              </Suspense>
            }
          />
        )}
        </ErrorBoundary>
      </main>

      <ToastContainer
        toasts={toasts}
        onRemove={removeToast}
        droppedCount={droppedToastCount}
        onClearDropped={clearDroppedToastCount}
      />

      <footer className="border-t border-border px-4 py-2 bg-card">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <div>EMSX Trading Tool v1.0.0</div>
          {/* The connection phase is already prominent in the toolbar; the
              footer keeps a single non-redundant attribution so users still
              know the data source without seeing the same status twice. */}
          <div>来源：Bloomberg Terminal · {footerConnectionText}</div>
        </div>
      </footer>
      </HandoffContractsProvider>
    </div>
  );
}

export default App;

import { Suspense, lazy, useState, useCallback, useEffect, useRef } from 'react';
import { Toolbar } from './sections/Toolbar';
import { MonitorBoard } from './sections/MonitorBoard';
import { ExecutionBoard } from './sections/ExecutionBoard';
import { ExecutionViewTabs } from './sections/ExecutionViewTabs';
import { SettingsBoard } from './sections/SettingsBoard';
import { ToastContainer } from './sections/ToastContainer';
import { StartupGate } from './components/startup-gate';
import { WorkspaceModuleTabs } from './sections/WorkspaceModuleTabs';
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
  const [settingsInitialSection, setSettingsInitialSection] = useState<
    'global' | 'monitor-conditions' | 'broker-algo' | 'parameter-frequency' | 'data-manager' | 'about'
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

  useEffect(() => {
    // Build WS URL from current page location (works behind proxy)
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsBase = import.meta.env.VITE_API_URL
      ? import.meta.env.VITE_API_URL.replace(/^http/, 'ws')
      : `${proto}//${window.location.host}`;
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

  const addToast = useCallback((type: Toast['type'], message: string) => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts(prev => [...prev, { id, type, message }]);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
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
    handleRouteOrder,
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

  // When stream is connected, use stream-driven state
  const effectiveOrders = streamConnected ? streamOrders : allOrders;
  const effectiveRoutes = streamConnected ? streamRoutes : allRoutes;

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
      />

      <main className="flex-1 p-4 space-y-4">
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
              <Suspense
                fallback={
                  <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
                    Loading MarketView module...
                  </div>
                }
              >
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
                    onRouteOrder={handleRouteOrder}
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
              <Suspense
                fallback={
                  <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
                    Loading CostView module...
                  </div>
                }
              >
                <CostViewModule onNavigateToDatabase={() => setActiveModule('database')} />
              </Suspense>
            }
            databaseView={
              <Suspense
                fallback={
                  <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
                    Loading Database module...
                  </div>
                }
              >
                <DatabaseViewModule />
              </Suspense>
            }
          />
        )}
      </main>

      <ToastContainer toasts={toasts} onRemove={removeToast} />

      <footer className="border-t border-border px-4 py-2 bg-card">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <div>EMSX Trading Tool v1.0.0</div>
          <div className="flex items-center gap-4">
            <span>{footerConnectionText}</span>
            <span className="text-primary">Bloomberg Terminal</span>
          </div>
        </div>
      </footer>
      </HandoffContractsProvider>
    </div>
  );
}

export default App;

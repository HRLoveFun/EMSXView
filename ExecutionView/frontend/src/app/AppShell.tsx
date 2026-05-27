// AppShell — layout and state orchestration
// All shell-level state lives here. No hidden contexts.
import { Suspense, lazy, useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Toolbar } from '@app/Toolbar';
import { ToastContainer } from '@app/ToastContainer';
import { StartupGate } from '@/components/startup-gate';
import { WorkspaceModuleTabs } from '@app/WorkspaceModuleTabs';
import { Spinner } from '@/components/ui/spinner';
import { ErrorBoundary } from '@/components/error-boundary';
import { useModuleNavigation } from '@app/hooks/use-module-navigation';
import { useStartupStatus } from '@app/hooks/use-startup-status';
import { createRealtimeClient, type RealtimeClient } from '@execution/services/realtime';
import { tokenService } from '@execution/services/execution-api';
import { HandoffContractsProvider } from '@shared/hooks/use-handoff-contracts';
import type { Toast } from '@shared/types';

const ExecutionModule = lazy(() => import('@execution/ExecutionModule'));
const CostViewModule = lazy(() => import('@/modules/costview/CostViewModule'));
const MarketViewModule = lazy(() => import('@/modules/marketview/MarketViewModule'));
const DatabaseViewModule = lazy(() => import('@/modules/databaseview/DatabaseViewModule'));

/** Skeleton shown while a lazy-loaded module's chunk is downloading. */
function ModuleLoadingSkeleton({ name }: { name: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground"
    >
      <Spinner className="h-6 w-6" />
      <div>Loading {name} module…</div>
    </div>
  );
}

const MAX_TOASTS = 5;

export function AppShell() {
  // ─── Auth state ────────────────────────────────────────────────────────
  // Bloomberg Terminal is already authenticated locally — no login required.
  const [isAuthenticated, setIsAuthenticated] = useState(true);
  const handleLogout = useCallback(() => {
    tokenService.clearToken();
    setIsAuthenticated(false);
  }, []);

  // ─── Toast state ───────────────────────────────────────────────────────
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [droppedToastCount, setDroppedToastCount] = useState(0);

  const addToast = useCallback((type: Toast['type'], message: string) => {
    const id =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    setToasts(prev => {
      const next = [...prev, { id, type, message }];
      if (next.length > MAX_TOASTS) {
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

  // ─── Realtime WS connection ────────────────────────────────────────────
  const [streamConnected, setStreamConnected] = useState(false);
  const [streamEverConnected, setStreamEverConnected] = useState(false);
  const rtClientRef = useRef<RealtimeClient | null>(null);

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const envUrl = import.meta.env.VITE_API_URL;
    let wsBase: string;
    if (envUrl) {
      const isPageSecure = window.location.protocol === 'https:';
      const envIsInsecure = /^http:\/\//i.test(envUrl) || /^ws:\/\//i.test(envUrl);
      if (isPageSecure && envIsInsecure) {
        console.error('[realtime] Refusing to use insecure VITE_API_URL on https page');
        addToast(
          'error',
          'Insecure VITE_API_URL protocol detected (http/ws). Automatically switched to same-origin WSS. Please check your environment configuration.',
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
      rtClientRef.current = null;
    };
  }, [addToast]);

  // ─── Execution module info (provided by ExecutionModule via callback) ───
  const [executionInfo, setExecutionInfo] = useState({
    orderCount: 0,
    routeCount: 0,
    isLoading: true,
    lastUpdatedAt: null as number | null,
    refresh: () => {},
    clearCache: () => {},
  });

  // ─── Startup status ───────────────────────────────────────────────────
  const {
    startupStatus,
    connectionStatus,
    elapsedSeconds: backendBootstrapElapsedSec,
    isChecking: checkingStartup,
    retry: retryBackendBootstrap,
    isReady: isBackendReady,
  } = useStartupStatus({ enabled: isAuthenticated });

  // ─── Module navigation ─────────────────────────────────────────────────
  const {
    activeModule,
    setActiveModule,
    shouldShowStartupGate,
    subscriptionsWarming,
    subscriptionsWarmingMode,
    footerConnectionText,
  } = useModuleNavigation({
    startupStatus,
    isBackendReady,
    streamConnected,
    streamEverConnected,
    startupElapsedSeconds: backendBootstrapElapsedSec,
    orderCount: executionInfo.orderCount,
    routeCount: executionInfo.routeCount,
  });

  const toolbarOrderCount = useMemo(() => {
    if (activeModule !== 'execution') return 0;
    return executionInfo.orderCount;
  }, [activeModule, executionInfo.orderCount]);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <HandoffContractsProvider>
      <Toolbar
        onRefresh={executionInfo.refresh}
        onClearCache={executionInfo.clearCache}
        isLoading={!isBackendReady || (activeModule === 'execution' && executionInfo.isLoading)}
        orderCount={toolbarOrderCount}
        onLogout={handleLogout}
        startupStatus={startupStatus}
        connectionStatus={connectionStatus}
        checkingStartup={checkingStartup}
        lastUpdatedAt={executionInfo.lastUpdatedAt}
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
              <Suspense fallback={<ModuleLoadingSkeleton name="Execution" />}>
                <ExecutionModule
                  onNavigateToDatabase={() => setActiveModule('database')}
                  onInfoUpdate={setExecutionInfo}
                  onLogout={handleLogout}
                  addToast={addToast}
                  realtimeClient={rtClientRef.current}
                  streamConnected={streamConnected}
                  streamEverConnected={streamEverConnected}
                  subscriptionsWarming={subscriptionsWarming}
                  subscriptionsWarmingMode={subscriptionsWarmingMode}
                />
              </Suspense>
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
          <div>EMSXView Trading Tool v1.0.0</div>
          <div>Source: Bloomberg Terminal · {footerConnectionText}</div>
        </div>
      </footer>
      </HandoffContractsProvider>
    </div>
  );
}

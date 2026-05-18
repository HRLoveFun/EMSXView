// AppShell — layout and state orchestration
// Consumes provider contexts (Auth, Realtime, Toast) and renders the full UI
import { Suspense, lazy, useState, useCallback, useMemo } from 'react';
import { Toolbar } from '@/sections/Toolbar';
import { ToastContainer } from '@/sections/ToastContainer';
import { StartupGate } from '@/components/startup-gate';
import { WorkspaceModuleTabs } from '@/sections/WorkspaceModuleTabs';
import { Spinner } from '@/components/ui/spinner';
import { ErrorBoundary } from '@/components/error-boundary';
import { useModuleNavigation, type AppModule } from '@app/hooks/use-module-navigation';
import { useStartupStatus } from '@app/hooks/use-startup-status';
import { useAuth } from './providers/AuthProvider';
import { useRealtime } from './providers/RealtimeProvider';
import { useToast } from './providers/ToastProvider';
import type { ExecutionModuleInfo } from '@execution/ExecutionModule';

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

export function AppShell() {
  const { isAuthenticated, handleLogout } = useAuth();
  const { streamConnected, streamEverConnected } = useRealtime();
  const { toasts, addToast, removeToast, droppedToastCount, clearDroppedToastCount } = useToast();

  // Execution module info (provided by ExecutionModule via callback)
  const [executionInfo, setExecutionInfo] = useState<ExecutionModuleInfo>({
    orderCount: 0,
    routeCount: 0,
    isLoading: true,
    lastUpdatedAt: null,
    refresh: () => {},
    clearCache: () => {},
  });
  const handleExecutionInfoUpdate = useCallback((info: ExecutionModuleInfo) => {
    setExecutionInfo(info);
  }, []);

  // Startup status
  const {
    startupStatus,
    connectionStatus,
    elapsedSeconds: backendBootstrapElapsedSec,
    isChecking: checkingStartup,
    retry: retryBackendBootstrap,
    isReady: isBackendReady,
  } = useStartupStatus({ enabled: isAuthenticated });

  // Module navigation (shell-level only, execution state is inside ExecutionModule)
  const {
    activeModule,
    setActiveModule,
    shouldShowStartupGate,
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

  // Toolbar order count depends on active module
  const toolbarOrderCount = useMemo(() => {
    if (activeModule !== 'execution') return 0;
    return executionInfo.orderCount;
  }, [activeModule, executionInfo.orderCount]);

  return (
    <div className="min-h-screen bg-background flex flex-col">
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
                  onInfoUpdate={handleExecutionInfoUpdate}
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
          <div>EMSX Trading Tool v1.0.0</div>
          <div>Source: Bloomberg Terminal · {footerConnectionText}</div>
        </div>
      </footer>
    </div>
  );
}
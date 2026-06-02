// ExecutionModule — self-contained entry point for the Execution domain
// Receives shell services via useShellContext() and contributes toolbar info via onContribute.
import { useState, useEffect, useMemo } from 'react';
import { MonitorBoard } from '@execution/views/MonitorBoard';
import { ExecutionBoard } from '@execution/views/ExecutionBoard';
import { ExecutionViewTabs } from '@execution/views/ExecutionViewTabs';
import { SettingsBoard } from '@execution/views/settings/SettingsBoard';
import { SubOrderReviewPanel } from '@execution/components/sub-order-review-panel';
import { useExecutionViewData } from '@execution/hooks/use-execution-view-data';
import { useOrdersStream } from '@execution/hooks/use-orders-stream';
import { useRoutesStream } from '@execution/hooks/use-routes-stream';
import { useExecutionState } from '@execution/hooks/use-execution-state';
import { useStartupStatus } from '@app/hooks/use-startup-status';
import { useShellContext } from '@shared/lib/shell-context';
import type { ModuleShellProps } from '@shared/lib/module-registry';
import type { RealtimeClient } from '@shared/services/realtime';

/** Info that ExecutionModule exposes to the shell for toolbar integration. */
export interface ExecutionModuleInfo {
  orderCount: number;
  routeCount: number;
  isLoading: boolean;
  lastUpdatedAt: number | null;
  refresh: () => void;
  clearCache: () => void;
}

export default function ExecutionModule({ onContribute }: ModuleShellProps) {
  const shell = useShellContext();

  // Bloomberg Terminal is already authenticated locally
  const isAuthenticated = true;

  // Local UI state
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [settingsInitialSection, setSettingsInitialSection] = useState<
    'global' | 'monitor-conditions' | 'broker-algo' | 'parameter-frequency' | 'route-plans' | 'data-manager' | 'about'
  >('global');
  const [monitorExceptionCount, setMonitorExceptionCount] = useState(0);

  // Startup status
  const {
    elapsedSeconds: backendBootstrapElapsedSec,
    isReady: isBackendReady,
  } = useStartupStatus({ enabled: isAuthenticated });

  // Execution data
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
    streamConnected: shell.streamConnected,
    allowFallbackFetch: shell.subscriptionsWarmingMode === 'timed-out',
    onAuthenticationFailure: shell.logout,
    onToast: shell.addToast,
  });

  // Stream hooks
  const { orders: streamOrders } = useOrdersStream({
    client: shell.realtimeClient as RealtimeClient | null,
    initialOrders: allOrders,
    enabled: shell.streamConnected,
  });
  const { routes: streamRoutes } = useRoutesStream({
    client: shell.realtimeClient as RealtimeClient | null,
    initialRoutes: allRoutes,
    enabled: shell.streamConnected,
  });

  const effectiveOrders = useMemo(() => {
    if (shell.streamConnected && streamOrders.length > 0) return streamOrders;
    return allOrders;
  }, [shell.streamConnected, streamOrders, allOrders]);
  const effectiveRoutes = useMemo(() => {
    if (shell.streamConnected && streamRoutes.length > 0) return streamRoutes;
    return allRoutes;
  }, [shell.streamConnected, streamRoutes, allRoutes]);

  useEffect(() => {
    if (effectiveOrders.length > 0 || effectiveRoutes.length > 0) {
      setLastUpdatedAt(Date.now());
    }
  }, [effectiveOrders, effectiveRoutes]);

  // Execution domain state
  const {
    activeTab,
    setActiveTab,
    currentFilters,
    monitorConditions,
    setMonitorConditions,
    filteredOrders,
    monitorCount,
    handleFilterChange,
  } = useExecutionState({ effectiveOrders });

  // Toolbar order count
  const toolbarOrderCount = useMemo(() => {
    switch (activeTab) {
      case 'monitor': return monitorCount;
      case 'trade': return filteredOrders.length;
      case 'settings': return effectiveOrders.length;
      default: return effectiveOrders.length;
    }
  }, [activeTab, effectiveOrders.length, filteredOrders.length, monitorCount]);

  // Contribute info to shell for toolbar — generic contribution pattern
  useEffect(() => {
    onContribute?.({
      counts: {
        orders: toolbarOrderCount,
        routes: effectiveRoutes.length,
      },
      isLoading,
      lastUpdatedAt,
      refresh: handleRefresh,
      clearCache: handleClearCache,
    });
  }, [toolbarOrderCount, effectiveRoutes.length, isLoading, lastUpdatedAt, handleRefresh, handleClearCache, onContribute]);

  return (
    <div className="space-y-3">
      {shell.subscriptionsWarming ? (
        <div
          className={
            shell.subscriptionsWarmingMode === 'timed-out'
              ? 'rounded-xl border border-dashed border-amber-500/50 bg-amber-500/5 px-4 py-3 text-xs text-amber-700 dark:text-amber-300'
              : 'rounded-xl border border-dashed border-primary/40 bg-primary/5 px-4 py-3 text-xs text-muted-foreground'
          }
        >
          {shell.subscriptionsWarmingMode === 'initial' && (
            <>
              Establishing EMSX subscriptions — order &amp; route streams will populate momentarily.
              You can explore CostView, MarketView, and Database tabs while we wait.
            </>
          )}
          {shell.subscriptionsWarmingMode === 'reconnecting' && (
            <>
              Realtime stream interrupted — reconnecting and resuming order &amp; route updates.
            </>
          )}
          {shell.subscriptionsWarmingMode === 'timed-out' && (
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
  );
}

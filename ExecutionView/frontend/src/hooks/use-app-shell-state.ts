import { useCallback, useEffect, useMemo, useState } from 'react';
import { loadConditions, saveConditions, matchesAnyCondition, type MonitorConditions } from '../lib/monitor-conditions';
import type { Order, OrderFilters, Route, StartupStatusSnapshot } from '../types';

export type AppModule = 'marketview' | 'execution' | 'costview' | 'database';
export type ExecutionViewTab = 'monitor' | 'trade' | 'settings';

interface UseAppShellStateParams {
  effectiveOrders: Order[];
  effectiveRoutes: Route[];
  startupStatus: StartupStatusSnapshot | null;
  isBackendReady: boolean;
  streamConnected: boolean;
  /** True if WS has reached OPEN at least once during this session. */
  streamEverConnected: boolean;
  /** Seconds elapsed since the current startup probe began. */
  startupElapsedSeconds: number;
}

/** UI mode for the subscriptions-warming notice. */
export type SubscriptionsWarmingMode = 'initial' | 'reconnecting' | 'timed-out';

/** After this many seconds with no stream + no data, surface a degraded-mode notice. */
const SUBSCRIPTIONS_WARMING_TIMEOUT_SEC = 60;

export function useAppShellState({
  effectiveOrders,
  effectiveRoutes,
  startupStatus,
  isBackendReady,
  streamConnected,
  streamEverConnected,
  startupElapsedSeconds,
}: UseAppShellStateParams) {
  const [activeModule, setActiveModule] = useState<AppModule>('execution');
  const [activeTab, setActiveTab] = useState<ExecutionViewTab>('monitor');
  const [currentFilters, setCurrentFilters] = useState<OrderFilters>({});
  const [monitorConditions, setMonitorConditions] = useState<MonitorConditions>(loadConditions);

  useEffect(() => {
    saveConditions(monitorConditions);
  }, [monitorConditions]);

  const filteredOrders = useMemo(() => {
    let result = effectiveOrders;
    const filters = currentFilters;

    if (filters.symbol) {
      const symbol = filters.symbol.toUpperCase();
      result = result.filter((order) => order.symbol.toUpperCase().includes(symbol));
    }
    if (filters.side) {
      result = result.filter((order) => order.side === filters.side);
    }
    if (filters.statusMulti?.length) {
      result = result.filter((order) => filters.statusMulti!.includes(order.status));
    }
    else if (filters.status) {
      result = result.filter((order) => order.status === filters.status);
    }
    if (filters.orderTypeMulti?.length) {
      result = result.filter((order) => filters.orderTypeMulti!.includes(order.orderType));
    }
    else if (filters.orderType) {
      result = result.filter((order) => order.orderType === filters.orderType);
    }
    if (filters.portfolio) {
      const portfolio = filters.portfolio.toUpperCase();
      result = result.filter((order) => order.portfolio.toUpperCase().includes(portfolio));
    }
    if (filters.traderMulti?.length) {
      result = result.filter((order) => filters.traderMulti!.includes(order.trader));
    }
    else if (filters.trader) {
      const trader = filters.trader.toUpperCase();
      result = result.filter((order) => order.trader.toUpperCase().includes(trader));
    }
    if (filters.exchange) {
      const exchange = filters.exchange.toUpperCase();
      result = result.filter((order) => (order.exchange || '').toUpperCase().includes(exchange));
    }
    if (filters.currency) {
      const currency = filters.currency.toUpperCase();
      result = result.filter((order) => order.currency.toUpperCase().includes(currency));
    }

    return result;
  }, [effectiveOrders, currentFilters]);

  const monitorCount = useMemo(
    () => effectiveOrders.filter((order) => matchesAnyCondition(order, monitorConditions)).length,
    [effectiveOrders, monitorConditions],
  );

  const toolbarOrderCount = useMemo(() => {
    if (activeModule === 'marketview') {
      return 0;
    }

    if (activeModule === 'costview' || activeModule === 'database') {
      return effectiveOrders.length;
    }

    switch (activeTab) {
      case 'monitor':
        return monitorCount;
      case 'trade':
        return filteredOrders.length;
      case 'settings':
        return effectiveOrders.length;
      default:
        return effectiveOrders.length;
    }
  }, [activeModule, activeTab, effectiveOrders.length, filteredOrders.length, monitorCount]);

  // Only block the entire shell when the backend HTTP itself is not yet
  // reachable (or reports an error). Once HTTP is up, we let the user into
  // the tabs immediately — Execution surfaces render skeletons while
  // EMSX subscriptions finish INIT_PAINT, and CostView / MarketView /
  // DatabaseView (all independent of the order stream) become usable right
  // away. This is a major cold-start perceived-latency win.
  const httpReady = startupStatus?.backend.httpReady ?? false;
  const startupFailed = startupStatus?.phase === 'error';
  const shouldShowStartupGate =
    (!httpReady || startupFailed)
    && !streamConnected
    && effectiveOrders.length === 0
    && effectiveRoutes.length === 0;

  const subscriptionsWarming =
    httpReady
    && !isBackendReady
    && !streamConnected
    && effectiveOrders.length === 0
    && effectiveRoutes.length === 0;

  const subscriptionsWarmingTimedOut =
    subscriptionsWarming && startupElapsedSeconds > SUBSCRIPTIONS_WARMING_TIMEOUT_SEC;

  const subscriptionsWarmingMode: SubscriptionsWarmingMode = subscriptionsWarmingTimedOut
    ? 'timed-out'
    : streamEverConnected
      ? 'reconnecting'
      : 'initial';

  const footerConnectionText = useMemo(() => {
    if (startupStatus?.phase === 'ready') {
      return 'Connected to EMSX API';
    }
    if (startupStatus?.phase === 'subscriptions_warming') {
      return 'Warming EMSX subscriptions';
    }
    if (startupStatus?.phase === 'bloomberg_connecting') {
      return 'Waiting for Bloomberg';
    }
    if (startupStatus?.phase === 'error') {
      return startupStatus.message || 'Backend unavailable';
    }
    return 'Backend starting';
  }, [startupStatus]);

  const handleFilterChange = useCallback((filters: OrderFilters) => {
    setCurrentFilters(filters);
  }, []);

  return {
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
    subscriptionsWarmingTimedOut,
    subscriptionsWarmingMode,
    footerConnectionText,
    handleFilterChange,
  };
}
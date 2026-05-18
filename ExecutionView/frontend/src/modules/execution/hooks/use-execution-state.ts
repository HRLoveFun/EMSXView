// Execution Domain State — tab, filters, monitor conditions
import { useCallback, useEffect, useMemo, useState } from 'react';
import { loadConditions, saveConditions, matchesAnyCondition, type MonitorConditions } from '@execution/lib/monitor-conditions';
import type { Order, OrderFilters } from '@execution/types';

export type ExecutionViewTab = 'monitor' | 'trade' | 'route-engine' | 'settings';

interface UseExecutionStateParams {
  effectiveOrders: Order[];
}

export function useExecutionState({ effectiveOrders }: UseExecutionStateParams) {
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

  const handleFilterChange = useCallback((filters: OrderFilters) => {
    setCurrentFilters(filters);
  }, []);

  return {
    activeTab,
    setActiveTab,
    currentFilters,
    monitorConditions,
    setMonitorConditions,
    filteredOrders,
    monitorCount,
    handleFilterChange,
  };
}
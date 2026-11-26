/** RouteTable pure helpers and constants (A14/229). */

import type { RouteGroupByValue } from '@execution/lib';
import type { Route } from '@execution/types';

export type SortField = keyof Route | null;
export type SortDirection = 'asc' | 'desc';
export type GroupLevel = 'primary' | 'secondary';

export interface SortConfig {
  field: SortField;
  direction: SortDirection;
}

export interface GroupConfig {
  primary: RouteGroupByValue;
  secondary: RouteGroupByValue;
}

export const TOTAL_COLS = 26;

// 路由「已收敛」状态集合：乐观替换标记在此类状态下视为可清除
export const STABLE_ROUTE_STATUSES = new Set([
  'WORKING', 'PARTFILL', 'PARTFILLED', 'FILLED', 'DONE', 'CANCEL', 'REJECTED', 'CXLREJ', 'CXLRPRJ',
]);

export interface RouteFilters {
  status: string[];
  statusMode: 'include' | 'exclude';
  broker: string[];
  brokerMode: 'include' | 'exclude';
  trader: string[];
  traderMode: 'include' | 'exclude';
  ticker: string;
}

export function filterRoutes(routes: Route[], filters: RouteFilters): Route[] {
  let result = routes;
  if (filters.status.length > 0) {
    result = filters.statusMode === 'include'
      ? result.filter((r) => filters.status.includes(r.status))
      : result.filter((r) => !filters.status.includes(r.status));
  }
  if (filters.broker.length > 0) {
    result = filters.brokerMode === 'include'
      ? result.filter((r) => filters.broker.includes(r.broker))
      : result.filter((r) => !filters.broker.includes(r.broker));
  }
  if (filters.trader.length > 0) {
    result = filters.traderMode === 'include'
      ? result.filter((r) => filters.trader.includes(r.trader))
      : result.filter((r) => !filters.trader.includes(r.trader));
  }
  if (filters.ticker) {
    const needle = filters.ticker.toUpperCase();
    result = result.filter((r) => (r.ticker || '').toUpperCase().includes(needle));
  }
  return result;
}

export function sortRoutes(routes: Route[], config: SortConfig): Route[] {
  if (!config.field) return routes;
  return [...routes].sort((a, b) => {
    const field = config.field as keyof Route;
    const aValue = a[field];
    const bValue = b[field];
    const aNull = aValue === undefined || aValue === null || aValue === '';
    const bNull = bValue === undefined || bValue === null || bValue === '';
    if (aNull && bNull) return 0;
    if (aNull) return 1;
    if (bNull) return -1;
    if (typeof aValue === 'string' && typeof bValue === 'string') {
      return config.direction === 'asc'
        ? aValue.localeCompare(bValue)
        : bValue.localeCompare(aValue);
    }
    if (typeof aValue === 'number' && typeof bValue === 'number') {
      return config.direction === 'asc' ? aValue - bValue : bValue - aValue;
    }
    return 0;
  });
}

export interface RouteSubGroup {
  key: string;
  routes: Route[];
}

export interface RouteGroup {
  key: string;
  routes: Route[];
  subGroups: RouteSubGroup[] | null;
}

export function groupRoutes(routes: Route[], config: GroupConfig): RouteGroup[] {
  const { primary, secondary } = config;
  if (primary === 'none' && secondary === 'none') {
    return [{ key: '_all', routes, subGroups: null }];
  }

  const groups: Record<string, { routes: Route[]; subGroups: Record<string, Route[]> | null }> = {};
  for (const route of routes) {
    const primaryKey = primary !== 'none'
      ? String(route[primary as keyof Route] || '(empty)')
      : '_all';
    if (!groups[primaryKey]) {
      groups[primaryKey] = { routes: [], subGroups: secondary !== 'none' ? {} : null };
    }
    if (secondary !== 'none' && primary !== 'none') {
      const secondaryKey = String(route[secondary as keyof Route] || '(empty)');
      if (!groups[primaryKey].subGroups![secondaryKey]) {
        groups[primaryKey].subGroups![secondaryKey] = [];
      }
      groups[primaryKey].subGroups![secondaryKey].push(route);
    } else {
      groups[primaryKey].routes.push(route);
    }
  }

  return Object.entries(groups)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, data]) => ({
      key,
      routes: data.routes,
      subGroups: data.subGroups
        ? Object.entries(data.subGroups)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([subKey, subRoutes]) => ({ key: subKey, routes: subRoutes }))
        : null,
    }));
}

export const getPercentFilled = (route: Route): string => {
  if (route.amount <= 0) return '';
  return `${((route.filled / route.amount) * 100).toFixed(0)}%`;
};

export const getRouteStrategyDetail = (route: Route): string => {
  if (!route.strategyType) return '';
  const parts: string[] = [];
  if (route.strategyPartRate1 != null) parts.push(`Rate: ${route.strategyPartRate1}%`);
  if (route.strategyPartRate2 != null) parts.push(`Rate2: ${route.strategyPartRate2}%`);
  if (route.strategyStyle) parts.push(`Style: ${route.strategyStyle}`);
  if (route.strategyStartTime) parts.push(`Start: ${route.strategyStartTime}`);
  if (route.strategyEndTime) parts.push(`End: ${route.strategyEndTime}`);
  return parts.join(' | ');
};

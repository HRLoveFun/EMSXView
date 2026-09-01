/**
 * Unified health-level palette shared across Monitor / Trade (Order & Route tables).
 *
 * Level ranking (highest first): critical > warning > info > healthy.
 * Each level exposes tailwind class fragments so callers can render a 4px left
 * strip (`stripClass`), row tint (`rowClass`), or badge (`badgeClass`).
 */

import type { Order, Route, OrderStatus } from '@execution/types'
import type { MonitorConditions } from './monitor-conditions';
import { matchesAnyCondition } from './monitor-conditions';
import { PENDING_ROUTE_STATUSES, remainingOf } from './route-capacity';

export type HealthLevel = 'critical' | 'warning' | 'info' | 'healthy';

export const HEALTH_LEVELS: HealthLevel[] = ['critical', 'warning', 'info', 'healthy'];

export const HEALTH_RANK: Record<HealthLevel, number> = {
  critical: 3, warning: 2, info: 1, healthy: 0,
};

export const HEALTH_PALETTE: Record<HealthLevel, {
  label: string;
  stripClass: string;   // 4px vertical strip background
  rowClass: string;     // optional row tint for pinned sections
  badgeClass: string;   // inline badge colors
  dotClass: string;     // small round indicator
}> = {
  critical: {
    label: 'Critical',
    stripClass: 'bg-red-500',
    rowClass: 'bg-red-500/5 border-l-2 border-l-red-500',
    badgeClass: 'bg-red-500/10 text-red-700 dark:text-red-300 border-red-500/40',
    dotClass: 'bg-red-500',
  },
  warning: {
    label: 'Warning',
    stripClass: 'bg-amber-500',
    rowClass: 'bg-amber-500/5 border-l-2 border-l-amber-500',
    badgeClass: 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/40',
    dotClass: 'bg-amber-500',
  },
  info: {
    label: 'Info',
    stripClass: 'bg-sky-500',
    rowClass: 'bg-sky-500/5 border-l-2 border-l-sky-500',
    badgeClass: 'bg-sky-500/10 text-sky-700 dark:text-sky-300 border-sky-500/40',
    dotClass: 'bg-sky-500',
  },
  healthy: {
    label: 'Healthy',
    stripClass: 'bg-transparent',
    rowClass: '',
    badgeClass: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/40',
    dotClass: 'bg-emerald-500',
  },
};

// ─── Lazy-order rule ─────────────────────────────────────────────────────────

/**
 * Set of order statuses considered "not-lazy by status" (rule 1 exception set).
 * An order whose status is NOT in this set automatically qualifies as lazy.
 */
export const LAZY_EXEMPT_STATUSES = new Set<OrderStatus>([
  'WORKING', 'QUEUED', 'COMPLETED', 'FILLED', 'SUSPENDED',
]);

/**
 * 批量计算各父单的可路由额度（idle），返回 orderId → idle 映射。
 *
 * idle = 父单剩余量（remainingQuantity）− 在途路由量（Σ pending route.working）。
 * 供 MonitorBoard 等大列表场景复用，避免 O(N*M) 且消除重复实现。
 */
export function computeIdleShareByOrder(
  orders: Order[],
  routes: Route[],
): Map<string, number> {
  // 先按父单聚合在途量：只算 PENDING 状态，且取 working 而非 amount
  // （amount = working + 已成交，父单 remaining 已扣过成交量，按 amount 扣会二次扣减）。
  const pendingByOrderId = new Map<string, number>();
  for (const r of routes) {
    if (!PENDING_ROUTE_STATUSES.has(r.status)) continue;
    const w = Number(r.working ?? 0);
    if (!Number.isFinite(w) || w <= 0) continue;
    const key = String(r.sequence);
    pendingByOrderId.set(key, (pendingByOrderId.get(key) ?? 0) + w);
  }

  const result = new Map<string, number>();
  for (const o of orders) {
    const pending = pendingByOrderId.get(o.id) ?? 0;
    result.set(o.id, Math.max(0, remainingOf(o) - pending));
  }
  return result;
}

/**
 * Compute idle share for an order given its routes. "Idle share" = parent
 * quantity that is neither filled on the parent nor pending on any route
 * — i.e. `remainingQuantity − Σ pending route.working`.
 * Safe fallback to 0 when route data is not yet available.
 */
export function computeIdleShare(order: Order, routes: Route[] | undefined): number {
  if (!routes || routes.length === 0) {
    // Without routing context we cannot compute idle share reliably — return 0
    // so rule-2 does not falsely flag every order.
    return 0;
  }
  return computeIdleShareByOrder([order], routes).get(order.id) ?? 0;
}

export interface LazyContext {
  idleShareByOrderId?: Map<string, number>;
}

/**
 * Lazy order rule (either clause triggers):
 *  1. status ∉ {WORKING, QUEUED, COMPLETED, FILLED, SUSPENDED}
 *  2. status ≠ SUSPENDED AND idleShare > 0
 */
export function isLazyOrder(order: Order, ctx?: LazyContext): boolean {
  if (!LAZY_EXEMPT_STATUSES.has(order.status)) return true;
  if (order.status === 'SUSPENDED') return false;
  const idle = ctx?.idleShareByOrderId?.get(order.id) ?? 0;
  return idle > 0;
}

// ─── Health resolvers ────────────────────────────────────────────────────────

const CRITICAL_ORDER_STATUSES = new Set<OrderStatus>(['REJECTED', 'PENDING_CANCEL']);
const CRITICAL_ROUTE_STATUSES = new Set<string>([
  'REJECTED', 'CXLREJ', 'CXLRPRJ', 'ROUTE-ERR', 'BUST',
]);

export interface OrderHealthInput {
  order: Order;
  conditions: MonitorConditions;
  ctx?: LazyContext;
}

export function getOrderHealth({ order, conditions, ctx }: OrderHealthInput): HealthLevel {
  if (CRITICAL_ORDER_STATUSES.has(order.status)) return 'critical';
  if (matchesAnyCondition(order, conditions)) return 'warning';
  if (isLazyOrder(order, ctx)) return 'info';
  return 'healthy';
}

export function getRouteHealth(route: Route): HealthLevel {
  if (CRITICAL_ROUTE_STATUSES.has(route.status)) return 'critical';
  if (route.status === 'CXLRPRQ' || route.status === 'CXLREP' || route.status === 'REPPEN') return 'info';
  return 'healthy';
}

/** Pick the higher-severity level of two. */
export function maxHealth(a: HealthLevel, b: HealthLevel): HealthLevel {
  return HEALTH_RANK[a] >= HEALTH_RANK[b] ? a : b;
}

/** Stable ordering: critical first, then warning, info, healthy. */
export function compareHealth(a: HealthLevel, b: HealthLevel): number {
  return HEALTH_RANK[b] - HEALTH_RANK[a];
}

// ─── Convenience accessors ─────────────────────────────────────────────────────

/** Returns the text color for a health level (matching the strip color). */
export function getHealthColor(level: HealthLevel): string {
  const colorMap: Record<HealthLevel, string> = {
    critical: 'text-red-500',
    warning: 'text-amber-500',
    info: 'text-sky-500',
    healthy: 'text-emerald-500',
  };
  return colorMap[level];
}

/** Returns a background tint class for a health level. */
export function getHealthBg(level: HealthLevel): string {
  const bgMap: Record<HealthLevel, string> = {
    critical: 'bg-red-500/10',
    warning: 'bg-amber-500/10',
    info: 'bg-sky-500/10',
    healthy: 'bg-emerald-500/10',
  };
  return bgMap[level];
}

/** Returns a human-readable label for a health level. */
export function getHealthLabel(level: HealthLevel): string {
  return HEALTH_PALETTE[level].label;
}
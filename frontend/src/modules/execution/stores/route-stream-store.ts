/**
 * Route stream store — applies delta events to a local entity map.
 * Handles parent-child synchronization and deduplication.
 */

import type { Route } from '@execution/types'
import type { DeltaEvent } from '@shared/services/realtime';

export interface RouteStreamStore {
  /** Apply a delta event. Returns true if the store was modified. */
  apply(event: DeltaEvent): boolean;
  /** Get current snapshot as array (same shape as REST response). */
  snapshot(): Route[];
  /** Replace all routes (used for initial REST snapshot). */
  reset(routes: Route[]): void;
  /** Number of tracked routes. */
  readonly size: number;
}

export function createRouteStreamStore(): RouteStreamStore {
  const map = new Map<string, Route>();

  return {
    apply(event: DeltaEvent): boolean {
      const key = event.key;
      if (event.type === 'delete') {
        return map.delete(key);
      }
      const existing = map.get(key);
      const incoming = event.data as unknown as Route;
      if (existing && event.type === 'update') {
        map.set(key, { ...existing, ...incoming });
      } else {
        map.set(key, incoming);
      }
      return true;
    },

    snapshot(): Route[] {
      return Array.from(map.values());
    },

    reset(routes: Route[]): void {
      map.clear();
      for (const r of routes) {
        map.set(r.id, r);
      }
    },

    get size() {
      return map.size;
    },
  };
}
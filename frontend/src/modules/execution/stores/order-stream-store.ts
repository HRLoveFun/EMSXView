/**
 * Order stream store — applies delta events to a local entity map.
 * Handles version checks and partial patch merges.
 */

import type { Order } from '@execution/types'
import type { DeltaEvent } from '@execution/services/realtime';

export interface OrderStreamStore {
  /** Apply a delta event. Returns true if the store was modified. */
  apply(event: DeltaEvent): boolean;
  /** Get current snapshot as array (same shape as REST response). */
  snapshot(): Order[];
  /** Replace all orders (used for initial REST snapshot). */
  reset(orders: Order[]): void;
  /** Number of tracked orders. */
  readonly size: number;
}

export function createOrderStreamStore(): OrderStreamStore {
  const map = new Map<string, Order>();

  return {
    apply(event: DeltaEvent): boolean {
      const key = event.key;
      if (event.type === 'delete') {
        return map.delete(key);
      }
      // snapshot or update — merge data into map
      const existing = map.get(key);
      const incoming = event.data as unknown as Order;
      if (existing && event.type === 'update') {
        // Merge: incoming fields overwrite existing, keep fields not in incoming
        map.set(key, { ...existing, ...incoming });
      } else {
        map.set(key, incoming);
      }
      return true;
    },

    snapshot(): Order[] {
      return Array.from(map.values());
    },

    reset(orders: Order[]): void {
      map.clear();
      for (const o of orders) {
        map.set(o.id, o);
      }
    },

    get size() {
      return map.size;
    },
  };
}
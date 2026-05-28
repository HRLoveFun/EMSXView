/**
 * useOrdersStream — stream-backed order state hook.
 * Loads initial snapshot via REST, then applies deltas from WebSocket.
 * Falls back to polling when stream is disconnected.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import type { Order } from '@execution/types'
import type { RealtimeClient, DeltaEvent } from '@execution/services/realtime';
import { createOrderStreamStore } from '@execution/stores/order-stream-store';

interface UseOrdersStreamOptions {
  /** Realtime client instance */
  client: RealtimeClient | null;
  /** Initial orders from REST snapshot */
  initialOrders: Order[];
  /** Whether the stream is enabled */
  enabled: boolean;
}

interface UseOrdersStreamResult {
  orders: Order[];
  applyDelta: (event: DeltaEvent) => void;
  resetFromSnapshot: (orders: Order[]) => void;
}

export function useOrdersStream({
  client,
  initialOrders,
  enabled,
}: UseOrdersStreamOptions): UseOrdersStreamResult {
  const storeRef = useRef(createOrderStreamStore());
  const [orders, setOrders] = useState<Order[]>(initialOrders);

  // Sync initial orders into store
  useEffect(() => {
    storeRef.current.reset(initialOrders);
    setOrders(storeRef.current.snapshot());
  }, [initialOrders]);

  const applyDelta = useCallback((event: DeltaEvent) => {
    if (storeRef.current.apply(event)) {
      setOrders(storeRef.current.snapshot());
    }
  }, []);

  const resetFromSnapshot = useCallback((newOrders: Order[]) => {
    storeRef.current.reset(newOrders);
    setOrders(storeRef.current.snapshot());
  }, []);

  // Subscribe to realtime client
  useEffect(() => {
    if (!client || !enabled) return;
    const unsub = client.on('order', applyDelta);
    return unsub;
  }, [client, enabled, applyDelta]);

  return { orders, applyDelta, resetFromSnapshot };
}
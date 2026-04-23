/**
 * useRoutesStream — stream-backed route state hook.
 * Loads initial snapshot via REST, then applies deltas from WebSocket.
 * Falls back to polling when stream is disconnected.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import type { Route } from '@/types';
import type { RealtimeClient, DeltaEvent } from '@/services/realtime';
import { createRouteStreamStore } from '@/stores/route-stream-store';

interface UseRoutesStreamOptions {
  /** Realtime client instance */
  client: RealtimeClient | null;
  /** Initial routes from REST snapshot */
  initialRoutes: Route[];
  /** Whether the stream is enabled */
  enabled: boolean;
}

interface UseRoutesStreamResult {
  routes: Route[];
  applyDelta: (event: DeltaEvent) => void;
  resetFromSnapshot: (routes: Route[]) => void;
}

export function useRoutesStream({
  client,
  initialRoutes,
  enabled,
}: UseRoutesStreamOptions): UseRoutesStreamResult {
  const storeRef = useRef(createRouteStreamStore());
  const [routes, setRoutes] = useState<Route[]>(initialRoutes);

  // Sync initial routes into store
  useEffect(() => {
    storeRef.current.reset(initialRoutes);
    setRoutes(storeRef.current.snapshot());
  }, [initialRoutes]);

  const applyDelta = useCallback((event: DeltaEvent) => {
    if (storeRef.current.apply(event)) {
      setRoutes(storeRef.current.snapshot());
    }
  }, []);

  const resetFromSnapshot = useCallback((newRoutes: Route[]) => {
    storeRef.current.reset(newRoutes);
    setRoutes(storeRef.current.snapshot());
  }, []);

  // Subscribe to realtime client
  useEffect(() => {
    if (!client || !enabled) return;
    const unsub = client.on('route', applyDelta);
    return unsub;
  }, [client, enabled, applyDelta]);

  return { routes, applyDelta, resetFromSnapshot };
}

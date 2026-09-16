/**
 * useExecutionPoller — background polling effects for the execution view.
 *
 * Three independent effects:
 *   1. REST fallback poll — runs when WebSocket is disconnected, fetches
 *      orders+routes every 2s with backoff on consecutive errors.
 *   2. Reconcile poll — runs alongside WebSocket to catch dropped updates.
 *      Configurable cadence (5/15/30/60s). Skips when user mutations are
 *      in-flight. Warns after 3 consecutive failures.
 *   3. Trader cache refresh — validates the traderInfo cache every 30s.
 */

import { useEffect } from 'react';
import { getReconcileIntervalMs } from '@execution/lib';
import type { Toast } from '@shared/types';

interface TraderInfoCache {
  isValid: () => boolean;
}

interface UseExecutionPollerOptions {
  isAuthenticated: boolean;
  isBackendReady: boolean;
  streamConnected: boolean;
  allowFallbackFetch: boolean;
  fetchOrdersAndRoutes: () => Promise<void>;
  fetchTraderInfo: (forceRefresh?: boolean) => Promise<void>;
  traderInfoCache: TraderInfoCache;
  inflightMutationsRef: React.MutableRefObject<number>;
  onToast: (type: Toast['type'], message: string) => void;
}

export function useExecutionPoller({
  isAuthenticated,
  isBackendReady,
  streamConnected,
  allowFallbackFetch,
  fetchOrdersAndRoutes,
  fetchTraderInfo,
  traderInfoCache,
  inflightMutationsRef,
  onToast,
}: UseExecutionPollerOptions): void {
  // ── REST fallback poll (no WebSocket) ──────────────────────────────────
  useEffect(() => {
    const canPoll = isBackendReady || allowFallbackFetch;
    if (!isAuthenticated || streamConnected || !canPoll) {
      return;
    }

    let active = true;
    let consecutiveErrors = 0;
    const maxConsecutiveErrors = 5;
    const baseInterval = 2000;
    const backoffInterval = 5000;

    const getInterval = () => {
      if (consecutiveErrors >= maxConsecutiveErrors) return backoffInterval;
      if (document.hidden) return baseInterval * 2;
      return baseInterval;
    };

    const poll = async () => {
      const startTime = Date.now();
      try {
        await fetchOrdersAndRoutes();
        consecutiveErrors = 0;
      } catch {
        consecutiveErrors += 1;
        if (consecutiveErrors === maxConsecutiveErrors) {
          console.warn('Multiple polling errors detected, backing off...');
        }
      }

      if (active) {
        const elapsed = Date.now() - startTime;
        const interval = getInterval();
        const delay = Math.max(0, interval - elapsed);
        timer = setTimeout(poll, delay);
      }
    };

    let timer = setTimeout(poll, baseInterval);

    const handleVisibilityChange = () => {
      clearTimeout(timer);
      if (active) {
        timer = setTimeout(poll, document.hidden ? baseInterval * 2 : baseInterval);
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      active = false;
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [allowFallbackFetch, fetchOrdersAndRoutes, isAuthenticated, isBackendReady, streamConnected]);

  // ── Reconcile poll (alongside WebSocket) ───────────────────────────────
  useEffect(() => {
    if (!isAuthenticated || !isBackendReady || !streamConnected) {
      return;
    }

    let active = true;
    let reconcileFailures = 0;
    let reconcileWarned = false;

    const tick = async () => {
      const base = getReconcileIntervalMs();
      if (inflightMutationsRef.current === 0) {
        try {
          await fetchOrdersAndRoutes();
          if (reconcileWarned) {
            onToast('success', 'Data refresh recovered');
          }
          reconcileFailures = 0;
          reconcileWarned = false;
        } catch {
          reconcileFailures += 1;
          if (reconcileFailures >= 3 && !reconcileWarned) {
            reconcileWarned = true;
            onToast('error', 'Background refresh failing — table data may be stale');
          }
        }
      }
      if (active) {
        timer = setTimeout(tick, document.hidden ? base * 2 : base);
      }
    };

    let timer = setTimeout(tick, getReconcileIntervalMs());
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [fetchOrdersAndRoutes, isAuthenticated, isBackendReady, streamConnected, inflightMutationsRef, onToast]);

  // ── Trader cache refresh ───────────────────────────────────────────────
  useEffect(() => {
    if (!isAuthenticated || !isBackendReady) {
      return;
    }

    let active = true;
    const checkInterval = 30000;

    const checkAndRefresh = async () => {
      if (!traderInfoCache.isValid()) {
        await fetchTraderInfo();
      }

      if (active) {
        timer = setTimeout(checkAndRefresh, checkInterval);
      }
    };

    let timer = setTimeout(checkAndRefresh, checkInterval);

    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [fetchTraderInfo, traderInfoCache, isAuthenticated, isBackendReady]);
}

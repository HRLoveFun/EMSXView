// App Module Navigation — global shell state
import { useMemo, useState } from 'react';
import type { StartupStatusSnapshot } from '@shared/types';

export type AppModule = 'marketview' | 'execution' | 'costview' | 'database';

/** UI mode for the subscriptions-warming notice. */
export type SubscriptionsWarmingMode = 'initial' | 'reconnecting' | 'timed-out';

/** After this many seconds with no stream + no data, surface a degraded-mode notice. */
const SUBSCRIPTIONS_WARMING_TIMEOUT_SEC = 60;

interface UseModuleNavigationParams {
  startupStatus: StartupStatusSnapshot | null;
  isBackendReady: boolean;
  streamConnected: boolean;
  streamEverConnected: boolean;
  startupElapsedSeconds: number;
  orderCount: number;
  routeCount: number;
}

export function useModuleNavigation({
  startupStatus,
  isBackendReady,
  streamConnected,
  streamEverConnected,
  startupElapsedSeconds,
  orderCount,
  routeCount,
}: UseModuleNavigationParams) {
  const [activeModule, setActiveModule] = useState<AppModule>('execution');

  const httpReady = startupStatus?.backend.httpReady ?? false;
  const startupFailed = startupStatus?.phase === 'error';
  const shouldShowStartupGate =
    (!httpReady || startupFailed)
    && !streamConnected
    && orderCount === 0
    && routeCount === 0;

  const subscriptionsWarming =
    httpReady
    && !isBackendReady
    && !streamConnected
    && orderCount === 0
    && routeCount === 0;

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

  return {
    activeModule,
    setActiveModule,
    shouldShowStartupGate,
    subscriptionsWarming,
    subscriptionsWarmingTimedOut,
    subscriptionsWarmingMode,
    footerConnectionText,
  };
}
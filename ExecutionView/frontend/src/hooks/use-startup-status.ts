import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { apiService } from '@/services/api';
import type { ConnectionStatus, StartupStatusSnapshot } from '@/types';

interface UseStartupStatusOptions {
  enabled: boolean;
  pollIntervalMs?: number;
  readyPollIntervalMs?: number;
  timeoutMs?: number;
}

const DEFAULT_POLL_INTERVAL_MS = 2000;
const DEFAULT_READY_POLL_INTERVAL_MS = 30000;
const DEFAULT_TIMEOUT_MS = 60000;

function buildSyntheticStartupStatus(elapsedMs: number, timeoutMs: number, error?: string): StartupStatusSnapshot {
  const timedOut = elapsedMs >= timeoutMs;
  return {
    phase: timedOut ? 'error' : 'backend_starting',
    ready: false,
    message: timedOut
      ? error || '前端已经启动，但 backend HTTP 仍未就绪。'
      : '前端已经启动，正在等待 backend HTTP 服务响应。',
    backend: {
      httpReady: false,
      startedAt: undefined,
      uptime: Math.floor(elapsedMs / 1000),
    },
    bloomberg: {
      status: timedOut ? 'error' : 'connecting',
      message: timedOut ? error || 'Backend unavailable' : 'Waiting for backend HTTP service',
      lastConnected: undefined,
      uptime: undefined,
    },
    subscriptions: {
      ordersInitPaintDone: false,
      routesInitPaintDone: false,
      subscriptionFailed: timedOut,
      marketDataConnected: false,
      orderCount: 0,
      routeCount: 0,
      ready: false,
    },
  };
}

function deriveConnectionStatus(startupStatus: StartupStatusSnapshot | null): ConnectionStatus {
  if (!startupStatus) {
    return 'pending';
  }
  if (startupStatus.phase === 'ready') {
    return 'connected';
  }
  if (startupStatus.phase === 'error') {
    return 'disconnected';
  }
  return 'pending';
}

export function useStartupStatus({
  enabled,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  readyPollIntervalMs = DEFAULT_READY_POLL_INTERVAL_MS,
  timeoutMs = DEFAULT_TIMEOUT_MS,
}: UseStartupStatusOptions) {
  const [startupStatus, setStartupStatus] = useState<StartupStatusSnapshot | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [isChecking, setIsChecking] = useState(false);
  const [probeId, setProbeId] = useState(0);
  const startedAtRef = useRef(Date.now());

  const retry = useCallback(() => {
    startedAtRef.current = Date.now();
    setElapsedSeconds(0);
    setStartupStatus(null);
    setProbeId(prev => prev + 1);
  }, []);

  useEffect(() => {
    if (!enabled) {
      setStartupStatus(null);
      setElapsedSeconds(0);
      return;
    }

    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      const elapsedMs = Date.now() - startedAtRef.current;
      if (active) {
        setElapsedSeconds(Math.floor(elapsedMs / 1000));
        setIsChecking(true);
      }

      try {
        const response = await apiService.getStartupStatus();
        if (!active) return;
        if (response.success && response.data) {
          setStartupStatus(response.data);
          const delay = response.data.ready ? readyPollIntervalMs : pollIntervalMs;
          timer = setTimeout(poll, delay);
          return;
        }
        setStartupStatus(buildSyntheticStartupStatus(elapsedMs, timeoutMs, response.error));
      } catch (error) {
        if (!active) return;
        const message = error instanceof Error ? error.message : 'Network error';
        setStartupStatus(buildSyntheticStartupStatus(elapsedMs, timeoutMs, message));
      } finally {
        if (active) {
          setIsChecking(false);
        }
      }

      if (active) {
        timer = setTimeout(poll, pollIntervalMs);
      }
    };

    poll();

    return () => {
      active = false;
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [enabled, pollIntervalMs, probeId, readyPollIntervalMs, timeoutMs]);

  const connectionStatus = useMemo(() => deriveConnectionStatus(startupStatus), [startupStatus]);

  return {
    startupStatus,
    connectionStatus,
    elapsedSeconds,
    isChecking,
    retry,
    isReady: startupStatus?.ready ?? false,
  };
}
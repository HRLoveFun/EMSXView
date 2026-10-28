import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { getStartupStatus as fetchStartupStatus } from '@shared/services/startup-api';
import type { ConnectionStatus, StartupStatusSnapshot } from '@shared/types'

interface UseStartupStatusOptions {
  enabled: boolean;
  pollIntervalMs?: number;
  readyPollIntervalMs?: number;
  timeoutMs?: number;
}

const DEFAULT_POLL_INTERVAL_MS = 2000;
const DEFAULT_READY_POLL_INTERVAL_MS = 30000;
const DEFAULT_TIMEOUT_MS = 60000;

// 认证失败与「后端不可用」是两类问题：前者不该被启动门超时判成 error，
// 否则本地未配置 BYPASS_AUTH 时会误报为 Startup chain error。
const AUTH_ERROR_PATTERN =
  /authentication required|requires authentication|unauthorized|invalid username or password/i;

function isAuthError(message?: string): boolean {
  return !!message && AUTH_ERROR_PATTERN.test(message);
}

function buildSyntheticStartupStatus(
  elapsedMs: number,
  timeoutMs: number,
  error?: string,
  authRequired = false,
): StartupStatusSnapshot {
  // 认证缺失时后端本身是健康的，不进入 error 阶段
  const timedOut = !authRequired && elapsedMs >= timeoutMs;
  return {
    phase: timedOut ? 'error' : 'backend_starting',
    ready: false,
    message: authRequired
      ? 'Backend requires authentication. 本地开发请在 backend/.env 设置 BYPASS_AUTH=true，或在浏览器注入有效 token。'
      : error
        || (timedOut
          ? 'Frontend is up, but the backend HTTP service is not ready yet.'
          : 'Frontend is up, waiting for the backend HTTP service to respond.'),
    backend: {
      httpReady: false,
      startedAt: undefined,
      uptime: Math.floor(elapsedMs / 1000),
    },
    bloomberg: {
      status: timedOut ? 'error' : 'connecting',
      message: error || (timedOut ? 'Backend unavailable' : 'Waiting for backend HTTP service'),
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
  // 起始时刻在 effect 内落定：Date.now() 是不纯函数，不得在渲染期调用（react-hooks/purity）
  const startedAtRef = useRef(0);
  // Holds a callback that, when invoked, cancels the pending poll timer and
  // runs poll() immediately. Repopulated on every poll cycle.
  const wakeupRef = useRef<(() => void) | null>(null);

  const retry = useCallback(() => {
    startedAtRef.current = Date.now();
    setElapsedSeconds(0);
    setStartupStatus(null);
    setProbeId(prev => prev + 1);
  }, []);

  // 起始时刻落定（置于轮询 effect 之前，保证同一挂载周期内先于 poll 生效）
  useEffect(() => {
    startedAtRef.current = Date.now();
  }, []);

  useEffect(() => {
    // 未启用时的「空状态」由下方返回值派生，避免在 effect 内同步 setState
    if (!enabled) return;

    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const scheduleNext = (delay: number) => {
      timer = setTimeout(() => {
        timer = null;
        poll();
      }, delay);
      wakeupRef.current = () => {
        if (timer) {
          clearTimeout(timer);
          timer = null;
          poll();
        }
      };
    };

    const poll = async () => {
      const elapsedMs = Date.now() - startedAtRef.current;
      if (active) {
        setElapsedSeconds(Math.floor(elapsedMs / 1000));
        setIsChecking(true);
      }

      try {
        const response = await fetchStartupStatus();
        if (!active) return;
        if (response.success && response.data) {
          setStartupStatus(response.data);
          const delay = response.data.ready ? readyPollIntervalMs : pollIntervalMs;
          scheduleNext(delay);
          return;
        }
        setStartupStatus(
          buildSyntheticStartupStatus(elapsedMs, timeoutMs, response.error, isAuthError(response.error)),
        );
      } catch (error) {
        if (!active) return;
        const message = error instanceof Error ? error.message : 'Network error';
        setStartupStatus(
          buildSyntheticStartupStatus(elapsedMs, timeoutMs, message, isAuthError(message)),
        );
      } finally {
        if (active) {
          setIsChecking(false);
        }
      }

      if (active) {
        scheduleNext(pollIntervalMs);
      }
    };

    poll();

    // When the tab returns to the foreground, poll immediately rather than
    // waiting for the next setInterval tick (which could be many seconds
    // out after the browser throttled background timers).
    const handleVisibility = () => {
      if (document.visibilityState === 'visible' && wakeupRef.current) {
        wakeupRef.current();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      active = false;
      wakeupRef.current = null;
      document.removeEventListener('visibilitychange', handleVisibility);
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [enabled, pollIntervalMs, probeId, readyPollIntervalMs, timeoutMs]);

  const connectionStatus = useMemo(() => deriveConnectionStatus(startupStatus), [startupStatus]);

  // 未启用（enabled=false）时对外表现为「无状态」：在返回值处派生
  return {
    startupStatus: enabled ? startupStatus : null,
    connectionStatus: enabled ? connectionStatus : 'pending',
    elapsedSeconds: enabled ? elapsedSeconds : 0,
    isChecking: enabled ? isChecking : false,
    retry,
    isReady: enabled ? (startupStatus?.ready ?? false) : false,
  };
}
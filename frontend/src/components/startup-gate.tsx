import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2, RotateCcw, Server } from 'lucide-react';

import { Button } from '@/components/ui/button';
import type { BloombergConnectionState, StartupPhase } from '@shared/types'

interface StartupGateProps {
  phase: StartupPhase;
  elapsedSeconds: number;
  message?: string;
  httpReady: boolean;
  bloombergStatus: BloombergConnectionState;
  subscriptionsReady: boolean;
  onRetry: () => void;
}

export function StartupGate({
  phase,
  elapsedSeconds,
  message,
  httpReady,
  bloombergStatus,
  subscriptionsReady,
  onRetry,
}: StartupGateProps) {
  const isError = phase === 'error';
  // Throttle the manual retry so an anxious user mashing the button does
  // not produce a thundering herd of probe requests against the backend.
  const [retryCount, setRetryCount] = useState(0);
  const [retryCooldown, setRetryCooldown] = useState(0);

  useEffect(() => {
    if (retryCooldown <= 0) return;
    const t = setTimeout(() => setRetryCooldown(c => Math.max(0, c - 1)), 1000);
    return () => clearTimeout(t);
  }, [retryCooldown]);

  const handleRetry = () => {
    if (retryCooldown > 0) return;
    setRetryCount(c => c + 1);
    setRetryCooldown(3); // 3-second debounce window
    onRetry();
  };
  const title =
    phase === 'backend_starting'
      ? 'Backend HTTP service is starting'
      : phase === 'bloomberg_connecting'
        ? 'Connecting to Bloomberg EMSX'
        : phase === 'subscriptions_warming'
          ? 'Warming up order & route subscriptions'
          : phase === 'error'
            ? 'Startup chain error'
            : 'Startup still in progress';

  const description =
    message
    || (phase === 'backend_starting'
      ? 'Frontend is ready, waiting for the backend HTTP layer to report startup status.'
      : phase === 'bloomberg_connecting'
        ? 'HTTP is ready, establishing Bloomberg session.'
        : phase === 'subscriptions_warming'
          ? 'Bloomberg connected. Order & route data will load automatically after INIT_PAINT completes.'
          : phase === 'error'
            ? 'The startup chain could not complete. Check that the backend service is running and reachable, then use the Re-check button below.'
            : 'The frontend is open, but the startup sequence has not fully completed. You can stay on this page to continue monitoring the status.');

  return (
    <div className="mx-auto flex min-h-[calc(100vh-12rem)] max-w-4xl items-center justify-center px-4 py-10">
      <div className="w-full rounded-3xl border border-border bg-card/95 p-8 shadow-2xl shadow-black/10 backdrop-blur">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-4">
            <div className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-muted/60 px-3 py-1 text-xs font-medium text-muted-foreground">
              <Server className="h-3.5 w-3.5" />
              ExecutionView Startup Gate
            </div>

            <div className="space-y-2">
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h2>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>
            </div>

            <div className="grid gap-3 text-sm text-muted-foreground sm:grid-cols-4">
              <div className="rounded-2xl border border-border/70 bg-background/70 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground/70">Frontend</div>
                <div className="mt-2 font-medium text-foreground">Started</div>
              </div>
              <div className="rounded-2xl border border-border/70 bg-background/70 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground/70">HTTP Layer</div>
                <div className="mt-2 font-medium text-foreground">{httpReady ? 'Ready' : 'Starting'}</div>
              </div>
              <div className="rounded-2xl border border-border/70 bg-background/70 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground/70">Bloomberg</div>
                <div className="mt-2 font-medium text-foreground">{bloombergStatus}</div>
              </div>
              <div className="rounded-2xl border border-border/70 bg-background/70 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground/70">Subscriptions</div>
                <div className="mt-2 font-medium text-foreground">{subscriptionsReady ? 'Done' : 'In Progress'}</div>
                <div className="mt-2 text-xs text-muted-foreground">Elapsed {elapsedSeconds}s</div>
              </div>
            </div>
          </div>

          <div className="flex min-w-[220px] flex-col gap-3 rounded-2xl border border-border/70 bg-background/70 p-4">
            <div className={`flex items-center gap-3 rounded-2xl px-4 py-3 text-sm ${isError ? 'bg-amber-500/10 text-amber-700 dark:text-amber-300' : 'bg-primary/10 text-primary'}`}>
              {isError ? <AlertTriangle className="h-4 w-4" /> : <Loader2 className="h-4 w-4 animate-spin" />}
              <span>{isError ? 'Manual check of startup chain needed' : 'Continuously checking startup status'}</span>
            </div>

            <Button onClick={handleRetry} disabled={retryCooldown > 0} className="gap-2">
              {retryCooldown > 0
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : <RotateCcw className="h-4 w-4" />}
              {retryCooldown > 0 ? `Wait ${retryCooldown}s` : 'Re-check'}
            </Button>
            {retryCount > 0 && (
              <div className="text-[11px] text-muted-foreground">
                Retried {retryCount} time{retryCount === 1 ? '' : 's'}
              </div>
            )}

            <div className="text-xs leading-5 text-muted-foreground">
              {/* Display a relative log path so it remains accurate on any
                  deployment host and does not expose a developer username
                  baked into an absolute path. */}
              Log path: <span className="font-mono text-foreground">./logs/</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
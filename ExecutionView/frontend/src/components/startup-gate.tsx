import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2, RotateCcw, Server } from 'lucide-react';

import { Button } from '@/components/ui/button';
import type { BloombergConnectionState, StartupPhase } from '@/types';

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
      ? '后台 HTTP 服务正在启动'
      : phase === 'bloomberg_connecting'
        ? '正在连接 Bloomberg EMSX'
        : phase === 'subscriptions_warming'
          ? '正在热身订单与路由订阅'
          : '启动仍未完成';

  const description =
    message
    || (phase === 'backend_starting'
      ? '前端已经可用，正在等待 backend HTTP 层返回启动状态。'
      : phase === 'bloomberg_connecting'
        ? 'HTTP 已经可用，正在建立 Bloomberg 会话。'
        : phase === 'subscriptions_warming'
          ? 'Bloomberg 已连接，订单与路由数据会在 INIT_PAINT 完成后自动加载。'
          : '前端已经打开，但启动链路尚未全部完成。你可以留在此页面继续观察状态。');

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
                <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground/70">前端状态</div>
                <div className="mt-2 font-medium text-foreground">已启动</div>
              </div>
              <div className="rounded-2xl border border-border/70 bg-background/70 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground/70">HTTP 层</div>
                <div className="mt-2 font-medium text-foreground">{httpReady ? '已就绪' : '启动中'}</div>
              </div>
              <div className="rounded-2xl border border-border/70 bg-background/70 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground/70">Bloomberg</div>
                <div className="mt-2 font-medium text-foreground">{bloombergStatus}</div>
              </div>
              <div className="rounded-2xl border border-border/70 bg-background/70 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground/70">订阅热身</div>
                <div className="mt-2 font-medium text-foreground">{subscriptionsReady ? '已完成' : '进行中'}</div>
                <div className="mt-2 text-xs text-muted-foreground">等待时间 {elapsedSeconds}s</div>
              </div>
            </div>
          </div>

          <div className="flex min-w-[220px] flex-col gap-3 rounded-2xl border border-border/70 bg-background/70 p-4">
            <div className={`flex items-center gap-3 rounded-2xl px-4 py-3 text-sm ${isError ? 'bg-amber-500/10 text-amber-700 dark:text-amber-300' : 'bg-primary/10 text-primary'}`}>
              {isError ? <AlertTriangle className="h-4 w-4" /> : <Loader2 className="h-4 w-4 animate-spin" />}
              <span>{isError ? '需要人工检查启动链路' : '持续检测启动状态'}</span>
            </div>

            <Button onClick={handleRetry} disabled={retryCooldown > 0} className="gap-2">
              {retryCooldown > 0
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : <RotateCcw className="h-4 w-4" />}
              {retryCooldown > 0 ? `稍候 ${retryCooldown}s` : '重新检测'}
            </Button>
            {retryCount > 0 && (
              <div className="text-[11px] text-muted-foreground">
                已重试 {retryCount} 次
              </div>
            )}

            <div className="text-xs leading-5 text-muted-foreground">
              {/* Display a relative log path so it remains accurate on any
                  deployment host and does not expose a developer username
                  baked into an absolute path. */}
              日志位置：<span className="font-mono text-foreground">./logs/</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
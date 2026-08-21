import { useEffect, useMemo, useState } from 'react';
import type { UpdateStatusResponse } from '../types';

interface UpdateControlProps {
  onTrigger: () => void;
  status: UpdateStatusResponse | null;
  pending: boolean;
}

const STALL_THRESHOLD_MS = 5 * 60 * 1000; // 5 minutes
/** Re-evaluate stalled state every 10s — `useMemo([status])` alone would not
 *  fire when the backend simply goes silent without changing the status object. */
const STALL_TICK_MS = 10 * 1000;

function isActive(status: UpdateStatusResponse | null): boolean {
  return !!status && (status.status === 'started' || status.status === 'running');
}

function computeStalled(status: UpdateStatusResponse | null): boolean {
  if (!status || !isActive(status)) return false;
  if (!status.last_activity_at) return false;
  const elapsed = Date.now() - new Date(status.last_activity_at).getTime();
  return elapsed > STALL_THRESHOLD_MS;
}

export function UpdateControl({ onTrigger, status, pending }: UpdateControlProps) {
  const active = isActive(status);
  // 持续重新计算 stalled（即使 status 引用没变也要重算），避免子进程静默卡住
  // 时 useMemo 缓存导致警告延迟出现
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setTick((n) => n + 1), STALL_TICK_MS);
    return () => window.clearInterval(id);
  }, [active]);
  const stalled = useMemo(
    () => (tick >= 0 ? computeStalled(status) : false),
    [status, tick],
  );
  const overall = Math.max(0, Math.min(100, status?.overall_progress ?? 0));
  const stageLabel = status?.stage?.label ?? (active ? 'Starting…' : '');
  const stagePct = status?.stage?.progress ?? 0;
  const stageDetail = status?.stage?.detail;

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">Daily incremental update</div>
          <div className="text-xs text-muted-foreground">
            Runs CostView daily_update.py on the backend host. Localhost-only.
          </div>
        </div>
        <button
          type="button"
          onClick={onTrigger}
          disabled={active || pending}
          className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {active ? 'Pipeline running…' : pending ? 'Triggering…' : 'Update'}
        </button>
      </div>

      {status && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span className="font-mono">{status.job_id.slice(0, 8)}</span>
            <span>
              {status.status}
              {stalled ? ' \u00b7 Stalled' : ''}
              {stageLabel && !stalled ? ` \u00b7 ${stageLabel} ${stagePct}%` : ''}
            </span>
          </div>
          {status.status === 'failed' && (
            <div className="rounded-md border border-rose-300 bg-rose-50 p-2 text-[11px] text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
              Pipeline job failed. Details below.
            </div>
          )}
          {stalled && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-2 text-[11px] text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
              No progress detected for over 5 minutes. The pipeline may be stuck.
              The backend watchdog will terminate it automatically.
            </div>
          )}
          {stageDetail && !stalled && (
            <div className="text-[11px] text-muted-foreground/80 truncate" title={stageDetail}>
              {stageDetail}
            </div>
          )}
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full transition-all ${
                status.status === 'failed'
                  ? 'bg-rose-500'
                  : status.status === 'completed'
                    ? 'bg-emerald-500'
                    : stalled
                      ? 'bg-amber-500'
                      : 'bg-primary'
              }`}
              style={{ width: `${overall}%` }}
            />
          </div>
          {status.error && (
            <pre className="max-h-32 overflow-auto rounded-md bg-rose-50 p-2 text-[10px] text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">
              {status.error}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
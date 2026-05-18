import { useMemo } from 'react';
import type { UpdateStatusResponse } from '../types';

interface UpdateControlProps {
  onTrigger: () => void;
  status: UpdateStatusResponse | null;
  pending: boolean;
}

const STALL_THRESHOLD_MS = 5 * 60 * 1000; // 5 minutes

function isActive(status: UpdateStatusResponse | null): boolean {
  return !!status && (status.status === 'started' || status.status === 'running');
}

function isStalled(status: UpdateStatusResponse | null): boolean {
  if (!status || !isActive(status)) return false;
  if (!status.last_activity_at) return false;
  const elapsed = Date.now() - new Date(status.last_activity_at).getTime();
  return elapsed > STALL_THRESHOLD_MS;
}

export function UpdateControl({ onTrigger, status, pending }: UpdateControlProps) {
  const active = isActive(status);
  const stalled = useMemo(() => isStalled(status), [status]);
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
          {active ? 'Pipeline running…' : pending ? 'Triggering…' : 'Trigger update'}
        </button>
      </div>

      {status && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span className="font-mono">{status.job_id.slice(0, 8)}</span>
            <span>
              {status.status}
              {stalled ? ' · ⚠️ Stalled' : ''}
              {stageLabel && !stalled ? ` · ${stageLabel} ${stagePct}%` : ''}
            </span>
          </div>
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
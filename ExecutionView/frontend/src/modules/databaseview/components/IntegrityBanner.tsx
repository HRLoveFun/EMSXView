import type { IntegrityIssue } from '../types';

interface IntegrityBannerProps {
  issues: IntegrityIssue[];
  loading?: boolean;
}

export function IntegrityBanner({ issues, loading }: IntegrityBannerProps) {
  if (loading) {
    return (
      <div className="rounded-lg border border-dashed border-border p-3 text-xs text-muted-foreground">
        Running bounded integrity checks…
      </div>
    );
  }
  if (issues.length === 0) {
    return (
      <div className="rounded-lg border border-emerald-300/60 bg-emerald-50 p-3 text-xs text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
        No issues detected in the last scan window.
      </div>
    );
  }
  return (
    <ul className="space-y-1.5">
      {issues.map((issue, idx) => {
        const color =
          issue.severity === 'error'
            ? 'border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300'
            : issue.severity === 'warning'
              ? 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300'
              : 'border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-300';
        return (
          <li key={`${issue.code}-${idx}`} className={`rounded-md border px-3 py-2 text-xs ${color}`}>
            <div className="flex items-center gap-2">
              <span className="font-mono uppercase tracking-wide text-[10px]">{issue.severity}</span>
              <span className="font-mono text-[10px]">{issue.code}</span>
            </div>
            <div className="mt-0.5">{issue.message}</div>
          </li>
        );
      })}
    </ul>
  );
}

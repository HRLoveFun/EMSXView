/**
 * Reconcile poll interval — single source of truth for the cadence at which
 * the UI cross-checks the WebSocket-driven state against a REST snapshot.
 *
 * Stored in localStorage so it survives reload and cross-component access
 * (Settings UI writes; data hook reads on every tick).
 */

const STORAGE_KEY = 'emsx_reconcile_interval_sec';
const DEFAULT_INTERVAL_SEC = 15;
const ALLOWED = [5, 15, 30, 60] as const;
export type ReconcileIntervalSec = typeof ALLOWED[number];

export const RECONCILE_INTERVAL_OPTIONS: ReadonlyArray<{ value: ReconcileIntervalSec; label: string }> = [
  { value: 5, label: '5 seconds' },
  { value: 15, label: '15 seconds (default)' },
  { value: 30, label: '30 seconds' },
  { value: 60, label: '60 seconds' },
];

export function getReconcileIntervalMs(): number {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_INTERVAL_SEC * 1000;
    const n = parseInt(raw, 10);
    if (ALLOWED.includes(n as ReconcileIntervalSec)) return n * 1000;
  } catch {
    /* ignore storage failures */
  }
  return DEFAULT_INTERVAL_SEC * 1000;
}

export function getReconcileIntervalSec(): ReconcileIntervalSec {
  return (getReconcileIntervalMs() / 1000) as ReconcileIntervalSec;
}

export function setReconcileIntervalSec(sec: ReconcileIntervalSec): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(sec));
  } catch {
    /* ignore storage failures */
  }
}
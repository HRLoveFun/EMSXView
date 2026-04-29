import { useCallback, useEffect, useRef, useState } from 'react';
import { Database, RefreshCw } from 'lucide-react';
import { fetchOverview, fetchUpdateStatus, triggerUpdate } from './services/api';
import type { DatabaseOverview, UpdateStatusResponse } from './types';
import { DatabaseOverviewGrid } from './components/DatabaseOverviewGrid';
import { DatabaseDetailDrawer } from './components/DatabaseDetailDrawer';
import { UpdateControl } from './components/UpdateControl';
import { RestartHint } from './components/RestartHint';

export default function DatabaseViewModule() {
  const [overview, setOverview] = useState<DatabaseOverview[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatusResponse | null>(null);
  const [triggerPending, setTriggerPending] = useState(false);
  const pollRef = useRef<number | null>(null);

  const clearPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchOverview();
      setOverview(data.items);
      setSelectedKey((current) => current ?? data.items.find((i) => i.exists)?.key ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load database overview');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOverview();
    return clearPoll;
  }, [loadOverview, clearPoll]);

  const pollStatus = useCallback(
    async (jobId: string) => {
      try {
        const status = await fetchUpdateStatus(jobId);
        setUpdateStatus(status);
        clearPoll();
        if (status.status === 'started' || status.status === 'running') {
          pollRef.current = window.setTimeout(() => void pollStatus(jobId), 2000);
          return;
        }
        if (status.status === 'completed') {
          void loadOverview();
        }
      } catch (err) {
        setUpdateStatus((prev) => ({
          job_id: prev?.job_id ?? jobId,
          status: 'failed',
          started_at: prev?.started_at ?? new Date().toISOString(),
          completed_at: new Date().toISOString(),
          error: err instanceof Error ? err.message : 'Polling failed',
          stage: prev?.stage ?? null,
          overall_progress: prev?.overall_progress ?? 0,
          last_activity_at: new Date().toISOString(),
        }));
      }
    },
    [clearPoll, loadOverview],
  );

  const handleTrigger = useCallback(async () => {
    setTriggerPending(true);
    setError(null);
    clearPoll();
    try {
      const job = await triggerUpdate();
      setUpdateStatus({
        job_id: job.job_id,
        status: (job.status as UpdateStatusResponse['status']) || 'started',
        started_at: new Date().toISOString(),
        completed_at: null,
        error: null,
        stage: null,
        overall_progress: 0,
        last_activity_at: new Date().toISOString(),
      });
      void pollStatus(job.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to trigger update');
    } finally {
      setTriggerPending(false);
    }
  }, [clearPoll, pollStatus]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-primary" />
          <div>
            <h2 className="text-lg font-semibold leading-tight">Database</h2>
            <p className="text-xs text-muted-foreground">
              Date coverage, row counts and update orchestration for the CostView data layer.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void loadOverview()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      {error && (
        <div className="rounded-md border border-rose-300 bg-rose-50 p-3 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
          {error}
        </div>
      )}

      <RestartHint />

      <UpdateControl onTrigger={() => void handleTrigger()} status={updateStatus} pending={triggerPending} />

      {loading && overview.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-10 text-center text-xs text-muted-foreground">
          Loading database overview…
        </div>
      ) : (
        <DatabaseOverviewGrid
          items={overview}
          selectedKey={selectedKey}
          onSelect={(key) => setSelectedKey(key)}
        />
      )}

      {selectedKey && <DatabaseDetailDrawer dbKey={selectedKey} />}
    </div>
  );
}

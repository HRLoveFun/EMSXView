import { useEffect, useState } from 'react';
import type { DatabaseSummary, IntegrityIssue } from '../types';
import { fetchIntegrity, fetchSummary } from '../services/api';
import { DateCoverageHeatmap } from './DateCoverageHeatmap';
import { IntegrityBanner } from './IntegrityBanner';
import { SchemaSamplePanel } from './SchemaSamplePanel';
import { formatBytes, formatRowCount, normalizeTradeDate } from '../lib/format';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

interface DatabaseDetailDrawerProps {
  dbKey: string;
}

export function DatabaseDetailDrawer({ dbKey }: DatabaseDetailDrawerProps) {
  const [summary, setSummary] = useState<DatabaseSummary | null>(null);
  const [issues, setIssues] = useState<IntegrityIssue[] | null>(null);
  const [integrityLoading, setIntegrityLoading] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSummary(null);
    setIssues(null);
    setError(null);
    setSummaryLoading(true);
    fetchSummary(dbKey)
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load summary');
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dbKey]);

  const runIntegrity = async () => {
    setIntegrityLoading(true);
    setIssues(null);
    try {
      const data = await fetchIntegrity(dbKey);
      setIssues(data.issues);
    } catch (err) {
      setIssues([
        {
          severity: 'error',
          code: 'integrity_request_failed',
          message: err instanceof Error ? err.message : 'Integrity request failed',
        },
      ]);
    } finally {
      setIntegrityLoading(false);
    }
  };

  if (summaryLoading) {
    return (
      <div className="rounded-xl border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
        Loading <span className="font-mono">{dbKey}</span> summary…
      </div>
    );
  }

  if (error || !summary) {
    return (
      <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
        {error ?? 'Summary unavailable.'}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h3 className="text-base font-semibold">{summary.label}</h3>
        <p className="text-xs text-muted-foreground">{summary.description}</p>
        <p className="text-[11px] font-mono text-muted-foreground break-all">{summary.path}</p>
        <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs">
          <div><dt className="inline text-muted-foreground">Size: </dt><dd className="inline font-mono">{formatBytes(summary.size_bytes)}</dd></div>
          <div><dt className="inline text-muted-foreground">Tables: </dt><dd className="inline font-mono">{summary.tables.length}</dd></div>
        </dl>
      </header>

      <Tabs defaultValue="overview" className="w-full">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="schema">Schema &amp; Sample</TabsTrigger>
          <TabsTrigger value="integrity">Integrity</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4 pt-2">
          {summary.tables.map((table) => (
            <section key={table.name} className="space-y-2 rounded-xl border border-border bg-card p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold font-mono">{table.name}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {table.description} · date column:{' '}
                    <span className="font-mono">{table.date_column ?? '—'}</span>
                  </div>
                </div>
                <div className="text-[11px] text-muted-foreground">
                  <span className="font-mono">{formatRowCount(table.row_count)}</span> rows ·
                  <span className="font-mono ml-1">
                    {normalizeTradeDate(table.earliest_trade_date) ?? '—'}
                  </span>
                  <span className="mx-1">→</span>
                  <span className="font-mono">{normalizeTradeDate(table.latest_trade_date) ?? '—'}</span>
                  <span className="ml-1">({table.distinct_trade_dates} days)</span>
                </div>
              </div>
              {table.per_date_counts.length > 0 ? (
                <DateCoverageHeatmap counts={table.per_date_counts} />
              ) : (
                <div className="text-xs text-muted-foreground">No per-date coverage (table has no indexed date column).</div>
              )}
            </section>
          ))}
        </TabsContent>

        <TabsContent value="schema" className="pt-2">
          <SchemaSamplePanel dbKey={dbKey} tables={summary.tables} />
        </TabsContent>

        <TabsContent value="integrity" className="pt-2">
          <section className="space-y-2 rounded-xl border border-border bg-card p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold">Integrity</div>
                <div className="text-[11px] text-muted-foreground">
                  Bounded to recent rowids / dates to stay performant on large databases.
                </div>
              </div>
              <button
                type="button"
                onClick={runIntegrity}
                disabled={integrityLoading}
                className="rounded-md border border-border px-3 py-1 text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
              >
                {integrityLoading ? 'Scanning…' : issues === null ? 'Run check' : 'Re-check'}
              </button>
            </div>
            {issues !== null || integrityLoading ? (
              <IntegrityBanner issues={issues ?? []} loading={integrityLoading} />
            ) : (
              <div className="text-xs text-muted-foreground">Click "Run check" to start an integrity scan.</div>
            )}
          </section>
        </TabsContent>
      </Tabs>
    </div>
  );
}

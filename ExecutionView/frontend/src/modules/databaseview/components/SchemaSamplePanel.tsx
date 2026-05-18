import { useEffect, useMemo, useState } from 'react';
import type { SampleResponse, SchemaResponse, TableSummary } from '../types';
import { fetchTableSample, fetchTableSchema } from '../services/api';
import { SampleTable } from './SampleTable';
import { formatRowCount } from '../lib/format';

interface SchemaSamplePanelProps {
  dbKey: string;
  tables: TableSummary[];
  dbExists?: boolean;
}

const LIMIT_OPTIONS = [10, 50, 100, 200] as const;

export function SchemaSamplePanel({ dbKey, tables, dbExists = true }: SchemaSamplePanelProps) {
  const tableNames = useMemo(() => tables.map((t) => t.name), [tables]);
  const [activeTable, setActiveTable] = useState<string | null>(
    tableNames[0] ?? null,
  );
  const [limit, setLimit] = useState<number>(50);
  const [refreshTick, setRefreshTick] = useState(0);

  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  const [sample, setSample] = useState<SampleResponse | null>(null);
  const [sampleLoading, setSampleLoading] = useState(false);
  const [sampleError, setSampleError] = useState<string | null>(null);

  // Reset selection when the database key changes.
  useEffect(() => {
    setActiveTable(tableNames[0] ?? null);
  }, [dbKey, tableNames]);

  // Load schema whenever (db, table) changes.
  useEffect(() => {
    if (!activeTable) {
      setSchema(null);
      return;
    }
    let cancelled = false;
    setSchemaLoading(true);
    setSchema(null);
    setSchemaError(null);
    fetchTableSchema(dbKey, activeTable)
      .then((data) => {
        if (!cancelled) setSchema(data);
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setSchemaError(err instanceof Error ? err.message : 'Schema request failed');
      })
      .finally(() => {
        if (!cancelled) setSchemaLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dbKey, activeTable]);

  // Load sample whenever (db, table, limit) changes.
  useEffect(() => {
    if (!activeTable) {
      setSample(null);
      return;
    }
    let cancelled = false;
    setSampleLoading(true);
    setSample(null);
    setSampleError(null);
    fetchTableSample(dbKey, activeTable, limit)
      .then((data) => {
        if (!cancelled) setSample(data);
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setSampleError(err instanceof Error ? err.message : 'Sample request failed');
      })
      .finally(() => {
        if (!cancelled) setSampleLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dbKey, activeTable, limit, refreshTick]);

  if (tableNames.length === 0) {
    if (!dbExists) {
      return (
        <div className="rounded-xl border border-dashed border-amber-300 bg-amber-50/60 p-6 text-center text-xs text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300">
          The database file has not been created yet. This database requires a full data update run (
          <span className="font-mono">daily_update</span>) before tables appear.
        </div>
      );
    }
    return (
      <div className="rounded-xl border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
        This database currently has no tables to display.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {tableNames.length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Table:</span>
          {tableNames.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => setActiveTable(name)}
              className={`rounded-md border px-3 py-1 text-xs font-mono transition-colors ${
                activeTable === name
                  ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
                  : 'border-border hover:bg-muted'
              }`}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      {/* ── Schema section ────────────────────────────────────────────── */}
      <section className="space-y-2 rounded-xl border border-border bg-card p-4">
        <div className="flex items-baseline justify-between">
          <div>
            <div className="text-sm font-semibold">Schema</div>
            <div className="text-[11px] text-muted-foreground">
              Columns, types and indexes from <span className="font-mono">PRAGMA table_info</span>.
            </div>
          </div>
          {schema && (
            <div className="text-[11px] text-muted-foreground">
              {schema.columns.length} columns · {schema.indexes.length} indexes
            </div>
          )}
        </div>

        {schemaLoading && (
          <div className="text-xs text-muted-foreground">Loading schema…</div>
        )}
        {schemaError && (
          <div className="rounded-md border border-rose-300 bg-rose-50 p-2 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
            {schemaError}
          </div>
        )}
        {schema && !schemaLoading && (
          <>
            {schema.primary_key_display && (
              <div className="text-[11px] text-muted-foreground">
                Composite PK:{' '}
                <span className="font-mono">{schema.primary_key_display}</span>
              </div>
            )}
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="min-w-full text-[11px]">
                <thead className="bg-muted/50 text-left">
                  <tr>
                    <th className="border-b border-border px-2 py-1.5 font-semibold">Column</th>
                    <th className="border-b border-border px-2 py-1.5 font-semibold">Type</th>
                    <th className="border-b border-border px-2 py-1.5 font-semibold">Nullable</th>
                    <th className="border-b border-border px-2 py-1.5 font-semibold">PK</th>
                    <th className="border-b border-border px-2 py-1.5 font-semibold">Default</th>
                  </tr>
                </thead>
                <tbody>
                  {schema.columns.map((col) => (
                    <tr key={col.name} className="border-b border-border/50 last:border-b-0">
                      <td className="px-2 py-1 font-mono">{col.name}</td>
                      <td className="px-2 py-1 font-mono text-muted-foreground">
                        {col.type || '—'}
                      </td>
                      <td className="px-2 py-1 font-mono">{col.nullable ? 'yes' : 'no'}</td>
                      <td className="px-2 py-1 font-mono">
                        {col.primary_key > 0 ? `pk${col.primary_key}` : '—'}
                      </td>
                      <td className="px-2 py-1 font-mono text-muted-foreground">
                        {col.default_value ?? '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {schema.indexes.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {schema.indexes.map((idx) => (
                  <span
                    key={idx.name}
                    title={idx.columns.join(', ')}
                    className={`inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[10px] font-mono ${
                      idx.unique ? 'bg-emerald-50 dark:bg-emerald-950/30' : 'bg-muted/40'
                    }`}
                  >
                    {idx.unique ? 'UNIQ' : 'IDX'} · {idx.name} ({idx.columns.join(', ')})
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </section>

      {/* ── Sample section ────────────────────────────────────────────── */}
      <section className="space-y-2 rounded-xl border border-border bg-card p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <div className="text-sm font-semibold">Recent rows</div>
            <div className="text-[11px] text-muted-foreground">
              {sample?.order_by ? (
                <>Ordered by <span className="font-mono">{sample.order_by}</span>.</>
              ) : (
                'Most recent rows by date / rowid.'
              )}
              {sample && (
                <>
                  {' '}
                  Estimated total:{' '}
                  <span className="font-mono">{formatRowCount(sample.row_count_estimate)}</span>{' '}
                  rows.
                </>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-[11px] text-muted-foreground">
              Show
              <select
                value={limit}
                onChange={(event) => setLimit(Number(event.target.value))}
                className="ml-1 rounded-md border border-border bg-background px-2 py-1 font-mono"
              >
                {LIMIT_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => setRefreshTick((tick) => tick + 1)}
              disabled={sampleLoading}
              className="rounded-md border border-border px-3 py-1 text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
              title="Refresh sample"
            >
              Refresh
            </button>
          </div>
        </div>

        {sample?.fetched_at && (
          <div className="text-[10px] text-muted-foreground">
            Fetched at <span className="font-mono">{sample.fetched_at}</span>
          </div>
        )}

        {sampleLoading && (
          <div className="text-xs text-muted-foreground">Loading sample…</div>
        )}
        {sampleError && (
          <div className="rounded-md border border-rose-300 bg-rose-50 p-2 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
            {sampleError}
          </div>
        )}
        {sample && !sampleLoading && (
          <SampleTable
            columns={sample.columns}
            rows={sample.rows}
            anomalies={sample.anomalies}
            emptyMessage="Table is empty."
          />
        )}
        {sample && sample.anomalies.length > 0 && (
          <details className="text-[11px]">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              {sample.anomalies.length} column anomaly hint
              {sample.anomalies.length === 1 ? '' : 's'} (in this sample)
            </summary>
            <ul className="mt-1 space-y-0.5 pl-4">
              {sample.anomalies.map((a, idx) => (
                <li key={`${a.column}-${a.code}-${idx}`}>
                  <span className="font-mono">{a.column}</span>{' '}
                  <span
                    className={
                      a.severity === 'error'
                        ? 'text-rose-700 dark:text-rose-300'
                        : a.severity === 'warning'
                          ? 'text-amber-700 dark:text-amber-300'
                          : 'text-sky-700 dark:text-sky-300'
                    }
                  >
                    [{a.severity}]
                  </span>{' '}
                  {a.message}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </div>
  );
}
import type { ColumnAnomaly, SampleCell } from '../types';

interface SampleTableProps {
  columns: string[];
  rows: SampleCell[][];
  anomalies?: ColumnAnomaly[];
  emptyMessage?: string;
}

const CELL_DISPLAY_MAX = 120;

function formatCell(value: SampleCell): { text: string; isNull: boolean; isNumeric: boolean } {
  if (value === null || value === undefined) {
    return { text: 'NULL', isNull: true, isNumeric: false };
  }
  if (typeof value === 'number') {
    return { text: Number.isFinite(value) ? String(value) : 'NaN', isNull: false, isNumeric: true };
  }
  if (typeof value === 'boolean') {
    return { text: value ? 'true' : 'false', isNull: false, isNumeric: false };
  }
  const text = String(value);
  return { text, isNull: text === '', isNumeric: false };
}

function severityClasses(severity: string): string {
  if (severity === 'error') {
    return 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300';
  }
  if (severity === 'warning') {
    return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
  }
  return 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300';
}

/**
 * Lightweight read-only data grid used for the Schema & Sample tab.
 * Pure HTML <table> + Tailwind — no third-party grid library.
 */
export function SampleTable({ columns, rows, anomalies = [], emptyMessage }: SampleTableProps) {
  if (columns.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
        {emptyMessage ?? 'No columns to display.'}
      </div>
    );
  }

  // Index anomalies by column for fast lookup in header rendering.
  const anomalyByColumn = new Map<string, ColumnAnomaly[]>();
  for (const a of anomalies) {
    const list = anomalyByColumn.get(a.column);
    if (list) list.push(a);
    else anomalyByColumn.set(a.column, [a]);
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border bg-card">
      <table className="min-w-full text-[11px]">
        <thead className="bg-muted/50 text-left">
          <tr>
            {columns.map((col) => {
              const colAnomalies = anomalyByColumn.get(col) ?? [];
              return (
                <th
                  key={col}
                  className="sticky top-0 whitespace-nowrap border-b border-border px-2 py-1.5 font-mono font-semibold"
                >
                  <span className="inline-flex items-center gap-1">
                    {col}
                    {colAnomalies.map((a, idx) => (
                      <span
                        key={`${a.code}-${idx}`}
                        title={`${a.code}: ${a.message}`}
                        className={`inline-block rounded px-1 py-px text-[9px] font-normal uppercase tracking-wide ${severityClasses(a.severity)}`}
                      >
                        {a.code === 'high_null' ? '!NULL' : a.code === 'all_same' ? '=' : '!'}
                      </span>
                    ))}
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-2 py-4 text-center text-muted-foreground"
              >
                {emptyMessage ?? 'No rows.'}
              </td>
            </tr>
          ) : (
            rows.map((row, rIdx) => (
              <tr
                key={rIdx}
                className="border-b border-border/50 last:border-b-0 hover:bg-muted/40"
              >
                {row.map((cell, cIdx) => {
                  const fmt = formatCell(cell);
                  const display =
                    fmt.text.length > CELL_DISPLAY_MAX
                      ? fmt.text.slice(0, CELL_DISPLAY_MAX) + '…'
                      : fmt.text;
                  return (
                    <td
                      key={cIdx}
                      title={fmt.isNull ? undefined : fmt.text}
                      className={`whitespace-nowrap px-2 py-1 font-mono ${
                        fmt.isNumeric ? 'text-right' : 'text-left'
                      } ${fmt.isNull ? 'text-muted-foreground italic' : ''}`}
                    >
                      {display}
                    </td>
                  );
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
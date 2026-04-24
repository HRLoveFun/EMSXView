import { useMemo } from 'react';
import type { DateRowCount } from '../types';
import { formatRowCount, normalizeTradeDate } from '../lib/format';

interface DateCoverageHeatmapProps {
  counts: DateRowCount[];
  title?: string;
}

// Render a year × month-day heatmap of trading-day row counts.
// Uses normalized YYYY-MM-DD and grades cells by quintile of log(count).
export function DateCoverageHeatmap({ counts, title }: DateCoverageHeatmapProps) {
  const { cellMap, months, rows, minLog, maxLog } = useMemo(() => {
    const map = new Map<string, number>();
    for (const entry of counts) {
      const normalized = normalizeTradeDate(entry.trade_date) ?? entry.trade_date;
      map.set(normalized, (map.get(normalized) ?? 0) + entry.row_count);
    }
    const sorted = [...map.keys()].sort();
    const monthSet = new Set<string>();
    let minL = Infinity;
    let maxL = -Infinity;
    for (const date of sorted) {
      monthSet.add(date.slice(0, 7));
      const v = map.get(date) ?? 0;
      if (v > 0) {
        const l = Math.log10(v);
        if (l < minL) minL = l;
        if (l > maxL) maxL = l;
      }
    }
    if (!Number.isFinite(minL)) minL = 0;
    if (!Number.isFinite(maxL) || maxL === minL) maxL = minL + 1;
    const monthList = [...monthSet].sort();
    const dayRows = Array.from({ length: 31 }, (_, i) => i + 1);
    return {
      cellMap: map,
      months: monthList,
      rows: dayRows,
      minLog: minL,
      maxLog: maxL,
    };
  }, [counts]);

  if (months.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
        No date-level coverage data available.
      </div>
    );
  }

  function shade(count: number): string {
    if (!count) return 'bg-muted/30';
    const t = (Math.log10(count) - minLog) / (maxLog - minLog);
    // 5 buckets
    if (t < 0.2) return 'bg-emerald-100 dark:bg-emerald-950';
    if (t < 0.4) return 'bg-emerald-200 dark:bg-emerald-900';
    if (t < 0.6) return 'bg-emerald-300 dark:bg-emerald-800';
    if (t < 0.8) return 'bg-emerald-400 dark:bg-emerald-700';
    return 'bg-emerald-500 dark:bg-emerald-600';
  }

  return (
    <div className="space-y-2">
      {title && <div className="text-xs font-medium text-muted-foreground">{title}</div>}
      <div className="overflow-x-auto">
        <table className="text-[10px]">
          <thead>
            <tr>
              <th className="px-1 text-left text-muted-foreground">Day</th>
              {months.map((m) => (
                <th key={m} className="px-1 text-center font-normal text-muted-foreground">
                  {m}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((day) => (
              <tr key={day}>
                <td className="pr-1 text-right font-mono text-muted-foreground">{String(day).padStart(2, '0')}</td>
                {months.map((month) => {
                  const date = `${month}-${String(day).padStart(2, '0')}`;
                  const count = cellMap.get(date) ?? 0;
                  return (
                    <td key={`${month}-${day}`} className="p-[1px]">
                      <div
                        className={`h-3 w-3 rounded-[2px] ${shade(count)}`}
                        title={count ? `${date}: ${formatRowCount(count)} rows` : `${date}: no data`}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

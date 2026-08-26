import { useMemo } from 'react';
import type { DateRowCount } from '../types';
import { formatRowCount, normalizeTradeDate } from '../lib/format';

interface DateCoverageTableProps {
  counts: DateRowCount[];
  title?: string;
}

// Overview 日期覆盖表格：展示最近 20 个工作日（周一至周五）的
// 日期 / 行数 / 拉取日 / 异常说明 四列。无数据的日期以 note 标出。
// 拉取日与异常说明仅 raw_fills 提供，其余表显示为 "—"。

function noteTone(note: string | null | undefined): string {
  if (!note) return 'text-muted-foreground';
  if (note.includes('failed')) return 'text-rose-600';
  return 'text-amber-600';
}

export function DateCoverageTable({ counts, title }: DateCoverageTableProps) {
  // 倒序展示：最新日期在最上方（后端按日期升序返回，此处反转确保稳定）
  const rows = useMemo(
    () => [...counts].sort((a, b) => b.trade_date.localeCompare(a.trade_date)),
    [counts],
  );

  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
        No date-level coverage data available.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {title && <div className="text-xs font-medium text-muted-foreground">{title}</div>}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="py-1.5 pr-3 font-medium">Date</th>
              <th className="py-1.5 pr-3 text-right font-medium">Rows</th>
              <th className="py-1.5 pr-3 font-medium">Fetch date</th>
              <th className="py-1.5 font-medium">Note</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const date = normalizeTradeDate(row.trade_date) ?? row.trade_date;
              const hasData = row.row_count > 0;
              const note = row.note ?? (hasData ? null : 'no data');
              return (
                <tr
                  key={date}
                  className={`border-b border-border/50 last:border-b-0 ${hasData ? '' : 'bg-muted/30'}`}
                >
                  <td className="py-1.5 pr-3 font-mono">{date}</td>
                  <td className="py-1.5 pr-3 text-right font-mono">{formatRowCount(row.row_count)}</td>
                  <td className="py-1.5 pr-3 font-mono">
                    {normalizeTradeDate(row.fetch_date ?? '') ?? '—'}
                  </td>
                  <td className={`py-1.5 ${noteTone(note)}`}>{note ?? '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="text-[10px] text-muted-foreground">Recent 20 trading days (Mon–Fri).</div>
    </div>
  );
}

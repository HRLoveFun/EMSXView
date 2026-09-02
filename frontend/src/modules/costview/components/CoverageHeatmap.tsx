import { useMemo } from 'react';
import type { BdibHealthStatus, MetricCoverageRow } from '../types';
import { BDIB_DEPENDENT_METRICS, EXPECTED_NULL_METRICS, METRIC_LABELS, METRIC_NULL_REASON } from '../lib/monitoring-metrics';

interface CoverageHeatmapProps {
  /** 覆盖率行（按日期升序） */
  rows: MetricCoverageRow[];
  /** 当前勾选的指标列 */
  metrics: string[];
  /** 日期 → BDIB 健康状态（用于 NULL 归因 tooltip） */
  bdibStatusByDate?: Map<string, BdibHealthStatus>;
}

/** 覆盖率 → 单元格背景色（Tailwind arbitrary 值，由深红到深绿渐变）；期望内指标统一灰色 */
const coverageColor = (pct: number | null, expected: boolean): string => {
  if (expected) return 'bg-slate-800/50 text-slate-400';
  if (pct == null) return 'bg-muted/30 text-muted-foreground';
  if (pct >= 99) return 'bg-emerald-900/60 text-emerald-300';
  if (pct >= 90) return 'bg-lime-900/50 text-lime-300';
  if (pct >= 70) return 'bg-yellow-900/50 text-yellow-300';
  if (pct >= 50) return 'bg-orange-900/50 text-orange-300';
  return 'bg-red-900/60 text-red-300';
};

const BDIB_STATUS_LABELS: Record<BdibHealthStatus, string> = {
  ok: 'BDIB 完整',
  partial: 'BDIB 部分缺失',
  missing: 'BDIB 缺失（可回补）',
  unrecoverable: 'BDIB 缺失（不可回补）',
};

/** 单元格 tooltip 文本：覆盖率 + NULL 数 + 原因归因 */
const cellTitle = (
  row: MetricCoverageRow,
  metric: string,
  bdibStatus?: BdibHealthStatus,
  nullReason?: string,
): string => {
  const pct = row.coverage[metric];
  const nulls = row.null_counts[metric] ?? 0;
  const lines = [
    `${row.date} · ${metric}${METRIC_LABELS[metric] ? `（${METRIC_LABELS[metric]}）` : ''}`,
    `覆盖率: ${pct == null ? '—' : `${pct.toFixed(1)}%`}（NULL ${nulls}/${row.total_routes}）`,
  ];
  if (nullReason) lines.push(`归因: ${nullReason}`);
  if (bdibStatus && BDIB_DEPENDENT_METRICS.has(metric)) {
    lines.push(`BDIB 状态: ${BDIB_STATUS_LABELS[bdibStatus]}`);
  }
  return lines.join('\n');
};

/** 日期 × 指标覆盖率热力图 */
export function CoverageHeatmap({ rows, metrics, bdibStatusByDate }: CoverageHeatmapProps) {
  const sortedRows = useMemo(
    () => [...rows].sort((a, b) => a.date.localeCompare(b.date)),
    [rows],
  );

  if (!sortedRows.length || !metrics.length) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
        无覆盖率数据
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 bg-card px-2 py-1.5 text-left font-medium text-muted-foreground">
              日期
            </th>
          {metrics.map((metric) => {
            const expected = EXPECTED_NULL_METRICS.has(metric);
            return (
              <th key={metric} className="px-1 py-1.5 text-center font-medium text-muted-foreground" title={METRIC_LABELS[metric] ?? metric}>
                {metric}
                {expected && <span className="text-slate-500" title="期望内 NULL（SLA 豁免）">ⓘ</span>}
                {BDIB_DEPENDENT_METRICS.has(metric) && !expected && <span className="text-sky-400">*</span>}
              </th>
            );
          })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => {
            const rowKey = row.exchange ? `${row.date}-${row.exchange}` : row.date;
            const bdibStatus = bdibStatusByDate?.get(row.date);
            return (
              <tr key={rowKey} className="border-t border-border/40">
                <td className="sticky left-0 bg-card px-2 py-1 text-left font-mono">
                  {row.date}
                  {row.exchange && <span className="ml-1 text-muted-foreground">{row.exchange}</span>}
                </td>
                {metrics.map((metric) => {
                  const pct = row.coverage[metric];
                  const expected = EXPECTED_NULL_METRICS.has(metric);
                  const nullReason = row.null_reasons?.[metric];
                  return (
                    <td
                      key={metric}
                      className={`px-1 py-1 text-center tabular-nums ${coverageColor(pct, expected)}`}
                      title={cellTitle(row, metric, bdibStatus, expected ? '期望内 NULL' : nullReason)}
                    >
                      {pct == null ? '—' : pct.toFixed(0)}
                      {expected && <span className="text-slate-500 text-[9px] ml-0.5">ⓘ</span>}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted-foreground">
        单元格数值为覆盖率（%），<span className="text-sky-400">*</span> 表示依赖 BDIB 行情的指标；<span className="text-slate-500">ⓘ</span> 表示期望内 NULL（SLA 豁免）；悬停查看 NULL 计数与归因。
      </p>
    </div>
  );
}

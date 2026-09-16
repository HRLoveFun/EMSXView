import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { MetricCoverageReport } from '../../types';

/** 覆盖率单元格背景色（与 HTML 报告一致）：按 SLA 口径着色，SLA 无值时回退原始口径 */
function coverageBg(pct: number | null): string {
  if (pct == null) return '';
  if (pct >= 99.0) return 'bg-emerald-900/40';
  if (pct >= 90.0) return 'bg-lime-900/40';
  if (pct >= 50.0) return 'bg-yellow-900/40';
  return 'bg-red-900/40';
}

/** 指标覆盖率表（日期 × 指标，单元格按覆盖率着色，BDIB 依赖指标带 *） */
export function CoverageTable({ coverage }: { coverage?: MetricCoverageReport | null }) {
  if (!coverage || !coverage.rows.length) return null;
  const dependent = new Set(coverage.bdib_dependent_metrics ?? []);
  const overall = coverage.overall;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          指标覆盖率（%）
          <span className="ml-2 text-[10px] text-muted-foreground">
            * = 依赖 BDIB 行情；单元格＝原始 / SLA（底色按 SLA，悬停查看 NULL 原因）
            {overall?.coverage != null
              ? `；整体 原始 ${overall.coverage.toFixed(2)}% / SLA ${overall.sla_coverage?.toFixed(2) ?? '—'}%`
              : ''}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 z-10 bg-card">
              <tr className="text-muted-foreground">
                <th className="py-1 pr-2 text-left">日期</th>
                <th className="py-1 pr-2 text-right">routes</th>
                {coverage.metrics.map((m) => (
                  <th key={m} className="py-1 pr-2 text-right">{m}{dependent.has(m) ? '*' : ''}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {coverage.rows.map((row) => (
                <tr key={row.date} className="border-t border-muted">
                  <td className="py-0.5 pr-2 text-left text-muted-foreground">{row.date}</td>
                  <td className="py-0.5 pr-2 text-right">{row.total_routes}</td>
                  {coverage.metrics.map((m) => {
                    const v = row.coverage[m];
                    const sla = row.sla_coverage?.[m];
                    const reason = row.null_reasons?.[m];
                    const text = v == null
                      ? '—'
                      : sla == null || Math.abs(sla - v) < 0.05
                        ? v.toFixed(1)
                        : `${v.toFixed(1)} / ${sla.toFixed(1)}`;
                    return (
                      <td
                        key={m}
                        className={`py-0.5 pr-2 text-right ${coverageBg(sla ?? v)}`}
                        title={reason ? `NULL 原因：${reason}` : undefined}
                      >
                        {text}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

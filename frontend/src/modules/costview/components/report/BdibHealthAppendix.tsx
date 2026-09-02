import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { BdibHealthReport, BdibHealthStatus } from '../../types';

const statusLabel: Record<BdibHealthStatus, string> = {
  ok: 'ok',
  partial: 'partial',
  missing: 'missing',
  unrecoverable: 'unrecoverable',
};

const statusClass: Record<BdibHealthStatus, string> = {
  ok: 'bg-emerald-900/40 text-emerald-300',
  partial: 'bg-yellow-900/40 text-yellow-300',
  missing: 'bg-red-900/40 text-red-300',
  unrecoverable: 'bg-slate-700/40 text-slate-300',
};

/** BDIB 缺口附录（仅列出非 ok 日期，与 HTML 报告一致） */
export function BdibHealthAppendix({ health }: { health?: BdibHealthReport | null }) {
  if (!health || !health.dates.length) return null;
  const gapDates = health.dates.filter((d) => d.status !== 'ok');
  if (gapDates.length === 0) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">BDIB 缺口附录</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-20 items-center justify-center text-sm text-muted-foreground">
            监控范围内 BDIB 覆盖完整，无缺口
          </div>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">BDIB 缺口附录（{gapDates.length} 天）</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="py-1 pr-2 text-left">日期</th>
                <th className="py-1 pr-2 text-left">状态</th>
                <th className="py-1 pr-2 text-right">覆盖率</th>
                <th className="py-1 pr-2 text-right">缺口 ticker</th>
                <th className="py-1 pr-2 text-right">保留窗口剩余(天)</th>
                <th className="py-1 text-left">缺失 ticker 样例</th>
              </tr>
            </thead>
            <tbody>
              {gapDates.map((d) => (
                <tr key={d.date} className="border-t border-muted">
                  <td className="py-0.5 pr-2 text-left text-muted-foreground">{d.date}</td>
                  <td className="py-0.5 pr-2 text-left">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] ${statusClass[d.status]}`}>
                      {statusLabel[d.status]}
                    </span>
                  </td>
                  <td className="py-0.5 pr-2 text-right">{d.coverage_pct.toFixed(1)}%</td>
                  <td className="py-0.5 pr-2 text-right">{d.missing_ticker_count}</td>
                  <td className="py-0.5 pr-2 text-right">{d.retention_days_left}</td>
                  <td className="py-0.5 text-left text-muted-foreground">
                    {d.missing_tickers.slice(0, 8).join(', ')}
                    {d.missing_ticker_count > 8 ? '…' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground">
          保留窗口内（partial/missing）可用 scripts/ops/backfill_bdib_by_market.py 回补；
          unrecoverable 已超出 Bloomberg BDIB 保留期限，无法回补
        </div>
      </CardContent>
    </Card>
  );
}

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatBps } from '../../lib/report-format';
import type { TcaImpactBreakdown } from '../../types';

interface ImpactRow {
  label: string;
  value: number | null;
  desc: string;
}

/** 市场冲击分解表（B2-2）：暂时冲击 5/10/30min + 永久冲击 + 收盘价成本 */
export function ImpactBreakdownTable({ impact }: { impact?: TcaImpactBreakdown | null }) {
  if (!impact) return null;
  const rows: ImpactRow[] = [
    { label: '暂时冲击 5min', value: impact.temp_impact_5min_bps, desc: '成交后 5 分钟价格恢复偏离' },
    { label: '暂时冲击 10min', value: impact.temp_impact_10min_bps, desc: '成交后 10 分钟价格恢复偏离' },
    { label: '暂时冲击 30min', value: impact.temp_impact_30min_bps, desc: '成交后 30 分钟价格恢复偏离' },
    { label: '永久冲击', value: impact.perm_impact_bps, desc: '收盘价相对到达价的持续偏离' },
    { label: '收盘价成本', value: impact.close_cost_bps, desc: '收盘价基准偏离' },
  ];
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">市场冲击分解</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="py-1 pr-2 text-left">冲击维度</th>
                <th className="py-1 pr-2 text-right">加权值 (bps)</th>
                <th className="py-1 text-left">说明</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label} className="border-t border-muted">
                  <td className="py-1 pr-2 text-left">{r.label}</td>
                  <td className="py-1 pr-2 text-right">{formatBps(r.value)}</td>
                  <td className="py-1 text-left text-muted-foreground">{r.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground">
          成交额加权（RouteShares × p_avg）；恢复窗口越界时使用次日收盘价作跨日恢复价格
        </div>
      </CardContent>
    </Card>
  );
}

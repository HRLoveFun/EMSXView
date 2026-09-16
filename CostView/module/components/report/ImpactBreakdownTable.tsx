import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { appendNote, formatBps, formatWeightCoverage } from '../../lib/report-format';
import type { TcaImpactBreakdown, TcaReportSummary } from '../../types';

interface ImpactRow {
  label: string;
  value: number | null;
  desc: string;
  /** 对应的加权指标键：覆盖披露按指标取，与 HTML 报告冲击表逐行一致 */
  metric: string;
}

/**
 * 市场冲击分解表（B2-2）：暂时冲击 5/10/30min + 永久冲击 + 收盘价成本。
 *
 * 每行附该指标的样本量与权重覆盖披露（与 HTML 报告同表同措辞）：冲击均值同样只由
 * 有数据的路由子集决定，读者需知道该子集占多少条、多少成交额。
 */
export function ImpactBreakdownTable({
  impact,
  coverage,
}: {
  impact?: TcaImpactBreakdown | null;
  coverage?: TcaReportSummary['weight_coverage'];
}) {
  if (!impact) return null;
  const noteFor = (metric: string): string =>
    formatWeightCoverage(coverage?.metrics?.[metric]);
  const rows: ImpactRow[] = [
    {
      label: '暂时冲击 5min',
      value: impact.temp_impact_5min_bps,
      desc: '成交后 5 分钟价格恢复偏离',
      metric: 'temp_impact_5min_bps',
    },
    {
      label: '暂时冲击 10min',
      value: impact.temp_impact_10min_bps,
      desc: '成交后 10 分钟价格恢复偏离',
      metric: 'temp_impact_10min_bps',
    },
    {
      label: '暂时冲击 30min',
      value: impact.temp_impact_30min_bps,
      desc: '成交后 30 分钟价格恢复偏离',
      metric: 'temp_impact_30min_bps',
    },
    {
      label: '永久冲击',
      value: impact.perm_impact_bps,
      desc: '收盘价相对到达价的持续偏离',
      metric: 'perm_impact_bps',
    },
    {
      label: '收盘价成本',
      value: impact.close_cost_bps,
      desc: '收盘价基准偏离',
      metric: 'close_cost_bps',
    },
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
                  <td className="py-1 text-left text-muted-foreground">
                    {appendNote(r.desc, noteFor(r.metric))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground">
          成交额加权（fill × p_avg，与总成交金额同源）；恢复窗口越界时使用次日收盘价作跨日恢复价格
          {impact.recovery_truncated_count
            ? `。其中 ${impact.recovery_truncated_count.toLocaleString()} 条（${((impact.recovery_truncated_share ?? 0) * 100).toFixed(1)}%）为跨日兜底口径`
            : ''}
        </div>
      </CardContent>
    </Card>
  );
}

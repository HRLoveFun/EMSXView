import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatMoney } from '../../lib/report-format';
import type { TcaMarketNotionalRankRow } from '../../types';

/** 市场概览表（与 HTML 报告「市场概览」对齐）：route 数 + 成交金额（本币/USD） */
export function MarketOverviewTable({ rows }: { rows?: TcaMarketNotionalRankRow[] }) {
  const shown = rows ?? [];
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">市场概览</CardTitle>
      </CardHeader>
      <CardContent>
        {shown.length === 0 ? (
          <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">无数据</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="text-muted-foreground">
                  <th className="py-1 pr-2 text-left">市场</th>
                  <th className="py-1 pr-2 text-left">代码</th>
                  <th className="py-1 pr-2 text-right">Route 数</th>
                  <th className="py-1 pr-2 text-right">成交金额（本币）</th>
                  <th className="py-1 text-right">成交金额（美元）</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((m) => (
                  <tr key={m.exchange} className="border-t border-muted">
                    <td className="py-1 pr-2 text-left">{m.name}</td>
                    <td className="py-1 pr-2 text-left text-muted-foreground">{m.exchange}</td>
                    <td className="py-1 pr-2 text-right">{m.route_count.toLocaleString()}</td>
                    <td className="py-1 pr-2 text-right">{formatMoney(m.notional)}</td>
                    <td className="py-1 text-right">{formatMoney(m.notional_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-2 text-[10px] text-muted-foreground">
              市场顺序与白名单由 DataPipeline/config.py::Config.MARKET_ORDER 设定
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

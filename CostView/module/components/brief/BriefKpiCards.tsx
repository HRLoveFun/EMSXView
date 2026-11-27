import { Card, CardContent } from '@/components/ui/card';
import { costToneClass, formatSignedBps } from '../../lib/cost-sign';
import { formatInt, formatMoney, formatPct } from '../../lib/report-format';
import type { ExecutionBriefPayload } from '../../types';

interface KpiCard {
  label: string;
  value: string;
  sub: string;
  tone?: string;
}

/** 执行简报 KPI 首屏：规模 / 完成 / 成本 / 风险各一组，null 一律显示「—」。 */
export function BriefKpiCards({ brief }: { brief: ExecutionBriefPayload }) {
  const { coverage, overview, anomaly } = brief;
  const cards: KpiCard[] = [
    { label: '订单数', value: formatInt(coverage.orders), sub: `Route ${formatInt(coverage.route_count)}` },
    { label: '标的数', value: formatInt(coverage.symbols), sub: `交易员 ${formatInt(coverage.traders)} 名` },
    {
      label: '委托金额（USD）',
      value: formatMoney(coverage.order_notional_usd),
      sub: 'RouteShares × 价格回退链 × fx',
    },
    {
      label: '成交金额（USD）',
      value: formatMoney(coverage.fill_notional_usd),
      sub: 'fill × p_avg × fx',
    },
    {
      label: '组合完成率',
      value: formatPct(overview.completion),
      sub: 'Σfill / ΣRouteShares',
    },
    {
      label: '加权 arrival',
      value: formatSignedBps(overview.arrival_cost_bps),
      sub: '成交额加权 · 负 = 不利',
      tone: costToneClass(overview.arrival_cost_bps),
    },
    {
      label: '加权 IS',
      value: formatSignedBps(overview.wagner_is_bps),
      sub: '成交额加权 · 负 = 不利',
      tone: costToneClass(overview.wagner_is_bps),
    },
    {
      label: '机会成本（USD）',
      value: formatMoney(overview.opportunity_cost_usd),
      sub: '未成交部分 · 上游有符号原值',
    },
    {
      label: '零成交订单',
      value: formatInt(overview.zero_fill_orders),
      sub: `未成交 ${formatMoney(overview.unfilled_notional_usd)}`,
    },
    {
      label: '异常订单',
      value: formatInt(anomaly.orders_total),
      sub: `critical ${formatInt(anomaly.critical)} / warning ${formatInt(anomaly.warning)}`,
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">{card.label}</div>
            <div className={`mt-1 text-2xl font-semibold ${card.tone ?? ''}`}>{card.value}</div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">{card.sub}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

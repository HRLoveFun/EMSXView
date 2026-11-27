/** ReportView KPI cards (A14/229). Extracted verbatim from ReportView.tsx. */

import { Card, CardContent } from '@/components/ui/card';
import {
  appendNote,
  formatInt,
  formatMoney,
  formatNum,
  formatPct,
  formatRisk,
  formatShares,
  formatUnfilledSub,
  formatWeightCoverage,
  formatZeroFillSub,
} from '../../lib/report-format';
import type { TcaReportSummary } from '../../types';

/** 总成交金额卡片副标题：USD 换算成功率与被排除金额（与后端换算成功率口径一致） */
const fxCoverageSub = (kpi: NonNullable<TcaReportSummary['kpi']>): string => {
  const coverage = kpi.fx_coverage;
  if (coverage == null) return 'USD 换算 · 无 fx_rate 列';
  const pct = coverage * 100;
  const base = pct >= 99 ? 'USD 换算 · 全覆盖' : `USD 换算 · 覆盖率 ${pct.toFixed(0)}%`;
  const excluded = kpi.notional_usd_excluded;
  return excluded ? `${base}（本币排除 ${formatMoney(excluded)}）` : base;
};

/** KPI 卡片区（与 HTML 报告一致：基础 6 + 决策基准/风险/完成率/零成交 + 异常数） */
export const KpiCards = ({
  kpi,
  extra,
  anomaly,
  weightCoverage,
}: {
  kpi: TcaReportSummary['kpi'];
  extra?: TcaReportSummary['extra_kpis'];
  anomaly?: TcaReportSummary['anomaly'];
  weightCoverage?: TcaReportSummary['weight_coverage'];
}) => {
  if (!kpi) return null;
  const note = (metric: string): string =>
    formatWeightCoverage(weightCoverage?.metrics?.[metric]);
  const cards = [
    { label: 'Route 总数', value: kpi.route_count.toLocaleString(), sub: '' },
    { label: '总委托股数', value: formatShares(kpi.total_route_shares), sub: 'RouteShares 合计（委托股数，非成交股数）' },
    { label: '总成交金额（美元）', value: formatMoney(kpi.notional_usd), sub: fxCoverageSub(kpi) },
    {
      label: '加权 pnl_vwap',
      value: formatNum(kpi.weighted_pnl_vwap),
      sub: appendNote('成交额加权 · VWAP 基准', note('pnl_vwap')),
    },
    {
      label: '平均 par_rate',
      value: formatNum(kpi.avg_par_rate),
      sub: appendNote('成交额加权', note('par_rate')),
    },
    {
      label: '平均 RPM',
      value: formatNum(kpi.avg_rpm),
      sub: appendNote('成交额加权', note('RPM')),
    },
  ];
  if (extra) {
    cards.push(
      {
        label: '加权 arrival 成本',
        value: formatNum(extra.arrival_cost_bps),
        sub: appendNote('决策基准 · 成交额加权', note('arrival_cost_bps')),
      },
      {
        label: '加权 IS (bps)',
        value: formatNum(extra.wagner_is_bps),
        sub: appendNote('实现短缺 · 成交额加权', note('wagner_is_bps')),
      },
      {
        label: '成本风险 stddev/CVaR',
        value: formatRisk(extra.cost_stddev, extra.cost_cvar),
        sub: appendNote('尾部风险', note('cost_cvar')),
      },
      { label: '组合完成率', value: formatPct(extra.avg_fill), sub: 'Σfill / ΣRouteShares' },
      {
        label: '未成交金额缺口',
        value: formatMoney(extra.unfilled_notional_usd ?? null),
        sub: formatUnfilledSub(extra),
      },
      // 完全未执行（零成交）单独成卡：成本 KPI 与异常清单都看不到这批路由
      {
        label: '零成交路由',
        value: formatInt(extra.zero_fill_routes ?? 0),
        sub: formatZeroFillSub(extra),
      },
    );
  }
  if (anomaly != null) {
    cards.push(
      { label: '异常路由', value: anomaly.count.toLocaleString(), sub: '见下方明细' },
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">{card.label}</div>
            <div className="mt-1 text-2xl font-semibold">{card.value}</div>
            {card.sub && <div className="mt-0.5 text-[10px] text-muted-foreground">{card.sub}</div>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
};

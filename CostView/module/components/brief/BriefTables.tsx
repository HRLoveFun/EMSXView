import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { costToneClass, formatSignedBps } from '../../lib/cost-sign';
import { formatInt, formatMoney, formatPct, formatShares } from '../../lib/report-format';
import { SegmentedField } from '../SegmentedField';
import type {
  ExecutionBriefBlock,
  ExecutionBriefCompletionBucket,
  ExecutionBriefDataAvailability,
  ExecutionBriefDimensionRow,
  ExecutionBriefOrderRow,
  ExecutionBriefSides,
  ExecutionBriefTopOrders,
  TraderAnomalySummary,
} from '../../types';

const nbsp = '—';

/** 买卖拆分：委托 / 成交 / 完成 / 成本逐维对照。 */
export function SideSplitTable({
  sides,
  total,
}: {
  sides: ExecutionBriefSides;
  total: ExecutionBriefBlock;
}) {
  const rows: Array<{ key: string; label: string; block: ExecutionBriefBlock }> = [
    { key: 'buy', label: '买入', block: sides.buy },
    { key: 'sell', label: '卖出', block: sides.sell },
  ];
  if (sides.other.orders > 0) {
    rows.push({ key: 'other', label: '方向未知', block: sides.other });
  }
  rows.push({ key: 'total', label: '合计', block: total });
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">买卖拆分</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="text-muted-foreground">
              <th className="py-1 pr-2 text-left">方向</th>
              <th className="py-1 pr-2 text-right">订单</th>
              <th className="py-1 pr-2 text-right">委托股数</th>
              <th className="py-1 pr-2 text-right">成交股数</th>
              <th className="py-1 pr-2 text-right">委托金额</th>
              <th className="py-1 pr-2 text-right">成交金额</th>
              <th className="py-1 pr-2 text-right">完成率</th>
              <th className="py-1 pr-2 text-right">加权 arrival</th>
              <th className="py-1 text-right">机会成本</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-t border-muted">
                <td className="py-1 pr-2 text-left">{row.label}</td>
                <td className="py-1 pr-2 text-right">{formatInt(row.block.orders)}</td>
                <td className="py-1 pr-2 text-right">{formatShares(row.block.order_shares)}</td>
                <td className="py-1 pr-2 text-right">{formatShares(row.block.fill_shares)}</td>
                <td className="py-1 pr-2 text-right">{formatMoney(row.block.order_notional_usd)}</td>
                <td className="py-1 pr-2 text-right">{formatMoney(row.block.fill_notional_usd)}</td>
                <td className="py-1 pr-2 text-right">{formatPct(row.block.completion)}</td>
                <td className={`py-1 pr-2 text-right ${costToneClass(row.block.arrival_cost_bps)}`}>
                  {formatSignedBps(row.block.arrival_cost_bps)}
                </td>
                <td className="py-1 text-right">
                  {formatMoney(row.block.opportunity_cost_usd)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {sides.mixed_orders > 0 && (
          <div className="mt-2 text-[10px] text-muted-foreground">
            另有 {formatInt(sides.mixed_orders)} 笔多路由订单方向不一致，按成交股数最大路由归属。
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** 完成状态分桶：完全成交 / 部分成交 / 零成交 / 超成交（数据矛盾单列）。 */
export function CompletionBucketsTable({
  buckets,
}: {
  buckets: ExecutionBriefCompletionBucket[];
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">完成状态分桶</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="text-muted-foreground">
              <th className="py-1 pr-2 text-left">状态</th>
              <th className="py-1 pr-2 text-right">订单</th>
              <th className="py-1 pr-2 text-right">订单占比</th>
              <th className="py-1 pr-2 text-right">委托股数</th>
              <th className="py-1 pr-2 text-right">委托金额</th>
              <th className="py-1 pr-2 text-right">金额占比</th>
              <th className="py-1 text-right">完成率</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.key} className="border-t border-muted">
                <td className="py-1 pr-2 text-left">
                  <span
                    className={
                      bucket.key === 'zero'
                        ? 'text-destructive'
                        : bucket.key === 'overfill'
                          ? 'text-amber-600'
                          : ''
                    }
                  >
                    {bucket.label}
                  </span>
                </td>
                <td className="py-1 pr-2 text-right">{formatInt(bucket.orders)}</td>
                <td className="py-1 pr-2 text-right">{formatPct(bucket.share_of_orders)}</td>
                <td className="py-1 pr-2 text-right">{formatShares(bucket.order_shares)}</td>
                <td className="py-1 pr-2 text-right">{formatMoney(bucket.order_notional_usd)}</td>
                <td className="py-1 pr-2 text-right">{formatPct(bucket.share_of_notional)}</td>
                <td className="py-1 text-right">{formatPct(bucket.completion)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-2 text-[10px] text-muted-foreground">
          完成率 = Σfill / ΣRouteShares；零成交按委托金额计，超成交单独暴露数据矛盾。
        </div>
      </CardContent>
    </Card>
  );
}

/** 维度分布（策略 / 算法 / 券商 / 交易员）：订单数、金额、完成率、arrival。 */
export function DimensionMixTable({
  title,
  rows,
  emptyText = '本期无数据',
}: {
  title: string;
  rows: ExecutionBriefDimensionRow[];
  emptyText?: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        {rows.length === 0 ? (
          <div className="py-4 text-center text-xs text-muted-foreground">{emptyText}</div>
        ) : (
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="py-1 pr-2 text-left">名称</th>
                <th className="py-1 pr-2 text-right">订单</th>
                <th className="py-1 pr-2 text-right">占比</th>
                <th className="py-1 pr-2 text-right">委托金额</th>
                <th className="py-1 pr-2 text-right">完成率</th>
                <th className="py-1 text-right">加权 arrival</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 10).map((row) => (
                <tr key={row.key} className="border-t border-muted">
                  <td className="max-w-[14rem] truncate py-1 pr-2 text-left" title={row.label}>
                    {row.label}
                  </td>
                  <td className="py-1 pr-2 text-right">{formatInt(row.orders)}</td>
                  <td className="py-1 pr-2 text-right">{formatPct(row.share_of_orders)}</td>
                  <td className="py-1 pr-2 text-right">{formatMoney(row.order_notional_usd)}</td>
                  <td className="py-1 pr-2 text-right">{formatPct(row.completion)}</td>
                  <td className={`py-1 text-right ${costToneClass(row.arrival_cost_bps)}`}>
                    {formatSignedBps(row.arrival_cost_bps)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

type OrderMetric = keyof ExecutionBriefTopOrders;

const ORDER_METRIC_OPTIONS: Array<{ value: OrderMetric; label: string }> = [
  { value: 'by_arrival', label: '成本最不利' },
  { value: 'by_unfilled', label: '未成交金额' },
  { value: 'by_opportunity', label: '机会成本规模' },
];

function orderMetricValue(row: ExecutionBriefOrderRow, metric: OrderMetric): string {
  if (metric === 'by_arrival') return formatSignedBps(row.arrival_cost_bps);
  if (metric === 'by_unfilled') return formatMoney(row.unfilled_notional_usd);
  return formatMoney(row.opportunity_cost_usd);
}

/** 待处理订单 Top N：按成本 / 未成交 / 机会成本切换同一张表。 */
export function TopOrdersTable({
  topOrders,
  metric,
  onMetricChange,
}: {
  topOrders: ExecutionBriefTopOrders;
  metric: OrderMetric;
  onMetricChange: (value: OrderMetric) => void;
}) {
  const rows = topOrders[metric] ?? [];
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm">待处理订单</CardTitle>
        <SegmentedField
          label="排序口径"
          ariaLabel="待处理订单排序口径"
          options={ORDER_METRIC_OPTIONS}
          value={metric}
          onChange={(value) => onMetricChange(value as OrderMetric)}
        />
      </CardHeader>
      <CardContent className="overflow-x-auto">
        {rows.length === 0 ? (
          <div className="py-6 text-center text-xs text-muted-foreground">本期无命中订单</div>
        ) : (
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="py-1 pr-2 text-left">订单</th>
                <th className="py-1 pr-2 text-left">日期</th>
                <th className="py-1 pr-2 text-left">标的</th>
                <th className="py-1 pr-2 text-left">方向</th>
                <th className="py-1 pr-2 text-right">完成率</th>
                <th className="py-1 pr-2 text-right">委托金额</th>
                <th className="py-1 pr-2 text-right">未成交</th>
                <th className="py-1 pr-2 text-right">arrival</th>
                <th className="py-1 pr-2 text-right">IS</th>
                <th className="py-1 pr-2 text-left">交易员</th>
                <th className="py-1 text-right">{ORDER_METRIC_OPTIONS.find((o) => o.value === metric)?.label}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.order_id}-${row.order_as_of_date}`} className="border-t border-muted">
                  <td className="py-1 pr-2 font-mono text-left">{row.order_id}</td>
                  <td className="py-1 pr-2 text-left">{row.order_as_of_date}</td>
                  <td className="max-w-[12rem] truncate py-1 pr-2 text-left" title={row.ticker ?? ''}>
                    {row.ticker ?? nbsp}
                  </td>
                  <td className="py-1 pr-2 text-left">{row.side ?? nbsp}</td>
                  <td className="py-1 pr-2 text-right">{formatPct(row.completion)}</td>
                  <td className="py-1 pr-2 text-right">{formatMoney(row.order_notional_usd)}</td>
                  <td className="py-1 pr-2 text-right">{formatMoney(row.unfilled_notional_usd)}</td>
                  <td className={`py-1 pr-2 text-right ${costToneClass(row.arrival_cost_bps)}`}>
                    {formatSignedBps(row.arrival_cost_bps)}
                  </td>
                  <td className={`py-1 pr-2 text-right ${costToneClass(row.wagner_is_bps)}`}>
                    {formatSignedBps(row.wagner_is_bps)}
                  </td>
                  <td className="py-1 pr-2 text-left">{row.trader_name ?? nbsp}</td>
                  <td className="py-1 text-right font-medium">{orderMetricValue(row, metric)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

/** 异常摘要：按规则计数 + Top 订单（订单级口径，与交易员复盘台同源）。 */
export function AnomalyPanel({ anomaly }: { anomaly: TraderAnomalySummary }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">异常摘要</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="destructive">critical {formatInt(anomaly.critical)}</Badge>
          <Badge variant="secondary">warning {formatInt(anomaly.warning)}</Badge>
          <span className="text-muted-foreground">
            规则命中 {formatInt(anomaly.rule_orders)} · 质量标记 {formatInt(anomaly.quality_orders)}
          </span>
        </div>
        {anomaly.by_rule.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {anomaly.by_rule.map((rule) => (
              <Badge key={rule.key} variant={rule.critical > 0 ? 'destructive' : 'outline'}>
                {rule.label} {formatInt(rule.count)}
              </Badge>
            ))}
          </div>
        )}
        {anomaly.top_orders.length > 0 && (
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="py-1 pr-2 text-left">订单</th>
                <th className="py-1 pr-2 text-left">标的</th>
                <th className="py-1 pr-2 text-left">方向</th>
                <th className="py-1 pr-2 text-left">命中</th>
              </tr>
            </thead>
            <tbody>
              {anomaly.top_orders.map((order) => (
                <tr key={`${order.order_id}-${order.order_as_of_date}`} className="border-t border-muted">
                  <td className="py-1 pr-2 font-mono text-left">{order.order_id}</td>
                  <td className="py-1 pr-2 text-left">{order.ticker ?? nbsp}</td>
                  <td className="py-1 pr-2 text-left">{order.side ?? nbsp}</td>
                  <td className="py-1 pr-2 text-left">
                    {order.reasons.map((reason) => `${reason.label} ${reason.value}${reason.unit}`).join('；')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="text-[10px] text-muted-foreground">{anomaly.note}</div>
      </CardContent>
    </Card>
  );
}

/** 数据缺口：不可得项显式列出（不把「没数据」写成「没问题」）。 */
export function DataAvailabilityPanel({
  items,
  notes,
}: {
  items: ExecutionBriefDataAvailability[];
  notes: string[];
}) {
  const statusLabel: Record<string, string> = {
    unavailable: '未覆盖',
    partial: '部分覆盖',
    available: '已覆盖',
  };
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">数据缺口与口径</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-2 md:grid-cols-2">
          {items.map((item) => (
            <div key={item.key} className="rounded border border-muted px-3 py-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{item.label}</span>
                <Badge variant={item.status === 'unavailable' ? 'destructive' : 'secondary'}>
                  {statusLabel[item.status] ?? item.status}
                </Badge>
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground">{item.reason}</div>
            </div>
          ))}
        </div>
        <ul className="list-disc space-y-1 pl-5 text-[11px] text-muted-foreground">
          {notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      </CardContent>
    </Card>
  );
}

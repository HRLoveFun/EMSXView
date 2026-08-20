import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import type { TcaOrderAggregate } from '../types';
import type { TcaOrderReport } from '../services/api';

interface OrderAggregateTableProps {
  report: TcaOrderReport | null;
  error: string | null;
  isLoading: boolean;
}

function fmtBps(value: number | null | undefined): string {
  if (value == null) return '—';
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${value.toFixed(1)} bps`;
}

function fmtCurrency(value: number | null | undefined): string {
  if (value == null) return '—';
  const abs = Math.abs(value);
  const prefix = value > 0 ? '+' : value < 0 ? '-' : '';
  if (abs >= 1_000_000) return `${prefix}${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${prefix}${(abs / 1_000).toFixed(1)}K`;
  return `${prefix}${abs.toFixed(0)}`;
}

function fmtDurationSec(value: number | null | undefined): string {
  if (value == null) return '—';
  if (value < 60) return `${value.toFixed(0)}s`;
  const min = Math.floor(value / 60);
  const sec = Math.round(value % 60);
  return `${min}m${sec}s`;
}

/**
 * Order 级 TCA 聚合视图（003-tca-core-benchmarks Phase 2）。
 * 通过 POST /api/tca/analyze-orders 获取按订单聚合的指标，
 * 聚合规则见 specs/003-tca-core-benchmarks/plan.md §3.2。
 */
export function OrderAggregateTable({ report, error, isLoading }: OrderAggregateTableProps) {
  if (isLoading) {
    return (
      <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        Loading order aggregate view…
      </div>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Order aggregation failed</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!report || !report.orders.length) {
    return (
      <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        No orders matched the current filters.
      </div>
    );
  }

  const orders: TcaOrderAggregate[] = report.orders;

  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 text-sm text-muted-foreground">
        <span>
          {report.total_orders} order{report.total_orders !== 1 ? 's' : ''} aggregated · Generated {new Date(report.generated_at).toLocaleString()}
        </span>
        <span className="text-xs">货币成本为 SUM；bps 为成交额加权；风险取各 route 最大值（保守）</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1200px] text-sm">
          <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="sticky left-0 z-10 bg-muted/50 px-3 py-3 text-left font-medium">Order</th>
              <th className="px-3 py-3 text-left font-medium">Date</th>
              <th className="px-3 py-3 text-left font-medium">Symbol</th>
              <th className="px-3 py-3 text-left font-medium">Broker</th>
              <th className="px-3 py-3 text-left font-medium">Algo</th>
              <th className="px-3 py-3 text-right font-medium">Routes</th>
              <th className="px-3 py-3 text-right font-medium">Fill %</th>
              <th className="px-3 py-3 text-right font-medium">Arrival Cost</th>
              <th className="px-3 py-3 text-right font-medium">Close Cost</th>
              <th className="px-3 py-3 text-right font-medium">Wagner IS</th>
              <th className="px-3 py-3 text-right font-medium">Cost SD</th>
              <th className="px-3 py-3 text-right font-medium">Duration</th>
              <th className="px-3 py-3 text-right font-medium">Temp Imp 5m</th>
              <th className="px-3 py-3 text-right font-medium">Perm Imp</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => {
              const fillPct = order.fill != null && order.route_shares ? (order.fill / order.route_shares) * 100 : null;
              return (
                <tr key={`${order.order_id}/${order.order_as_of_date}`} className="border-t border-border/60 transition-colors hover:bg-muted/30">
                  <td className="sticky left-0 z-10 bg-card px-3 py-3 font-mono text-xs">{order.order_id}</td>
                  <td className="px-3 py-3 text-xs">{order.order_as_of_date}</td>
                  <td className="max-w-[180px] px-3 py-3 truncate" title={order.equ_ticker ?? ''}>{order.equ_ticker ?? '—'}</td>
                  <td className="px-3 py-3">{order.broker ?? '—'}</td>
                  <td className="px-3 py-3">{order.algo ?? '—'}</td>
                  <td className="px-3 py-3 text-right">{order.route_count}</td>
                  <td className="px-3 py-3 text-right">{fillPct != null ? `${fillPct.toFixed(1)}%` : '—'}</td>
                  <td className="px-3 py-3 text-right" title={order.p_arrival != null ? `P₀ ${order.p_arrival.toFixed(2)}` : undefined}>{fmtBps(order.arrival_cost_bps)}</td>
                  <td className="px-3 py-3 text-right" title={order.p_close != null ? `Pn ${order.p_close.toFixed(2)}` : undefined}>{fmtBps(order.close_cost_bps)}</td>
                  <td className="px-3 py-3 text-right" title={order.wagner_is_bps != null ? `${fmtBps(order.wagner_is_bps)} · $${fmtCurrency(order.wagner_is)}` : undefined}>{fmtCurrency(order.wagner_is)}</td>
                  <td className="px-3 py-3 text-right">{order.cost_stddev != null ? `${order.cost_stddev.toFixed(1)} bps` : '—'}</td>
                  <td className="px-3 py-3 text-right">{fmtDurationSec(order.order_duration_sec)}</td>
                  <td className="px-3 py-3 text-right">{fmtBps(order.temp_impact_5min_bps)}</td>
                  <td className="px-3 py-3 text-right">{fmtBps(order.perm_impact_bps)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

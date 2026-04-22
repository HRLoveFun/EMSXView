import { Fragment, useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { fmtNum } from '@/lib/format-utils';
import { getHighestOrderSeverity, getOrderAlertDetails, getSeverityText, getSeverityTone } from '../lib/thresholds';
import type { CostViewConfig, TcaOrderSummary, TcaReport } from '../types';
import { TcaRouteTable } from './TcaRouteTable';

interface TcaOrderTableProps {
  config: CostViewConfig;
  report: TcaReport;
  selectedOrderId: string | null;
  onPageChange: (offset: number) => void;
  onSelectOrder: (order: TcaOrderSummary | null) => void;
}

function fmtPercent(value: number | null | undefined, decimals = 1): string {
  if (value == null) return '—';
  return `${value.toFixed(decimals)}%`;
}

function fmtBps(value: number | null | undefined): string {
  if (value == null) return '—';
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${value.toFixed(1)} bps`;
}

export function TcaOrderTable({ config, report, selectedOrderId, onPageChange, onSelectOrder }: TcaOrderTableProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const totalPages = Math.ceil(report.total_orders / report.limit);
  const currentPage = Math.floor(report.offset / report.limit) + 1;

  function toggleExpand(orderId: string) {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      if (next.has(orderId)) {
        next.delete(orderId);
      } else {
        next.add(orderId);
      }
      return next;
    });
  }

  if (!report.orders.length) {
    return (
      <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        No orders matched the current filters.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1160px] text-sm">
          <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="w-12 px-3 py-3 text-left font-medium">Open</th>
              <th className="sticky left-0 z-10 bg-muted/50 px-3 py-3 text-left font-medium">Order</th>
              <th className="px-3 py-3 text-left font-medium">Date</th>
              <th className="px-3 py-3 text-left font-medium">Symbol</th>
              <th className="px-3 py-3 text-left font-medium">Alert</th>
              <th className="px-3 py-3 text-left font-medium">Data</th>
              <th className="px-3 py-3 text-right font-medium">Fill %</th>
              <th className="px-3 py-3 text-right font-medium">Exec</th>
              <th className="px-3 py-3 text-right font-medium">VWAP</th>
              <th className="px-3 py-3 text-right font-medium">Tracking Error</th>
              <th className="px-3 py-3 text-right font-medium">Vol % Interval</th>
              <th className="px-3 py-3 text-right font-medium">Vol % ADV20</th>
              <th className="px-3 py-3 text-right font-medium">Volatility</th>
              <th className="px-3 py-3 text-right font-medium">Price Move</th>
            </tr>
          </thead>
          <tbody>
            {report.orders.map((order) => {
              const isExpanded = expandedIds.has(order.order_id);
              const isSelected = selectedOrderId === order.order_id;
              const severity = getHighestOrderSeverity(order, config);
              const alerts = getOrderAlertDetails(order, config);
              return (
                <Fragment key={order.order_id}>
                  <tr
                    className={`border-t border-border/60 transition-colors hover:bg-muted/30 ${isSelected ? 'bg-primary/5' : ''}`}
                    onClick={() => onSelectOrder(isSelected ? null : order)}
                  >
                    <td className="px-3 py-3">
                      <button
                        type="button"
                        className="inline-flex h-7 w-7 items-center justify-center rounded border border-border hover:bg-muted"
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleExpand(order.order_id);
                        }}
                        aria-label={isExpanded ? 'Collapse routes' : 'Expand routes'}
                      >
                        {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>
                    </td>
                    <td className="sticky left-0 z-10 bg-card px-3 py-3 font-mono text-xs">
                      <div>{order.order_id}</div>
                      <div className="mt-1 text-[11px] text-muted-foreground">{order.side ?? '—'} · {order.algo ?? '—'}</div>
                    </td>
                    <td className="px-3 py-3 text-xs">{order.order_as_of_date}</td>
                    <td className="max-w-[180px] px-3 py-3 truncate" title={order.equ_ticker ?? ''}>{order.equ_ticker ?? '—'}</td>
                    <td className="px-3 py-3">
                      <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-medium ${getSeverityTone(severity)}`} title={alerts.map((alert) => `${alert.label}: ${alert.value}`).join('\n')}>
                        {severity === 'none' ? 'N/A' : getSeverityText(severity)}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      {order.data_quality_warning ? (
                        <Badge variant="outline" className="gap-1 border-amber-500/30 bg-amber-500/10 text-amber-700">
                          <AlertTriangle className="h-3 w-3" /> Partial
                        </Badge>
                      ) : (
                        <Badge variant="outline">OK</Badge>
                      )}
                    </td>
                    <td className="px-3 py-3 text-right">{fmtPercent(order.fill_pct)}</td>
                    <td className="px-3 py-3 text-right">{fmtNum(order.exec_price)}</td>
                    <td className="px-3 py-3 text-right">{fmtNum(order.interval_vwap)}</td>
                    <td className="px-3 py-3 text-right">
                      <span className={`inline-flex rounded border px-2 py-0.5 ${getSeverityTone(alerts.some((alert) => alert.key === 'tracking_error_bps') ? severity : 'none')}`}>
                        {fmtBps(order.tracking_error_bps)}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right">{fmtPercent(order.volume_pct_interval, 2)}</td>
                    <td className="px-3 py-3 text-right">{fmtPercent(order.volume_pct_adv20, 2)}</td>
                    <td className="px-3 py-3 text-right">{fmtPercent(order.intraday_volatility, 2)}</td>
                    <td className="px-3 py-3 text-right">{fmtPercent(order.price_movement_pct, 2)}</td>
                  </tr>
                  {isExpanded ? (
                    <tr className="bg-muted/20">
                      <td colSpan={14} className="p-0">
                        <TcaRouteTable routes={order.routes} trackingRule={config.rules.tracking_error_bps} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {totalPages > 1 ? (
        <div className="flex items-center justify-between border-t border-border px-4 py-3 text-xs text-muted-foreground">
          <span>
            {report.offset + 1}-{Math.min(report.offset + report.limit, report.total_orders)} of {report.total_orders} orders
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={currentPage === 1}
              onClick={() => onPageChange(Math.max(0, report.offset - report.limit))}
              className="rounded border border-border px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Prev
            </button>
            <span>{currentPage}/{totalPages}</span>
            <button
              type="button"
              disabled={currentPage === totalPages}
              onClick={() => onPageChange(report.offset + report.limit)}
              className="rounded border border-border px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
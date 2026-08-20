import { fmtNum } from '@shared/lib/format-utils';
import { getHighestOrderSeverity, getOrderAlertDetails, getSeverityText, getSeverityTone } from '../lib/thresholds';
import type { CostViewConfig, TcaReport, TcaRouteSummary } from '../types';

interface TcaOrderTableProps {
  config: CostViewConfig;
  report: TcaReport;
  selectedRouteKey: string | null;
  onPageChange: (offset: number) => void;
  onSelectRoute: (route: TcaRouteSummary | null) => void;
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

function routeKey(route: TcaRouteSummary): string {
  return `${route.order_id}/${route.route_id}/${route.order_as_of_date}`;
}

export function TcaOrderTable({ config, report, selectedRouteKey, onPageChange, onSelectRoute }: TcaOrderTableProps) {
  const totalPages = Math.ceil(report.total_orders / report.limit);
  const currentPage = Math.floor(report.offset / report.limit) + 1;

  if (!report.orders.length) {
    return (
      <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        No routes matched the current filters.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1640px] text-sm">
          <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="sticky left-0 z-10 bg-muted/50 px-3 py-3 text-left font-medium">Order · Route</th>
              <th className="px-3 py-3 text-left font-medium">Date</th>
              <th className="px-3 py-3 text-left font-medium">Symbol</th>
              <th className="px-3 py-3 text-left font-medium">Broker</th>
              <th className="px-3 py-3 text-left font-medium">Alert</th>
              <th className="px-3 py-3 text-right font-medium">Fill %</th>
              <th className="px-3 py-3 text-right font-medium">Pnl VWAP</th>
              <th className="px-3 py-3 text-right font-medium">Arrival Cost</th>
              <th className="px-3 py-3 text-right font-medium">Close Cost</th>
              <th className="px-3 py-3 text-right font-medium">Wagner IS</th>
              <th className="px-3 py-3 text-right font-medium">Cost SD</th>
              <th className="px-3 py-3 text-right font-medium">Duration</th>
              <th className="px-3 py-3 text-right font-medium">Temp Imp 5m</th>
              <th className="px-3 py-3 text-right font-medium">Perm Imp</th>
              <th className="px-3 py-3 text-right font-medium">Par Rate</th>
              <th className="px-3 py-3 text-right font-medium">Par Rate (Cont)</th>
              <th className="px-3 py-3 text-right font-medium">RPM</th>
              <th className="px-3 py-3 text-right font-medium">PWP 10</th>
              <th className="px-3 py-3 text-right font-medium">PWP 20</th>
            </tr>
          </thead>
          <tbody>
            {report.orders.map((route) => {
              const key = routeKey(route);
              const isSelected = selectedRouteKey === key;
              const severity = getHighestOrderSeverity(route, config);
              const alerts = getOrderAlertDetails(route, config);
              return (
                <tr
                  key={key}
                  className={`border-t border-border/60 transition-colors hover:bg-muted/30 ${isSelected ? 'bg-primary/5' : ''}`}
                  onClick={() => onSelectRoute(isSelected ? null : route)}
                >
                  <td className="sticky left-0 z-10 bg-card px-3 py-3 font-mono text-xs">
                    <div>{route.order_id}</div>
                    <div className="mt-1 text-[11px] text-muted-foreground">{route.route_id}</div>
                  </td>
                  <td className="px-3 py-3 text-xs">{route.order_as_of_date}</td>
                  <td className="max-w-[180px] px-3 py-3 truncate" title={route.equ_ticker ?? ''}>{route.equ_ticker ?? '—'}</td>
                  <td className="px-3 py-3">{route.broker ?? '—'}</td>
                  <td className="px-3 py-3">
                    <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-medium ${getSeverityTone(severity)}`} title={alerts.map((alert) => `${alert.label}: ${alert.value}`).join('\n')}>
                      {severity === 'none' ? 'N/A' : getSeverityText(severity)}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right">{fmtPercent(route.fill)}</td>
                  <td className="px-3 py-3 text-right">
                    <span className={`inline-flex rounded border px-2 py-0.5 ${getSeverityTone(alerts.some((alert) => alert.key === 'tracking_error_bps') ? severity : 'none')}`}>
                      {fmtBps(route.pnl_vwap)}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right" title={route.p_arrival != null ? `P₀ ${route.p_arrival.toFixed(2)}` : undefined}>{fmtBps(route.arrival_cost_bps)}</td>
                  <td className="px-3 py-3 text-right" title={route.p_close != null ? `Pn ${route.p_close.toFixed(2)}` : undefined}>{fmtBps(route.close_cost_bps)}</td>
                  <td className="px-3 py-3 text-right" title={route.wagner_is_bps != null ? `${fmtBps(route.wagner_is_bps)} · $${fmtCurrency(route.wagner_is)}` : undefined}>{fmtCurrency(route.wagner_is)}</td>
                  <td className="px-3 py-3 text-right">{route.cost_stddev != null ? `${route.cost_stddev.toFixed(1)} bps` : '—'}</td>
                  <td className="px-3 py-3 text-right">{fmtDurationSec(route.order_duration_sec)}</td>
                  <td className="px-3 py-3 text-right">{fmtBps(route.temp_impact_5min_bps)}</td>
                  <td className="px-3 py-3 text-right">{fmtBps(route.perm_impact_bps)}</td>
                  <td className="px-3 py-3 text-right">{fmtPercent((route.par_rate ?? 0) * 100, 2)}</td>
                  <td className="px-3 py-3 text-right">{fmtPercent((route.par_rate_continuous ?? 0) * 100, 2)}</td>
                  <td className="px-3 py-3 text-right">{fmtNum(route.rpm)}</td>
                  <td className="px-3 py-3 text-right">{route.pwp_10 ?? '—'}</td>
                  <td className="px-3 py-3 text-right">{route.pwp_20 ?? '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {totalPages > 1 ? (
        <div className="flex items-center justify-between border-t border-border px-4 py-3 text-xs text-muted-foreground">
          <span>
            {report.offset + 1}-{Math.min(report.offset + report.limit, report.total_orders)} of {report.total_orders} routes
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

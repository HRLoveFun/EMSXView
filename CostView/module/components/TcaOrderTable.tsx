import { fmtInt, fmtNum } from '@shared/lib/format-utils';
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
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  const prefix = value > 0 ? '+' : value < 0 ? '-' : '';
  if (abs >= 1_000_000) return `${prefix}${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${prefix}${(abs / 1_000).toFixed(1)}K`;
  return `${prefix}${abs.toFixed(0)}`;
}

/** 成交额是无符号量（非盈亏差额），不带 `+` 前缀。 */
function fmtNotional(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(abs / 1_000).toFixed(1)}K`;
  return `${abs.toFixed(0)}`;
}

function fmtDurationSec(value: number | null | undefined): string {
  if (value == null) return '—';
  if (value < 60) return `${value.toFixed(0)}s`;
  const min = Math.floor(value / 60);
  const sec = Math.round(value % 60);
  return `${min}m${sec}s`;
}

/**
 * 成交金额（本币）= fill × p_avg。
 *
 * F1（210 §0.2）：`tca_route_summary.Amount` 是**委托股数**，不是金额；
 * 金额列用 `fill × p_avg`（成交口径），委托股数单独成列。
 * 注意：零成交路由此处为 0；异常明细/HTML 报告为零成交路由另按
 * `RouteShares × p_avg` 计，两者口径不同。
 */
function tradedNotional(route: TcaRouteSummary): number | null {
  if (route.fill == null || route.p_avg == null) return null;
  return route.fill * route.p_avg;
}

function renderNotional(value: number | null, currency: string | null | undefined): string {
  if (value == null) return '—';
  // 保留货币代码原始大小写：GBp/ILs/ZAr 是最小计价单位（便士/阿高洛/分），
  // 大写后会被误标成 GBP/ILS/ZAR，而本币金额本身未做 ÷100 修正。
  const ccy = (currency ?? '').trim();
  return ccy ? `${ccy} ${fmtNotional(value)}` : fmtNotional(value);
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
        <table className="w-full min-w-[1730px] text-sm">
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
               <th className="px-3 py-3 text-right font-medium" title="tca_route_summary.Amount：委托股数，不是金额">委托股数</th>
               <th className="px-3 py-3 text-right font-medium" title="fill × p_avg（成交金额，非委托金额）">成交金额(本币)</th>
               <th className="px-3 py-3 text-right font-medium" title="后端按 fill×p_avg×汇率×小计价单位 计算后下发；当前未序列化，显示 —">成交金额(USD)</th>
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
                  <td className="px-3 py-3 text-right">{fmtPercent(route.fill != null && route.route_shares ? (route.fill / route.route_shares) * 100 : null)}</td>
                  <td className="px-3 py-3 text-right">
                    <span className={`inline-flex rounded border px-2 py-0.5 ${getSeverityTone(alerts.some((alert) => alert.key === 'pnl_vwap_bps') ? severity : 'none')}`}>
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
                  <td className="px-3 py-3 text-right" title="委托股数（Amount）">{fmtInt(route.amount)}</td>
                  <td className="px-3 py-3 text-right">{renderNotional(tradedNotional(route), route.currency)}</td>
                  {/* 后端未下发逐路由 USD 金额（fx_rate 未序列化）；不在前端重算换算，
                      待后端按 fill×p_avg×汇率×小计价单位 下发 notional_usd */}
                  <td className="px-3 py-3 text-right" title="后端未下发逐路由 USD 成交额">—</td>
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

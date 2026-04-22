import { evaluateThreshold, getSeverityText, getSeverityTone } from '../lib/thresholds';
import type { ThresholdRule, TcaRouteDetail } from '../types';
import { fmtNum } from '@/lib/format-utils';

interface TcaRouteTableProps {
  routes: TcaRouteDetail[];
  trackingRule: ThresholdRule;
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

export function TcaRouteTable({ routes, trackingRule }: TcaRouteTableProps) {
  if (!routes.length) {
    return <div className="px-4 py-3 text-xs italic text-muted-foreground">No route data available.</div>;
  }

  return (
    <div className="overflow-x-auto px-4 pb-3">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            <th className="py-2 pr-3 text-left font-medium">Route ID</th>
            <th className="py-2 pr-3 text-left font-medium">Broker</th>
            <th className="py-2 pr-3 text-left font-medium">Time</th>
            <th className="py-2 pr-3 text-right font-medium">Fill %</th>
            <th className="py-2 pr-3 text-right font-medium">Exec</th>
            <th className="py-2 pr-3 text-right font-medium">Benchmark</th>
            <th className="py-2 pr-3 text-right font-medium">Tracking Error</th>
            <th className="py-2 text-right font-medium">Vol % Interval</th>
          </tr>
        </thead>
        <tbody>
          {routes.map((route) => {
            const severity = evaluateThreshold(trackingRule, route.tracking_error_bps);
            return (
              <tr key={`${route.route_id}-${route.order_as_of_date}`} className="border-b border-border/40 last:border-b-0">
                <td className="py-2 pr-3 font-mono">{route.route_id}</td>
                <td className="py-2 pr-3">{route.broker ?? '—'}</td>
                <td className="py-2 pr-3">{route.start_time ?? '—'} - {route.end_time ?? '—'}</td>
                <td className="py-2 pr-3 text-right">{fmtPercent(route.fill_pct)}</td>
                <td className="py-2 pr-3 text-right">{fmtNum(route.exec_price)}</td>
                <td className="py-2 pr-3 text-right">{fmtNum(route.interval_vwap)}</td>
                <td className="py-2 pr-3 text-right">
                  <span className={`inline-flex rounded border px-2 py-0.5 ${getSeverityTone(severity)}`} title={getSeverityText(severity)}>
                    {fmtBps(route.tracking_error_bps)}
                  </span>
                </td>
                <td className="py-2 text-right">{fmtPercent(route.volume_pct_interval)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
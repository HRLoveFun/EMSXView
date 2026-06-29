/**
 * TcaRouteTable — route detail sub-table rendered inside a collapsed order row.
 */

import type { TcaRouteDetail } from '@/services/tca-api';

interface TcaRouteTableProps {
  routes: TcaRouteDetail[];
}

function fmt(v: number | null | undefined, decimals = 2): string {
  if (v == null) return '—';
  return v.toFixed(decimals);
}

function fmtBps(v: number | null | undefined): string {
  if (v == null) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${v.toFixed(1)} bps`;
}

export function TcaRouteTable({ routes }: TcaRouteTableProps) {
  if (routes.length === 0) {
    return (
      <div className="px-4 py-2 text-xs text-muted-foreground italic">
        No route data available
      </div>
    );
  }

  return (
    <div className="overflow-x-auto px-4 pb-2">
      <table className="w-full text-xs border-separate border-spacing-0">
        <thead>
          <tr className="text-muted-foreground">
            <th className="text-left py-1 pr-3 font-medium">Route ID</th>
            <th className="text-left py-1 pr-3 font-medium">Broker</th>
            <th className="text-left py-1 pr-3 font-medium">Side</th>
            <th className="text-right py-1 pr-3 font-medium">Fill %</th>
            <th className="text-right py-1 pr-3 font-medium">Exec Price</th>
            <th className="text-right py-1 pr-3 font-medium">Interval VWAP</th>
            <th className="text-right py-1 pr-3 font-medium">Tracking Error</th>
            <th className="text-right py-1 font-medium">Vol % Interval</th>
          </tr>
        </thead>
        <tbody>
          {routes.map((r) => {
            const teBps = r.tracking_error_bps ?? null;
            const teColor =
              teBps == null
                ? ''
                : teBps < -10
                ? 'text-green-500'
                : teBps > 10
                ? 'text-red-500'
                : 'text-foreground';
            return (
              <tr
                key={`${r.route_id}-${r.order_as_of_date}`}
                className="border-t border-border/40 hover:bg-muted/30"
              >
                <td className="py-1 pr-3 font-mono">{r.route_id}</td>
                <td className="py-1 pr-3">{r.broker ?? '—'}</td>
                <td className="py-1 pr-3">{r.side ?? '—'}</td>
                <td className="py-1 pr-3 text-right">{fmt(r.fill_pct, 1)}%</td>
                <td className="py-1 pr-3 text-right">{fmt(r.exec_price)}</td>
                <td className="py-1 pr-3 text-right">{fmt(r.interval_vwap)}</td>
                <td className={`py-1 pr-3 text-right ${teColor}`}>{fmtBps(r.tracking_error_bps)}</td>
                <td className="py-1 text-right">{fmt(r.volume_pct_interval, 1)}%</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

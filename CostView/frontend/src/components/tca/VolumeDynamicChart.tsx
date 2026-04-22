/**
 * VolumeDynamicChart — dual Y-axis chart for cumulative volume participation.
 *
 * Y1 (left):  Cumulative market volume % (0–100%)
 * Y2 (right): Cumulative fill volume % per route (0–100%)
 *
 * Uses recharts ComposedChart.
 */

import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { TcaRouteDetail } from '@/services/tca-api';

interface VolumeDynamicChartProps {
  routes: TcaRouteDetail[];
  orderId: string;
}

const ROUTE_COLORS = [
  '#3b82f6',
  '#f59e0b',
  '#10b981',
  '#f43f5e',
  '#8b5cf6',
];

interface ChartPoint {
  ts: string;
  cumMarketVolPct?: number | null;
  [fillKey: string]: number | null | string | undefined;
}

function buildChartData(routes: TcaRouteDetail[]): ChartPoint[] {
  const tsSet = new Set<string>();
  for (const r of routes) {
    for (const pt of r.time_series) tsSet.add(pt.ts);
  }
  const timestamps = Array.from(tsSet).sort();

  const fillVolMaps: Map<string, number | null>[] = routes.map((r) => {
    const m = new Map<string, number | null>();
    for (const pt of r.time_series) {
      if (pt.cum_volume_pct != null) m.set(pt.ts, pt.cum_volume_pct);
    }
    return m;
  });

  // Use first route for cumulative market volume %
  // cum_volume_pct in fill_bdib tracks fill volume pct of interval volume;
  // we approximate market participation via it.
  // We don't have raw cum market vol %, so use volume bar proportions as proxy.
  const primaryTsMap = new Map<string, TcaRouteDetail['time_series'][0]>();
  for (const pt of (routes[0]?.time_series ?? [])) {
    primaryTsMap.set(pt.ts, pt);
  }

  // Compute running cumulative volume for market
  let totalVol = 0;
  const totalByTs: Map<string, number> = new Map();
  for (const ts of timestamps) {
    const pt = primaryTsMap.get(ts);
    if (pt?.volume != null) totalVol += pt.volume;
    totalByTs.set(ts, totalVol);
  }
  const grandTotal = totalVol || 1;

  return timestamps.map((ts) => {
    const cumVol = totalByTs.get(ts) ?? 0;
    const point: ChartPoint = {
      ts,
      cumMarketVolPct: (cumVol / grandTotal) * 100,
    };
    for (let i = 0; i < routes.length; i++) {
      const key = `fill_vol_${routes[i].route_id}`;
      const v = fillVolMaps[i].get(ts);
      point[key] = v !== undefined ? v : null;
    }
    return point;
  });
}

function labelTs(ts: string): string {
  const parts = ts.split(' ');
  return parts[1]?.slice(0, 5) ?? ts;
}

export function VolumeDynamicChart({ routes, orderId }: VolumeDynamicChartProps) {
  if (!routes.length || !routes[0].time_series.length) {
    return (
      <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
        No time-series data available for {orderId}
      </div>
    );
  }

  const data = buildChartData(routes);

  return (
    <div className="w-full">
      <h4 className="text-xs font-semibold text-muted-foreground mb-2">
        Volume Participation — {orderId}
      </h4>
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 4, right: 40, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
          <XAxis
            dataKey="ts"
            tickFormatter={labelTs}
            tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
            minTickGap={40}
          />
          {/* Y1: cumulative market volume (%) */}
          <YAxis
            yAxisId="mkt"
            domain={[0, 100]}
            tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
            tickFormatter={(v: number) => `${v.toFixed(0)}%`}
            width={45}
          />
          {/* Y2: fill vol participation (%) per route */}
          <YAxis
            yAxisId="fill"
            orientation="right"
            domain={[0, 100]}
            tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
            tickFormatter={(v: number) => `${v.toFixed(0)}%`}
            width={45}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--card)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              fontSize: 11,
            }}
            formatter={(value: number | null, name: string) => {
              if (value == null) return ['—', name];
              return [`${value.toFixed(1)}%`, name];
            }}
            labelFormatter={labelTs}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />

          {/* Cumulative market volume */}
          <Line
            yAxisId="mkt"
            type="monotone"
            dataKey="cumMarketVolPct"
            name="Market Vol %"
            stroke="#94a3b8"
            strokeWidth={1.5}
            dot={false}
            connectNulls
          />

          {/* Fill volume per route */}
          {routes.map((r, idx) => (
            <Line
              key={r.route_id}
              yAxisId="fill"
              type="monotone"
              dataKey={`fill_vol_${r.route_id}`}
              name={`Fill Vol % (${r.route_id})`}
              stroke={ROUTE_COLORS[idx % ROUTE_COLORS.length]}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * PriceDynamicChart — dual Y-axis chart for a single route's price dynamics.
 *
 * Y1 (left):  BDIB interval close line + fill scatter (colored by route)
 * Y2 (right): Cumulative tracking error line
 *
 * Uses recharts ComposedChart.
 */

import {
  ComposedChart,
  Line,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { TcaRouteDetail, TcaTimeSeriesPoint } from '@/services/tca-api';

interface PriceDynamicChartProps {
  routes: TcaRouteDetail[];
  orderId: string;
}

// Palette for multiple routes
const ROUTE_COLORS = [
  '#3b82f6', // blue
  '#f59e0b', // amber
  '#10b981', // emerald
  '#f43f5e', // rose
  '#8b5cf6', // violet
];

interface ChartPoint {
  ts: string;
  close?: number | null;
  trackingError?: number | null;
  [fillKey: string]: number | null | string | undefined;
}

function buildChartData(routes: TcaRouteDetail[]): ChartPoint[] {
  // Merge all unique timestamps
  const tsSet = new Set<string>();
  for (const r of routes) {
    for (const pt of r.time_series) {
      tsSet.add(pt.ts);
    }
  }
  const timestamps = Array.from(tsSet).sort();

  // Build per-ts maps for each route's fill_px
  const fillMaps: Map<string, number | null>[] = routes.map((r) => {
    const m = new Map<string, number | null>();
    for (const pt of r.time_series) {
      if (pt.fill_px != null) m.set(pt.ts, pt.fill_px);
    }
    return m;
  });

  // Use first route for close + tracking error as reference
  const primaryRoute = routes[0];
  const closeMap = new Map<string, number | null>();
  const teMap = new Map<string, number | null>();
  for (const pt of primaryRoute?.time_series ?? []) {
    if (pt.close != null) closeMap.set(pt.ts, pt.close);
    if (pt.cum_tracking_error != null) teMap.set(pt.ts, pt.cum_tracking_error);
  }

  return timestamps.map((ts) => {
    const point: ChartPoint = {
      ts,
      close: closeMap.get(ts) ?? null,
      trackingError: teMap.get(ts) ?? null,
    };
    for (let i = 0; i < routes.length; i++) {
      const key = `fill_${routes[i].route_id}`;
      const v = fillMaps[i].get(ts);
      point[key] = v !== undefined ? v : null;
    }
    return point;
  });
}

function labelTs(ts: string): string {
  // ts format: "20260418 10:00:00" → "10:00"
  const parts = ts.split(' ');
  return parts[1]?.slice(0, 5) ?? ts;
}

export function PriceDynamicChart({ routes, orderId }: PriceDynamicChartProps) {
  if (!routes.length || !routes[0].time_series.length) {
    return (
      <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
        No time-series data available for {orderId}
      </div>
    );
  }

  const data = buildChartData(routes);

  // Compute Y1 domain (price axis) with 0.5% padding
  const prices: number[] = [];
  for (const d of data) {
    if (d.close != null) prices.push(d.close);
    for (const r of routes) {
      const v = d[`fill_${r.route_id}`];
      if (typeof v === 'number') prices.push(v);
    }
  }
  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);
  const pad = (maxP - minP) * 0.05 || 0.5;
  const priceDomain: [number, number] = [
    Math.floor((minP - pad) * 100) / 100,
    Math.ceil((maxP + pad) * 100) / 100,
  ];

  return (
    <div className="w-full">
      <h4 className="text-xs font-semibold text-muted-foreground mb-2">
        Price Dynamics — {orderId}
      </h4>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 4, right: 40, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
          <XAxis
            dataKey="ts"
            tickFormatter={labelTs}
            tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
            minTickGap={40}
          />
          {/* Y1: price */}
          <YAxis
            yAxisId="price"
            domain={priceDomain}
            tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
            tickFormatter={(v: number) => v.toFixed(2)}
            width={55}
          />
          {/* Y2: tracking error */}
          <YAxis
            yAxisId="te"
            orientation="right"
            tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
            tickFormatter={(v: number) => `${v.toFixed(0)} bps`}
            width={65}
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
              if (name === 'Tracking Error') return [`${value.toFixed(1)} bps`, name];
              return [value.toFixed(4), name];
            }}
            labelFormatter={labelTs}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />

          {/* BDIB close line */}
          <Line
            yAxisId="price"
            type="monotone"
            dataKey="close"
            name="BDIB Close"
            stroke="#94a3b8"
            strokeWidth={1.5}
            dot={false}
            connectNulls
          />

          {/* Fill scatter per route */}
          {routes.map((r, idx) => (
            <Scatter
              key={r.route_id}
              yAxisId="price"
              dataKey={`fill_${r.route_id}`}
              name={`Fill (${r.route_id})`}
              fill={ROUTE_COLORS[idx % ROUTE_COLORS.length]}
              opacity={0.8}
            />
          ))}

          {/* Tracking error line */}
          <Line
            yAxisId="te"
            type="monotone"
            dataKey="trackingError"
            name="Tracking Error"
            stroke="#f43f5e"
            strokeWidth={1.5}
            strokeDasharray="4 2"
            dot={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

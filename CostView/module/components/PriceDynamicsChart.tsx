import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { TcaRouteSummary } from '../types';

interface PriceDynamicsChartProps {
  orderId: string;
  routes: TcaRouteSummary[];
}

const ROUTE_COLORS = ['#2563eb', '#f59e0b', '#059669', '#e11d48', '#7c3aed'];

interface ChartPoint {
  ts: string;
  close?: number | null;
  trackingError?: number | null;
  [key: string]: number | string | null | undefined;
}

function buildChartData(routes: TcaRouteSummary[]): ChartPoint[] {
  const timestamps = Array.from(new Set(routes.flatMap((route) => route.time_series.map((point) => point.ts)))).sort();
  const primaryRoute = routes[0];
  const closeMap = new Map(primaryRoute?.time_series.map((point) => [point.ts, point.close]));
  const trackingMap = new Map(primaryRoute?.time_series.map((point) => [point.ts, point.cum_tracking_error]));

  return timestamps.map((ts) => {
    const row: ChartPoint = {
      ts,
      close: closeMap.get(ts) ?? null,
      trackingError: trackingMap.get(ts) ?? null,
    };

    routes.forEach((route) => {
      const point = route.time_series.find((value) => value.ts === ts);
      row[`fill_${route.route_id}`] = point?.fill_px ?? null;
    });

    return row;
  });
}

function formatTimestamp(ts: string): string {
  const parts = ts.split(' ');
  return parts[1]?.slice(0, 5) ?? ts;
}

export function PriceDynamicsChart({ orderId, routes }: PriceDynamicsChartProps) {
  if (!routes.length || !routes[0].time_series.length) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
        No price time-series data available for {orderId}.
      </div>
    );
  }

  const data = buildChartData(routes);
  const prices = data.flatMap((row) =>
    [row.close, ...routes.map((route) => row[`fill_${route.route_id}`])].filter(
      (value): value is number => typeof value === 'number',
    ),
  );
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const pad = (max - min) * 0.05 || 0.5;

  return (
    <div className="space-y-2">
      <div>
        <h4 className="text-sm font-semibold">Price Dynamics</h4>
        <p className="text-xs text-muted-foreground">Benchmark close, route fill points, and cumulative tracking error.</p>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 4, right: 40, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
          <XAxis dataKey="ts" tickFormatter={formatTimestamp} tick={{ fontSize: 10 }} minTickGap={40} />
          <YAxis
            yAxisId="price"
            domain={[Math.floor((min - pad) * 100) / 100, Math.ceil((max + pad) * 100) / 100]}
            tickFormatter={(value: number) => value.toFixed(2)}
            tick={{ fontSize: 10 }}
            width={55}
          />
          <YAxis
            yAxisId="te"
            orientation="right"
            tickFormatter={(value: number) => `${value.toFixed(0)} bps`}
            tick={{ fontSize: 10 }}
            width={65}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--card)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              fontSize: 11,
            }}
            formatter={(value, name) => {
              const numericValue = typeof value === 'number'
                ? value
                : Array.isArray(value)
                  ? Number(value[0])
                  : Number(value);
              if (!Number.isFinite(numericValue)) return ['—', String(name)];
              if (name === 'Tracking Error') return [`${numericValue.toFixed(1)} bps`, String(name)];
              return [numericValue.toFixed(4), String(name)];
            }}
            labelFormatter={formatTimestamp}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line yAxisId="price" type="monotone" dataKey="close" name="BDIB Close" stroke="#94a3b8" strokeWidth={1.5} dot={false} connectNulls />
          {routes.map((route, index) => (
            <Scatter
              key={route.route_id}
              yAxisId="price"
              dataKey={`fill_${route.route_id}`}
              name={`Fill (${route.route_id})`}
              fill={ROUTE_COLORS[index % ROUTE_COLORS.length]}
              opacity={0.8}
            />
          ))}
          <Line
            yAxisId="te"
            type="monotone"
            dataKey="trackingError"
            name="Tracking Error"
            stroke="#e11d48"
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
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { TcaRouteDetail } from '../types';

interface VolumeDynamicsChartProps {
  orderId: string;
  routes: TcaRouteDetail[];
}

const ROUTE_COLORS = ['#2563eb', '#f59e0b', '#059669', '#e11d48', '#7c3aed'];

interface ChartPoint {
  ts: string;
  cumMarketVolPct?: number | null;
  [key: string]: number | string | null | undefined;
}

function buildChartData(routes: TcaRouteDetail[]): ChartPoint[] {
  const timestamps = Array.from(new Set(routes.flatMap((route) => route.time_series.map((point) => point.ts)))).sort();
  const primaryTsMap = new Map(routes[0]?.time_series.map((point) => [point.ts, point]));

  let runningVolume = 0;
  const totals = new Map<string, number>();
  for (const ts of timestamps) {
    const point = primaryTsMap.get(ts);
    if (point?.volume != null) {
      runningVolume += point.volume;
    }
    totals.set(ts, runningVolume);
  }
  const grandTotal = runningVolume || 1;

  return timestamps.map((ts) => {
    const row: ChartPoint = {
      ts,
      cumMarketVolPct: ((totals.get(ts) ?? 0) / grandTotal) * 100,
    };

    routes.forEach((route) => {
      const point = route.time_series.find((value) => value.ts === ts);
      row[`fill_${route.route_id}`] = point?.cum_volume_pct ?? null;
    });

    return row;
  });
}

function formatTimestamp(ts: string): string {
  const parts = ts.split(' ');
  return parts[1]?.slice(0, 5) ?? ts;
}

export function VolumeDynamicsChart({ orderId, routes }: VolumeDynamicsChartProps) {
  if (!routes.length || !routes[0].time_series.length) {
    return (
      <div className="flex h-44 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
        No volume time-series data available for {orderId}.
      </div>
    );
  }

  const data = buildChartData(routes);

  return (
    <div className="space-y-2">
      <div>
        <h4 className="text-sm font-semibold">Volume Participation</h4>
        <p className="text-xs text-muted-foreground">Market cumulative volume versus route participation.</p>
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 4, right: 40, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
          <XAxis dataKey="ts" tickFormatter={formatTimestamp} tick={{ fontSize: 10 }} minTickGap={40} />
          <YAxis yAxisId="market" domain={[0, 100]} tickFormatter={(value: number) => `${value.toFixed(0)}%`} tick={{ fontSize: 10 }} width={45} />
          <YAxis yAxisId="fill" orientation="right" domain={[0, 100]} tickFormatter={(value: number) => `${value.toFixed(0)}%`} tick={{ fontSize: 10 }} width={45} />
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
              return [`${numericValue.toFixed(1)}%`, String(name)];
            }}
            labelFormatter={formatTimestamp}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line yAxisId="market" type="monotone" dataKey="cumMarketVolPct" name="Market Vol %" stroke="#94a3b8" strokeWidth={1.5} dot={false} connectNulls />
          {routes.map((route, index) => (
            <Line
              key={route.route_id}
              yAxisId="fill"
              type="monotone"
              dataKey={`fill_${route.route_id}`}
              name={`Fill Vol % (${route.route_id})`}
              stroke={ROUTE_COLORS[index % ROUTE_COLORS.length]}
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
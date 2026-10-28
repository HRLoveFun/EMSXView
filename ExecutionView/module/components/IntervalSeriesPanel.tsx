/**
 * 057 DL-30：执行区间量价面板（只读）。
 *
 * 价格线 + 累计量柱 + 三条参考线（区间 VWAP / 成交均价 / 到达价）。
 * 缺 bar 的桶保留 `gap`，价格线断开不插值；数据源 none 时显式提示。
 */

import { useMemo, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { IntervalSeriesPayload, Order } from '@execution/types';
import { apiService } from '@execution/services/execution-api';
import { resolveEquTicker, resolveInterval, toChartData } from '@execution/lib/interval-series';
import { useAsyncData } from '@shared/hooks/use-async-data';

const BUCKET_OPTIONS = [1, 5, 15, 30] as const;

interface IntervalSeriesPanelProps {
  order: Order;
  onClose: () => void;
}

function IntervalChart({ data, order }: { data: IntervalSeriesPayload; order: Order }) {
  const chartData = useMemo(() => toChartData(data.points), [data.points]);
  const referenceLines = [
    { value: data.interval_vwap, label: 'Interval VWAP', color: '#0ea5e9', position: 'insideTopRight' },
    { value: order.avgPrice, label: 'Avg Px', color: '#22c55e', position: 'insideBottomRight' },
    { value: order.arrivalPrice, label: 'Arrival', color: '#f59e0b', position: 'insideTopLeft' },
  ].filter((item) => item.value != null);

  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart data={chartData} margin={{ top: 8, right: 48, bottom: 4, left: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
        <XAxis dataKey="time" tick={{ fontSize: 10 }} minTickGap={32} />
        <YAxis yAxisId="price" tick={{ fontSize: 10 }} width={58} domain={['auto', 'auto']} />
        <YAxis
          yAxisId="volume"
          orientation="right"
          tick={{ fontSize: 10 }}
          width={58}
          tickFormatter={(value: number) => `${Math.round(value / 1_000_000)}M`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: 'var(--card)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            fontSize: 11,
          }}
          formatter={(value, name) => {
            const numeric = typeof value === 'number' ? value : Number(value);
            if (!Number.isFinite(numeric)) return ['gap', String(name)];
            return [
              name === 'Cum Volume' ? numeric.toLocaleString() : numeric.toFixed(4),
              String(name),
            ];
          }}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Bar
          yAxisId="volume"
          dataKey="cumVolume"
          name="Cum Volume"
          fill="#94a3b8"
          opacity={0.25}
          isAnimationActive={false}
        />
        <Line
          yAxisId="price"
          type="linear"
          dataKey="price"
          name="Price"
          stroke="#e11d48"
          strokeWidth={1.6}
          dot={false}
          connectNulls={false}
          isAnimationActive={false}
        />
        {referenceLines.map((line) => (
          <ReferenceLine
            key={line.label}
            yAxisId="price"
            y={line.value as number}
            stroke={line.color}
            strokeDasharray="4 2"
            label={{
              value: line.label,
              fontSize: 10,
              fill: line.color,
              position: line.position as 'insideTopRight' | 'insideBottomRight' | 'insideTopLeft',
            }}
          />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function SeriesSummary({ data, endAssumed }: { data: IntervalSeriesPayload; endAssumed: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
      <span className="rounded-full border border-border px-2 py-0.5">
        source: {data.source}
      </span>
      <span className="rounded-full border border-border px-2 py-0.5">
        {data.bar_count} bars
      </span>
      <span className={`rounded-full border px-2 py-0.5 ${data.gap_buckets > 0 ? 'border-amber-500/50 text-amber-600' : 'border-border'}`}>
        {data.gap_buckets} gap bucket(s)
      </span>
      <span className="rounded-full border border-border px-2 py-0.5">
        {data.start.slice(0, 5)}–{data.end.slice(0, 5)}
      </span>
      {endAssumed ? (
        <span className="rounded-full border border-amber-500/40 px-2 py-0.5 text-amber-600">
          终点按当前时刻/收盘近似
        </span>
      ) : null}
    </div>
  );
}

export function IntervalSeriesPanel({ order, onClose }: IntervalSeriesPanelProps) {
  const [bucketMinutes, setBucketMinutes] = useState<number>(5);
  const interval = useMemo(() => resolveInterval(order), [order]);
  const equTicker = useMemo(() => resolveEquTicker(order), [order]);
  const key = `${equTicker}|${interval.tradeDate}|${interval.start}|${interval.end}|${bucketMinutes}`;
  const { data, isLoading, error, reload } = useAsyncData(key, () =>
    apiService.getIntervalSeries({
      equ_ticker: equTicker,
      trade_date: interval.tradeDate,
      start: interval.start,
      end: interval.end,
      bucket_minutes: bucketMinutes,
    }),
  );

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">Execution Interval</span>
          <span className="font-mono text-xs text-muted-foreground">{order.symbol}</span>
          <span className="text-xs text-muted-foreground">{equTicker}</span>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[11px] text-muted-foreground" htmlFor="interval-bucket">
            Bucket
          </label>
          <select
            id="interval-bucket"
            className="h-7 rounded border border-border bg-background px-1 text-[11px]"
            value={bucketMinutes}
            onChange={(event) => setBucketMinutes(Number(event.target.value))}
          >
            {BUCKET_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option} min
              </option>
            ))}
          </select>
          <button
            type="button"
            className="h-7 rounded border border-border px-2 text-[11px] hover:bg-muted/40"
            onClick={reload}
          >
            Retry
          </button>
          <button
            type="button"
            className="h-7 rounded border border-border px-2 text-[11px] hover:bg-muted/40"
            onClick={onClose}
          >
            Close
          </button>
        </div>
      </div>

      <div className="space-y-3 px-3 py-3">
        {isLoading ? (
          <div className="rounded-lg border border-dashed border-border p-6 text-xs text-muted-foreground">
            Loading interval series…
          </div>
        ) : error ? (
          <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-xs text-red-700">
            {error.message}
          </div>
        ) : data ? (
          <>
            <SeriesSummary data={data} endAssumed={interval.endAssumed} />
            {data.source === 'none' ? (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-xs text-amber-700">
                区间内无可用 bar（{interval.tradeDate} {interval.start}–{interval.end}）。
                可能为非交易日、数据未入库，或该标的无 bar 供给。
              </div>
            ) : (
              <IntervalChart data={data} order={order} />
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}

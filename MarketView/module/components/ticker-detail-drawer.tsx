/**
 * 行详情抽屉（057 节点一）：三张图共用同一时间桶与同一 x 轴。
 *
 * 1) 价格—成交量分布：每 10 分钟一个时间桶，桶内按价格分档显示成交量，
 *    每个桶叠加 OHLC 点（高—低竖线 + 开/收短横）；右轴为相对前收的百分比变动。
 * 2) 累计成交量：当日 vs 前五个交易日均值，每桶一个数据点。
 * 3) 累计成交量占比：两条曲线各除以自身当日总量，压到 0–1，每桶一个数据点。
 *
 * 三图的绘图区宽度一致（左轴 64px、右轴 72px），刻度取同一组时间桶，
 * 因此纵向对齐。缺 bar 的时间桶显式标 gap，折线断开不插值。
 */

import { useEffect, useMemo, useState } from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { useAsyncData } from '@shared/hooks/use-async-data';

import { fetchTickerDetail } from '../services/api';
import { fmtCompact, fmtNumber } from '../marketview-utils';
import type { TickerDetailPayload } from '../types';

interface TickerDetailDrawerProps {
  ticker: string;
  tradeDate?: string | null;
  onClose: () => void;
}

// 三图共用布局：左轴 64px + 右轴 72px，绘图区宽度一致
const AXIS_LEFT = 64;
const AXIS_RIGHT = 72;
const HEATMAP_HEIGHT = 240;
const HEATMAP_TOP = 14;
const HEATMAP_BOTTOM = 24;
const CHART_HEIGHT = 190;

/** 容器宽度（像素）：热力图用与 recharts 相同的像素坐标，保证三图 x 轴等长。 */
function useMeasuredWidth() {
  // 用 callback ref：节点只在数据加载后才挂载，一次性 effect 会错过它
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    if (!element) return;
    const update = (): void => setWidth(element.clientWidth);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);

  return { ref: setElement, width };
}

/** x 轴刻度：取约 8 个等距时间桶，三图共用。 */
function useTickIndexes(count: number): number[] {
  return useMemo(() => {
    if (count <= 0) return [];
    const step = Math.max(1, Math.ceil(count / 8));
    const indexes: number[] = [];
    for (let index = 0; index < count; index += step) indexes.push(index);
    const last = count - 1;
    if (indexes[indexes.length - 1] !== last) indexes.push(last);
    return indexes;
  }, [count]);
}

/** 价格—成交量分布（SVG 热力格）+ 逐桶 OHLC 点 + 右轴百分比。 */
function PriceVolumeHeatmap({
  detail,
  width,
  tickIndexes,
}: {
  detail: TickerDetailPayload;
  width: number;
  tickIndexes: number[];
}) {
  const { buckets, cells } = detail;
  const binCount = detail.price_bin_count;
  const low = detail.price_low;
  const high = detail.price_high;
  const plotWidth = Math.max(width - AXIS_LEFT - AXIS_RIGHT, 1);
  const plotHeight = HEATMAP_HEIGHT - HEATMAP_TOP - HEATMAP_BOTTOM;

  const maxVolume = useMemo(() => cells.reduce((max, cell) => Math.max(max, cell.volume), 0), [cells]);
  const cellsByBucket = useMemo(() => {
    const map = new Map<number, typeof cells>();
    for (const cell of cells) {
      const list = map.get(cell.bucket) ?? [];
      list.push(cell);
      map.set(cell.bucket, list);
    }
    return map;
  }, [cells]);

  if (!buckets.length || !binCount || low == null || high == null || high <= low || width <= 0) {
    return (
      <div className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
        No usable bars for this session; the price distribution cannot be drawn.
      </div>
    );
  }

  const cellWidth = plotWidth / buckets.length;
  const cellHeight = plotHeight / binCount;
  const priceToY = (price: number): number =>
    HEATMAP_TOP + plotHeight * (1 - (price - low) / (high - low));
  const prevClose = detail.prev_close;
  const pctToLabel = (price: number): string =>
    prevClose && prevClose > 0 ? `${(((price / prevClose) - 1) * 100).toFixed(2)}%` : '';

  return (
    <svg
      width={width}
      height={HEATMAP_HEIGHT}
      viewBox={`0 0 ${width} ${HEATMAP_HEIGHT}`}
      className="block"
      role="img"
      aria-label={`${detail.equ_ticker} price–volume distribution`}
    >
      <rect
        x={AXIS_LEFT}
        y={HEATMAP_TOP}
        width={plotWidth}
        height={plotHeight}
        fill="var(--muted, #f8fafc)"
        opacity={0.35}
      />
      {buckets.map((bucket, index) => {
        const x = AXIS_LEFT + index * cellWidth;
        if (bucket.gap) {
          return (
            <rect
              key={`gap-${bucket.index}`}
              x={x}
              y={HEATMAP_TOP}
              width={cellWidth}
              height={plotHeight}
              fill="#f59e0b"
              opacity={0.12}
            >
              <title>{`${bucket.label} missing bars`}</title>
            </rect>
          );
        }
        return (cellsByBucket.get(index) ?? []).map((cell) => {
          const intensity = maxVolume > 0 ? Math.sqrt(cell.volume / maxVolume) : 0;
          const y = HEATMAP_TOP + plotHeight - (cell.price_bin + 1) * cellHeight;
          return (
            <rect
              key={`c-${cell.bucket}-${cell.price_bin}`}
              x={x}
              y={y}
              width={Math.max(cellWidth - 0.6, 0.6)}
              height={Math.max(cellHeight - 0.6, 0.6)}
              fill="#2563eb"
              opacity={0.08 + 0.82 * intensity}
            >
              <title>{`${buckets[index]?.label ?? ''} · price bin ${cell.price_bin + 1} · ${fmtCompact(cell.volume)}`}</title>
            </rect>
          );
        });
      })}

      {/* 逐桶 OHLC 点：高低竖线 + 开（左）/收（右）短横 */}
      {buckets.map((bucket, index) => {
        if (bucket.gap || bucket.high == null || bucket.low == null) return null;
        const center = AXIS_LEFT + index * cellWidth + cellWidth / 2;
        const yHigh = priceToY(bucket.high);
        const yLow = priceToY(bucket.low);
        const tick = Math.min(cellWidth * 0.28, 4);
        const rising = bucket.close != null && bucket.open != null && bucket.close >= bucket.open;
        const color = rising ? '#0f766e' : '#b91c1c';
        return (
          <g key={`ohlc-${bucket.index}`}>
            <line x1={center} x2={center} y1={yHigh} y2={yLow} stroke={color} strokeWidth={1} opacity={0.9} />
            {bucket.open != null ? (
              <line
                x1={center - tick}
                x2={center}
                y1={priceToY(bucket.open)}
                y2={priceToY(bucket.open)}
                stroke={color}
                strokeWidth={1}
              />
            ) : null}
            {bucket.close != null ? (
              <line
                x1={center}
                x2={center + tick}
                y1={priceToY(bucket.close)}
                y2={priceToY(bucket.close)}
                stroke={color}
                strokeWidth={1}
              />
            ) : null}
            <title>
              {`${bucket.label} O ${fmtNumber(bucket.open, 2)} H ${fmtNumber(bucket.high, 2)} L ${fmtNumber(bucket.low, 2)} C ${fmtNumber(bucket.close, 2)}`}
            </title>
          </g>
        );
      })}

      {/* 左轴价格 / 右轴相对前收百分比（同一组刻度，三图等宽） */}
      {Array.from({ length: 5 }, (_, index) => {
        const price = low + ((high - low) * index) / 4;
        const y = priceToY(price);
        return (
          <g key={`ticks-${index}`}>
            <text x={AXIS_LEFT - 6} y={y + 3} fontSize={9} textAnchor="end" fill="currentColor" opacity={0.65}>
              {fmtNumber(price, 2)}
            </text>
            {prevClose ? (
              <text
                x={AXIS_LEFT + plotWidth + 6}
                y={y + 3}
                fontSize={9}
                fill="currentColor"
                opacity={0.65}
              >
                {pctToLabel(price)}
              </text>
            ) : null}
          </g>
        );
      })}

      {tickIndexes.map((index) => {
        const bucket = buckets[index];
        if (!bucket) return null;
        return (
          <text
            key={`x-${bucket.index}`}
            x={AXIS_LEFT + index * cellWidth + cellWidth / 2}
            y={HEATMAP_TOP + plotHeight + 12}
            fontSize={9}
            textAnchor="middle"
            fill="currentColor"
            opacity={0.65}
          >
            {bucket.label}
          </text>
        );
      })}
    </svg>
  );
}

/** 累计量 / 累计量占比：两张折线图共用一份对齐数据（每桶一个点）。 */
function cumulativeSeries(detail: TickerDetailPayload) {
  return detail.buckets.map((bucket, index) => {
    const prev = detail.prev_buckets[index];
    return {
      label: bucket.label,
      todayVolume: bucket.cumulative_volume,
      prevVolume: prev?.cumulative_volume ?? null,
      todayPct: bucket.cumulative_pct != null ? bucket.cumulative_pct * 100 : null,
      prevPct: prev?.cumulative_pct != null ? prev.cumulative_pct * 100 : null,
      gap: bucket.gap,
    };
  });
}

function CumulativeChart({
  data,
  dataKeyToday,
  dataKeyPrev,
  domain,
  tickFormatter,
  caption,
  tickLabels,
}: {
  data: ReturnType<typeof cumulativeSeries>;
  dataKeyToday: string;
  dataKeyPrev: string;
  domain: [number, number | 'auto'];
  tickFormatter: (value: number) => string;
  caption: string;
  tickLabels: string[];
}) {
  return (
    <div className="rounded-xl border border-border/70 bg-background/60 p-3">
      <p className="mb-1 text-xs text-muted-foreground">{caption}</p>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <LineChart data={data} margin={{ top: 6, right: 0, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
          <XAxis dataKey="label" ticks={tickLabels} interval={0} tick={{ fontSize: 10 }} />
          <YAxis
            yAxisId="left"
            tick={{ fontSize: 10 }}
            width={AXIS_LEFT}
            domain={domain}
            tickFormatter={tickFormatter}
          />
          {/* 右侧留白与量价图的右轴等宽，保证三图绘图区一致 */}
          <YAxis yAxisId="right" orientation="right" width={AXIS_RIGHT} tick={false} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--card)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              fontSize: 11,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey={dataKeyToday}
            name="Today"
            stroke="#2563eb"
            strokeWidth={2}
            dot={{ r: 2 }}
            activeDot={{ r: 3 }}
            isAnimationActive={false}
            connectNulls={false}
          />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey={dataKeyPrev}
            name="Prev 5D avg"
            stroke="#94a3b8"
            strokeWidth={2}
            strokeDasharray="5 4"
            dot={{ r: 2 }}
            activeDot={{ r: 3 }}
            isAnimationActive={false}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function TickerDetailDrawer({ ticker, tradeDate, onClose }: TickerDetailDrawerProps) {
  const key = `${ticker}|${tradeDate ?? ''}`;
  const { data, isLoading, error, reload } = useAsyncData(key, () =>
    fetchTickerDetail(ticker, tradeDate ?? undefined),
  );
  const series = useMemo(() => (data ? cumulativeSeries(data) : []), [data]);
  const tickIndexes = useTickIndexes(data?.buckets.length ?? 0);
  const tickLabels = useMemo(
    () => tickIndexes.map((index) => data?.buckets[index]?.label ?? '').filter(Boolean),
    [tickIndexes, data],
  );
  const { ref: chartAreaRef, width: chartWidth } = useMeasuredWidth();

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/30"
      role="dialog"
      aria-modal="true"
      // 点击抽屉外空白处关闭（面板内部点击不触发）
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="h-full w-full max-w-[1180px] overflow-y-auto bg-card p-5 shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/70 pb-3">
          <div>
            <p className="text-lg font-semibold text-foreground">{ticker}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {data
                ? `${data.trade_date ?? '—'} · ${data.buckets.length} buckets × ${data.bucket_minutes}min · ${data.prev_days} prev day(s) · gaps ${data.gaps.length} · source ${data.source}`
                : 'Ticker detail: price × volume / cumulative volume / cumulative share'}
            </p>
            {data?.session_open ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                Session {data.session_open}–{data.session_close} ({data.market_code})
              </p>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded-full border border-border px-3 py-1 text-xs transition hover:text-foreground"
              onClick={() => reload()}
            >
              Refresh
            </button>
            <button
              type="button"
              className="rounded-full border border-border px-3 py-1 text-xs transition hover:text-foreground"
              onClick={onClose}
            >
              Close
            </button>
          </div>
        </div>

        {isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading ticker detail…</div>
        ) : error ? (
          <div className="p-6 text-sm text-red-700">{error.message}</div>
        ) : data ? (
          <div className="mt-4 space-y-4">
            <div className="rounded-xl border border-border/70 bg-background/60 p-3">
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>
                  Price × volume distribution (one {data.bucket_minutes}-min bucket; darker = more volume; wick +
                  open/close ticks = bucket OHLC)
                </span>
                <span>
                  Total {fmtCompact(data.total_volume)} · Prev5D avg {fmtCompact(data.prev_avg_volume)} · Prev close{' '}
                  {fmtNumber(data.prev_close, 2)}
                </span>
              </div>
              {/* 与 recharts 容器同宽（同 padding/边框的卡片内容区），保证三图 x 轴等长 */}
              <div ref={chartAreaRef}>
                <PriceVolumeHeatmap detail={data} width={chartWidth} tickIndexes={tickIndexes} />
              </div>
            </div>

            <CumulativeChart
              data={series}
              dataKeyToday="todayVolume"
              dataKeyPrev="prevVolume"
              domain={[0, 'auto']}
              tickFormatter={(value: number) => fmtCompact(value)}
              caption={`Cumulative volume: today vs prior ${data.prev_days}-session average (one point per bucket; missing bars break the line, no interpolation)`}
              tickLabels={tickLabels}
            />

            <CumulativeChart
              data={series}
              dataKeyToday="todayPct"
              dataKeyPrev="prevPct"
              domain={[0, 100]}
              tickFormatter={(value: number) => `${value.toFixed(0)}%`}
              caption="Cumulative volume share: each series divided by its own day total (0–100%, one point per bucket)"
              tickLabels={tickLabels}
            />

            {data.gaps.length ? (
              <p className="text-xs text-amber-600">Bucket gaps: {data.gaps.join(', ')}</p>
            ) : null}
          </div>
        ) : (
          <div className="p-6 text-sm text-muted-foreground">No detail data.</div>
        )}
      </div>
    </div>
  );
}

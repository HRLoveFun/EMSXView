/**
 * 行详情抽屉（057 节点一）：三张图共用同一时间桶序列。
 *
 * 1) 价格—成交量分布：每 10 分钟一个时间桶，桶内按价格分档显示成交量（OHLC 标注）；
 * 2) 累计成交量：当日 vs 前五个交易日均值；
 * 3) 累计成交量占比：两条曲线各除以自身当日总量，压到 0–1。
 *
 * 数据全部来自后端 `raw_bdib` 10 秒 bar 聚合；缺 bar 的时间桶显式标 gap，
 * 折线断开不插值。价格分布是 bar 级近似（把 bar 的量按 high–low 与分档的重叠比例摊开）。
 */

import { useMemo } from 'react';
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

const CHART_HEIGHT = 190;
const HEATMAP_WIDTH = 920;
const PAD = { left: 64, right: 72, top: 14, bottom: 26 };

const OHLC_COLORS: Record<string, string> = {
  open: '#0ea5e9',
  high: '#22c55e',
  low: '#ef4444',
  close: '#a855f7',
};

/** 价格—成交量分布（SVG 热力格）：x = 时间桶，y = 价格分档，色深 = 该格成交量。 */
function PriceVolumeHeatmap({ detail }: { detail: TickerDetailPayload }) {
  const { buckets, cells } = detail;
  const binCount = detail.price_bin_count;
  const low = detail.price_low;
  const high = detail.price_high;
  const plotWidth = HEATMAP_WIDTH - PAD.left - PAD.right;
  const plotHeight = 240 - PAD.top - PAD.bottom;

  const maxVolume = useMemo(
    () => cells.reduce((max, cell) => Math.max(max, cell.volume), 0),
    [cells],
  );
  const cellsByBucket = useMemo(() => {
    const map = new Map<number, typeof cells>();
    for (const cell of cells) {
      const list = map.get(cell.bucket) ?? [];
      list.push(cell);
      map.set(cell.bucket, list);
    }
    return map;
  }, [cells]);

  if (!buckets.length || !binCount || low == null || high == null || high <= low) {
    return (
      <div className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
        该标的当日没有可用的 bar，价格分布无法绘制。
      </div>
    );
  }

  const cellWidth = plotWidth / buckets.length;
  const cellHeight = plotHeight / binCount;
  const priceToY = (price: number): number =>
    PAD.top + plotHeight * (1 - (price - low) / (high - low));
  const tickStep = Math.max(1, Math.ceil(buckets.length / 9));

  return (
    <svg
      viewBox={`0 0 ${HEATMAP_WIDTH} 240`}
      className="h-[240px] w-full"
      role="img"
      aria-label={`${detail.equ_ticker} 价格—成交量分布`}
    >
      <rect
        x={PAD.left}
        y={PAD.top}
        width={plotWidth}
        height={plotHeight}
        fill="var(--muted, #f8fafc)"
        opacity={0.35}
      />
      {buckets.map((bucket, index) => {
        const x = PAD.left + index * cellWidth;
        if (bucket.gap) {
          return (
            <rect
              key={`gap-${bucket.index}`}
              x={x}
              y={PAD.top}
              width={cellWidth}
              height={plotHeight}
              fill="#f59e0b"
              opacity={0.12}
            >
              <title>{`${bucket.label} 缺 bar`}</title>
            </rect>
          );
        }
        return (cellsByBucket.get(index) ?? []).map((cell) => {
          const intensity = maxVolume > 0 ? Math.sqrt(cell.volume / maxVolume) : 0;
          const y = PAD.top + plotHeight - (cell.price_bin + 1) * cellHeight;
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
              <title>{`${buckets[index]?.label ?? ''} · 价格分档 ${cell.price_bin + 1} · ${fmtCompact(cell.volume)}`}</title>
            </rect>
          );
        });
      })}

      {(['open', 'high', 'low', 'close'] as const).map((key) => {
        const value = detail.ohlc[key];
        if (value == null) return null;
        const y = priceToY(value);
        return (
          <g key={key}>
            <line
              x1={PAD.left}
              x2={PAD.left + plotWidth}
              y1={y}
              y2={y}
              stroke={OHLC_COLORS[key]}
              strokeDasharray="4 3"
              strokeWidth={1}
              opacity={0.85}
            />
            <text
              x={PAD.left + plotWidth + 4}
              y={y + 3}
              fontSize={9}
              fill={OHLC_COLORS[key]}
            >
              {`${key.toUpperCase()} ${fmtNumber(value, 2)}`}
            </text>
          </g>
        );
      })}

      {buckets.map((bucket, index) =>
        index % tickStep === 0 ? (
          <text
            key={`x-${bucket.index}`}
            x={PAD.left + index * cellWidth + cellWidth / 2}
            y={PAD.top + plotHeight + 12}
            fontSize={9}
            textAnchor="middle"
            fill="currentColor"
            opacity={0.65}
          >
            {bucket.label}
          </text>
        ) : null,
      )}

      {Array.from({ length: 5 }, (_, index) => {
        const price = low + ((high - low) * index) / 4;
        return (
          <text
            key={`y-${index}`}
            x={PAD.left - 6}
            y={priceToY(price) + 3}
            fontSize={9}
            textAnchor="end"
            fill="currentColor"
            opacity={0.65}
          >
            {fmtNumber(price, 2)}
          </text>
        );
      })}
    </svg>
  );
}

/** 累计量 / 累计量占比：两张折线图共用一份对齐数据。 */
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
}: {
  data: ReturnType<typeof cumulativeSeries>;
  dataKeyToday: string;
  dataKeyPrev: string;
  domain: [number, number | 'auto'];
  tickFormatter: (value: number) => string;
  caption: string;
}) {
  return (
    <div className="rounded-xl border border-border/70 bg-background/60 p-3">
      <p className="mb-1 text-xs text-muted-foreground">{caption}</p>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <LineChart data={data} margin={{ top: 6, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} minTickGap={28} />
          <YAxis
            tick={{ fontSize: 10 }}
            width={58}
            domain={domain}
            tickFormatter={tickFormatter}
          />
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
            type="monotone"
            dataKey={dataKeyToday}
            name="Today"
            stroke="#2563eb"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey={dataKeyPrev}
            name="Prev 5D avg"
            stroke="#94a3b8"
            strokeWidth={2}
            strokeDasharray="5 4"
            dot={false}
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

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" role="dialog" aria-modal="true">
      <div className="h-full w-full max-w-[1180px] overflow-y-auto bg-card p-5 shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/70 pb-3">
          <div>
            <p className="text-lg font-semibold text-foreground">{ticker}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {data
                ? `${data.trade_date ?? '—'} · ${data.buckets.length} buckets × ${data.bucket_minutes}min · ${data.prev_days} prev day(s) · gaps ${data.gaps.length} · source ${data.source}`
                : '行详情：价格—成交量分布 / 累计量 / 累计量占比'}
            </p>
            {data?.session_open ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                会话 {data.session_open}–{data.session_close}（{data.market_code}）· {data.session_note}
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
                  价格—成交量分布（每 {data.bucket_minutes} 分钟一个时间桶；颜色越深量越大；虚线为 O/H/L/C）
                </span>
                <span>
                  Total {fmtCompact(data.total_volume)} · Prev5D avg {fmtCompact(data.prev_avg_volume)}
                </span>
              </div>
              <PriceVolumeHeatmap detail={data} />
            </div>

            <CumulativeChart
              data={series}
              dataKeyToday="todayVolume"
              dataKeyPrev="prevVolume"
              domain={[0, 'auto']}
              tickFormatter={(value: number) => fmtCompact(value)}
              caption={`累计成交量：当日 vs 前 ${data.prev_days} 个交易日均值（缺 bar 的桶断开，不插值）`}
            />

            <CumulativeChart
              data={series}
              dataKeyToday="todayPct"
              dataKeyPrev="prevPct"
              domain={[0, 100]}
              tickFormatter={(value: number) => `${value.toFixed(0)}%`}
              caption="累计成交量占比：各曲线除以自身当日总量（0–100%）"
            />

            {data.gaps.length ? (
              <p className="text-xs text-amber-600">缺口时间桶：{data.gaps.join(', ')}</p>
            ) : null}
          </div>
        ) : (
          <div className="p-6 text-sm text-muted-foreground">No detail data.</div>
        )}
      </div>
    </div>
  );
}

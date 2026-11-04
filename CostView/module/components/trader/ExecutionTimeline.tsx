import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { formatPct, formatShares } from '../../lib/report-format';
import {
  buildBubbles,
  buildBucketPoints,
  bubbleRadius,
  firstFillSec,
  isValidBenchmark,
  type BubblePoint,
} from '../../lib/timeline-points';
import type { TraderOrderDetail, TraderTimelineBenchmarks } from '../../types';

/** 基准线样式（只画有效正价；颜色与图例文字一一对应） */
const BENCHMARKS: Array<{
  key: keyof TraderTimelineBenchmarks;
  label: string;
  color: string;
}> = [
  { key: 'p_decision', label: '决策价', color: '#7c3aed' },
  { key: 'p_arrival', label: '首笔前 bar', color: '#2563eb' },
  { key: 'p_avg', label: '成交均价', color: '#059669' },
  { key: 'p_close', label: '收盘价', color: '#f59e0b' },
  { key: 'limit_price', label: '限价', color: '#e11d48' },
];

interface ExecutionTimelineProps {
  detail: TraderOrderDetail;
}

/** 成交气泡渲染（recharts 自定义 shape：半径随股数变化） */
function BubbleShape(props: {
  cx?: number;
  cy?: number;
  payload?: BubblePoint;
  maxShares: number;
}) {
  const { cx, cy, payload, maxShares } = props;
  if (cx == null || cy == null || !payload) return <g />;
  return (
    <circle
      cx={cx}
      cy={cy}
      r={bubbleRadius(payload.shares, maxShares)}
      fill="rgba(37,99,235,0.30)"
      stroke="#2563eb"
      strokeWidth={1}
    />
  );
}

/**
 * 订单执行时间线（210 §4.2）：上=价格 + 成交气泡 + 基准线，下=成交柱 + 累计完成率 + 逐桶参与率。
 *
 * 口径要点（与后端 `trader_metrics.bucket_fills` 一致，前端不重算）：
 * - 桶从**首笔成交**起按固定宽度切，空桶补 0（速度/加速度据此计算）；
 * - `participation_status = unavailable`（收盘竞价 / 无 bar）**不画 0%**，线在此断开；
 * - 基准价只画有效正价：上游用 `limit_price = 0` 表示「无限价」，0 会把价格轴拉到 0；
 * - 下方面板左轴为股数、右轴为百分比（两个物理量，轴标签各自标注），
 *   速度 / 加速度不画右轴线（噪声大），改由 tooltip 与完成轨迹摘要披露。
 */
export function ExecutionTimeline({ detail }: ExecutionTimelineProps) {
  const timeline = detail.timeline;
  const points = buildBucketPoints(timeline);
  const origin = firstFillSec(detail.fills);
  const bubbles = buildBubbles(detail.fills, origin);
  const maxShares = bubbles.reduce((max, item) => Math.max(max, item.shares), 0);
  const unavailable = timeline.buckets.filter(
    (bucket) => bucket.participation_status !== 'ok',
  ).length;
  const fillTotal = timeline.buckets.reduce((sum, bucket) => sum + bucket.fill, 0);
  const benchmarks = BENCHMARKS.filter((item) => isValidBenchmark(timeline.benchmarks[item.key]));
  const check = timeline.par_rate_check;
  const bucketMin = timeline.bucket_min || 5;

  /** 分钟数 → 该分钟所在桶的起始标签（两图横轴文案一致） */
  const labelAt = (minutes: number) => {
    const index = Math.min(
      Math.max(Math.floor(Number(minutes) / bucketMin), 0),
      points.length - 1,
    );
    return points[index]?.label ?? '';
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>桶宽 {bucketMin} 分钟 · 共 {points.length} 桶</span>
        <span>成交合计 {formatShares(fillTotal)} 股</span>
        {timeline.auto_widened && (
          <span className="text-amber-500">桶数超 240，已自动加宽（口径已披露）</span>
        )}
        {unavailable > 0 && (
          <span title="收盘竞价无 bar / BDIB 缺该桶行情">
            {unavailable} 桶无行情（不画 0% 参与率）
          </span>
        )}
        {check?.note && (
          <span className="text-amber-500" title="逐桶参与率与该路由 par_rate 的比值越界">
            {check.note}（比值 {check.ratio.toFixed(3)}）
          </span>
        )}
      </div>

      {benchmarks.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {benchmarks.map((item) => (
            <span key={item.key} style={{ color: item.color }}>
              {item.label} {timeline.benchmarks[item.key]?.toFixed(2)}
            </span>
          ))}
        </div>
      )}

      <div>
        <div className="mb-1 text-xs font-medium">价格与成交（气泡 = 成交股数）</div>
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={points} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
            <XAxis
              dataKey="idx"
              type="number"
              domain={['dataMin', 'dataMax']}
              tickFormatter={(value: number) => labelAt(value)}
            />
            <YAxis domain={['auto', 'auto']} width={64} tick={{ fontSize: 11 }} />
            <Tooltip
              formatter={(value: number | string, name: string) =>
                name === '成交' ? formatShares(Number(value)) : Number(value).toFixed(2)}
              labelFormatter={(value: number | string) => labelAt(Number(value))}
            />
            <Line
              type="monotone"
              dataKey="vwap"
              name="桶 VWAP"
              stroke="#0f766e"
              dot={false}
              connectNulls={false}
            />
            <Scatter
              data={bubbles}
              dataKey="price"
              name="成交"
              shape={(props: unknown) => (
                <BubbleShape {...(props as object)} maxShares={maxShares} />
              )}
            />
            {benchmarks.map((item) => (
              <ReferenceLine
                key={item.key}
                y={timeline.benchmarks[item.key] as number}
                stroke={item.color}
                strokeDasharray="4 4"
                label={{ value: item.label, fontSize: 10, fill: item.color }}
              />
            ))}
            <Legend />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div>
        <div className="mb-1 text-xs font-medium">
          成交柱（股数，左轴）与累计完成率 / 逐桶参与率（%，右轴）
        </div>
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={points} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis yAxisId="shares" width={64} tick={{ fontSize: 11 }} />
            <YAxis yAxisId="pct" orientation="right" unit="%" width={52} tick={{ fontSize: 11 }} />
            <Tooltip
              formatter={(value: number | string, name: string) =>
                name === '成交股数'
                  ? formatShares(Number(value))
                  : formatPct(Number(value) / 100)}
            />
            <Legend />
            <Bar yAxisId="shares" dataKey="fill" name="成交股数" fill="#93c5fd" />
            <Line
              yAxisId="pct"
              type="monotone"
              dataKey="cumPct"
              name="累计完成率"
              stroke="#1d4ed8"
              dot={false}
              connectNulls={false}
            />
            <Line
              yAxisId="pct"
              type="monotone"
              dataKey="parPct"
              name="逐桶参与率"
              stroke="#f97316"
              dot={false}
              connectNulls={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
        <p className="mt-1 text-[11px] text-muted-foreground">
          参与率分母为同桶 raw_bdib 市场量（多路由按订单窗口**并集**，不把各路由 par_rate
          相加）；无 bar 桶（收盘竞价 / 行情缺失）在线上断开，不按 0% 绘制。
        </p>
      </div>
    </div>
  );
}

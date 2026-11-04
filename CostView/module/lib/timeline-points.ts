import type { TraderDetailFill, TraderTimeline } from '../types';

/** 单桶图表行（上下两图共用同一批桶，横轴分别为分钟数与桶标签） */
export interface BucketPoint {
  idx: number;
  label: string;
  vwap: number | null;
  fill: number;
  fillCount: number;
  /** 累计完成率（%，不可得 → null，禁止按 0 画） */
  cumPct: number | null;
  /** 逐桶市场参与率（%）；unavailable 桶为 null（不画 0%） */
  parPct: number | null;
  speed: number;
  accel: number | null;
}

/** 成交气泡（大小 = 该笔成交股数） */
export interface BubblePoint {
  idx: number;
  price: number;
  shares: number;
  routeId: string;
}

/** 首笔成交的当日秒（时间线横轴原点；无逐笔 → null） */
export function firstFillSec(fills: TraderDetailFill[]): number | null {
  const values = fills
    .map((fill) => fill.ts_sec)
    .filter((value): value is number => value != null && Number.isFinite(value));
  return values.length ? Math.min(...values) : null;
}

/**
 * 桶行 → 图表点（210 §4.2）。
 *
 * - 横轴 ``idx`` 以「首笔成交后第几分钟」表示（桶序 × 桶宽，后端已按首笔切桶）；
 * - 累计完成率与参与率一律换算成百分数给图表，``null`` 保持 ``null``（线断开），
 *   从而「无 bar 桶不画 0%」的规则在数据层就成立，不依赖渲染层判断。
 */
export function buildBucketPoints(timeline: TraderTimeline): BucketPoint[] {
  const bucketMin = timeline.bucket_min || 5;
  return timeline.buckets.map((bucket, index) => ({
    idx: index * bucketMin,
    label: bucket.start ?? String(index + 1),
    vwap: bucket.vwap,
    fill: bucket.fill,
    fillCount: bucket.fill_count,
    cumPct: bucket.cum_completion == null ? null : bucket.cum_completion * 100,
    parPct: bucket.participation_status === 'ok' && bucket.participation != null
      ? bucket.participation * 100
      : null,
    speed: bucket.speed_shares_per_min,
    accel: bucket.accel,
  }));
}

/** 逐笔 → 气泡点（价格缺失 / 时间缺失的成交不画；横轴与桶行同为「分钟」） */
export function buildBubbles(
  fills: TraderDetailFill[], origin: number | null,
): BubblePoint[] {
  if (origin == null) return [];
  return fills
    .filter((fill) => fill.ts_sec != null && fill.price != null)
    .map((fill) => ({
      idx: ((fill.ts_sec as number) - origin) / 60,
      price: fill.price as number,
      shares: fill.shares ?? 0,
      routeId: fill.route_id ?? '—',
    }));
}

/** 气泡半径：按股数开方缩放，限定 3–12px（极端大单不撑破面板） */
export function bubbleRadius(shares: number, maxShares: number): number {
  if (!Number.isFinite(shares) || shares <= 0 || maxShares <= 0) return 3;
  return 3 + Math.sqrt(shares / maxShares) * 9;
}

/** 有效基准价：上游用 0 表示「无此价格/无限价」，0 与负数一律不画（会把价格轴拉到 0） */
export function isValidBenchmark(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value) && value > 0;
}

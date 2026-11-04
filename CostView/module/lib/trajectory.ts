import type { TraderOrderDetail } from '../types';

/** 完成轨迹摘要（全部字段 null = 不可得，禁止按 0 解读） */
export interface TrajectoryStats {
  spanSec: number | null;
  speedPerMin: number | null;
  /** 非零桶速度的变异系数（population std / mean；有效桶不足 2 → null） */
  speedCv: number | null;
  maxSpeedRatio: number | null;
  zeroBuckets: number;
  /** |accel| 最大的 2 个桶（§4.4：只标注时刻，不画连续柱状加速度） */
  accelTop: Array<{ label: string; accel: number }>;
}

/** 非零桶速度的均值（无正速度 → null） */
function meanSpeed(speeds: number[]): number | null {
  return speeds.length ? speeds.reduce((sum, value) => sum + value, 0) / speeds.length : null;
}

/** 总体标准差（与后端 statistics.pstdev 同定义，不用样本标准差） */
function populationStd(values: number[], mean: number): number {
  const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length;
  return Math.sqrt(variance);
}

/**
 * 完成轨迹统计（210 §4.4）。
 *
 * 跨度与平均速度直接取后端 `order.fill_span_sec` / `order.speed_shares_per_min`
 * （`fill_count<2` 时后端已返回 null）；零成交桶与加速度由同一批桶行计算。
 *
 * `speedCv` 目前只在后端 `trader_metrics.fill_span_stats` 内部算出、未随详情
 * payload 下发，故此处按**同一公式**（非零桶、总体标准差）复算并在 UI 标注口径 ——
 * 一旦 API 暴露该字段，应改为直接消费，勿长期保留两份实现。
 */
export function computeTrajectory(detail: TraderOrderDetail): TrajectoryStats {
  const buckets = detail.timeline.buckets;
  const speeds = buckets
    .map((bucket) => bucket.speed_shares_per_min)
    .filter((value) => Number.isFinite(value) && value > 0);
  const mean = meanSpeed(speeds);
  const accelTop = buckets
    .filter((bucket) => bucket.accel != null)
    .map((bucket) => ({ label: bucket.start ?? '—', accel: bucket.accel as number }))
    .sort((left, right) => Math.abs(right.accel) - Math.abs(left.accel))
    .slice(0, 2);
  return {
    spanSec: detail.order.fill_span_sec,
    speedPerMin: detail.order.speed_shares_per_min,
    speedCv: mean && speeds.length > 1 ? populationStd(speeds, mean) / mean : null,
    maxSpeedRatio: mean && speeds.length ? Math.max(...speeds) / mean : null,
    zeroBuckets: buckets.filter((bucket) => bucket.speed_shares_per_min === 0).length,
    accelTop,
  };
}

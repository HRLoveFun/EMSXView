import { describe, expect, it } from 'vitest';
import { computeTrajectory } from './trajectory';
import type { TraderOrderDetail, TraderTimelineBucket } from '../types';

/** 造一个最小详情：只需 order 的速度字段与 timeline.buckets */
function buildDetail(
  buckets: TraderTimelineBucket[],
  fillSpanSec: number | null = 300,
  speed: number | null = 2200,
): TraderOrderDetail {
  return {
    order: { fill_span_sec: fillSpanSec, speed_shares_per_min: speed },
    timeline: { bucket_min: 5, auto_widened: false, buckets, benchmarks: {}, par_rate_check: null },
  } as unknown as TraderOrderDetail;
}

function bucket(
  start: string, speed: number, accel: number | null,
): TraderTimelineBucket {
  return {
    start, end: start, fill: speed * 5, fill_count: 1, vwap: 100,
    market_volume: null, participation: null, participation_status: 'unavailable',
    cum_completion: null, speed_shares_per_min: speed, accel,
  };
}

describe('computeTrajectory（210 §4.4 完成轨迹口径）', () => {
  it('非零桶口径算 CV 与峰值比；零成交桶单独计数，不进 CV 分母', () => {
    const stats = computeTrajectory(buildDetail([
      bucket('09:35', 800, null),
      bucket('09:40', 400, -400),
      bucket('09:45', 0, -400),
    ]));

    // 非零桶 [800, 400]：mean 600、pstdev 200 → CV = 1/3
    expect(stats.speedCv).toBeCloseTo(1 / 3, 6);
    expect(stats.maxSpeedRatio).toBeCloseTo(800 / 600, 6);
    expect(stats.zeroBuckets).toBe(1);
    // 加速度按 |accel| 降序取 2 个（并列时保持桶序）
    expect(stats.accelTop.map((item) => item.label)).toEqual(['09:40', '09:45']);
  });

  it('单笔成交（后端已置 null）：跨度与速度原样为 null，不按 0 计算', () => {
    const stats = computeTrajectory(
      buildDetail([bucket('09:35', 1400, null)], null, null),
    );

    expect(stats.spanSec).toBeNull();
    expect(stats.speedPerMin).toBeNull();
    expect(stats.speedCv).toBeNull();     // 仅 1 个非零桶 → 无法算变异
    expect(stats.maxSpeedRatio).toBeCloseTo(1, 6);
    expect(stats.accelTop).toEqual([]);
  });

  it('全部桶无成交：CV / 峰值比均为 null（不做除零）', () => {
    const stats = computeTrajectory(buildDetail([
      bucket('09:35', 0, null),
      bucket('09:40', 0, 0),
    ]));

    expect(stats.speedCv).toBeNull();
    expect(stats.maxSpeedRatio).toBeNull();
    expect(stats.zeroBuckets).toBe(2);
  });
});

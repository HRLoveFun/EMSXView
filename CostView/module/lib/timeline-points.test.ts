import { describe, expect, it } from 'vitest';
import {
  buildBubbles,
  buildBucketPoints,
  bubbleRadius,
  firstFillSec,
  isValidBenchmark,
} from './timeline-points';
import type { TraderDetailFill, TraderTimeline } from '../types';

const TIMELINE: TraderTimeline = {
  bucket_min: 5,
  auto_widened: false,
  buckets: [
    {
      start: '09:35', end: '09:40', fill: 4000, fill_count: 2, vwap: 101.2,
      market_volume: 20000, participation: 0.2, participation_status: 'ok',
      cum_completion: 0.3333, speed_shares_per_min: 800, accel: null,
    },
    {
      start: '09:40', end: '09:45', fill: 3000, fill_count: 1, vwap: 101.25,
      market_volume: null, participation: null, participation_status: 'unavailable',
      cum_completion: 0.5833, speed_shares_per_min: 600, accel: -200,
    },
  ],
  benchmarks: { p_decision: 101, p_arrival: 100.9, p_avg: null, p_close: 101.5, limit_price: 0 },
  par_rate_check: null,
};

function fill(tsSec: number, price: number | null, shares: number | null): TraderDetailFill {
  return {
    route_id: 'R1', fill_id: `F${tsSec}`, ts_local: null, ts_sec: tsSec,
    route_as_of_sec: tsSec - 10, price, shares, is_closing_auction: false,
    liquidity_raw: null, liquidity_class: 'unknown',
  };
}

describe('timeline-points（210 §4.2 时间线数据整形）', () => {
  it('桶行换算：横轴按桶宽推进，百分比 ×100，unavailable 桶参与率为 null', () => {
    const points = buildBucketPoints(TIMELINE);

    expect(points.map((point) => point.idx)).toEqual([0, 5]);
    expect(points[0].cumPct).toBeCloseTo(33.33, 2);
    expect(points[0].parPct).toBeCloseTo(20, 6);
    // 收盘竞价 / 无 bar 桶：null（不画 0%），且累计完成率仍给出
    expect(points[1].parPct).toBeNull();
    expect(points[1].cumPct).toBeCloseTo(58.33, 2);
  });

  it('完成率不可得时保持 null（不按 0 画）', () => {
    const points = buildBucketPoints({
      ...TIMELINE,
      buckets: [{ ...TIMELINE.buckets[0], cum_completion: null }],
    });

    expect(points[0].cumPct).toBeNull();
  });

  it('气泡：以首笔为原点换算分钟，缺价格的成交不画', () => {
    const fills = [
      fill(35100, 101.2, 4000),
      fill(35400, 101.25, 3000),
      fill(35700, null, 100),
    ];
    const origin = firstFillSec(fills);

    expect(origin).toBe(35100);
    const bubbles = buildBubbles(fills, origin);
    expect(bubbles).toHaveLength(2);
    expect(bubbles[0].idx).toBe(0);
    expect(bubbles[1].idx).toBeCloseTo(5, 6);
    expect(bubbles[0].routeId).toBe('R1');
  });

  it('无逐笔（origin=null）时不产生气泡', () => {
    expect(buildBubbles([fill(35100, 101.2, 100)], null)).toEqual([]);
    expect(firstFillSec([])).toBeNull();
  });

  it('气泡半径随股数开方缩放并封顶 12px，异常输入退化为 3px', () => {
    expect(bubbleRadius(100, 100)).toBeCloseTo(12, 6);
    expect(bubbleRadius(25, 100)).toBeLessThan(8);
    expect(bubbleRadius(0, 100)).toBe(3);
    expect(bubbleRadius(10, 0)).toBe(3);
  });

  it('基准价有效性：0（无限价哨兵）与负数、null 一律不画', () => {
    expect(isValidBenchmark(101.5)).toBe(true);
    expect(isValidBenchmark(0)).toBe(false);
    expect(isValidBenchmark(-1)).toBe(false);
    expect(isValidBenchmark(null)).toBe(false);
  });
});

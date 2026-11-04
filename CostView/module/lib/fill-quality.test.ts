import { describe, expect, it } from 'vitest';
import {
  passiveCostDiff,
  sweepHint,
  unknownShareLevel,
  SWEEP_MIN_FILLS,
} from './fill-quality';

describe('fill-quality（210 §4.5 / §4.6 面板口径）', () => {
  it('扫单线索：≥6 笔且 Top3≥70% 且最大单笔≥30% 才提示', () => {
    expect(sweepHint(6, 0.7, 0.3).triggered).toBe(true);
    expect(sweepHint(6, 0.7, 0.3).text).toContain('集中扫单');
    // 任一条不满足 → 不提示
    expect(sweepHint(6, 0.69, 0.3).triggered).toBe(false);
    expect(sweepHint(6, 0.7, 0.29).triggered).toBe(false);
  });

  it('样本不足（<6 笔）与不可得一律不提示（避免噪声结论）', () => {
    expect(sweepHint(SWEEP_MIN_FILLS - 1, 1.0, 1.0).triggered).toBe(false);
    expect(sweepHint(SWEEP_MIN_FILLS - 1, 1.0, 1.0).text).toBe('');
    expect(sweepHint(null, 0.9, 0.5).triggered).toBe(false);
    expect(sweepHint(8, null, 0.5).triggered).toBe(false);
    expect(sweepHint(8, 0.9, null).triggered).toBe(false);
  });

  it('被动/主动成本差：passive − aggressive，任一缺失则 null', () => {
    expect(passiveCostDiff(-3, -5)).toBe(2);       // 被动更优（adverse 更小）
    expect(passiveCostDiff(-5, -3)).toBe(-2);      // 负 = 被动更差
    expect(passiveCostDiff(null, -3)).toBeNull();
    expect(passiveCostDiff(-3, null)).toBeNull();
  });

  it('未知占比分级：≤10% 无标，10–25% info，>25% warn', () => {
    expect(unknownShareLevel(null)).toBe('none');
    expect(unknownShareLevel(0.1)).toBe('none');
    expect(unknownShareLevel(0.1001)).toBe('info');
    expect(unknownShareLevel(0.25)).toBe('info');
    expect(unknownShareLevel(0.26)).toBe('warn');
  });
});

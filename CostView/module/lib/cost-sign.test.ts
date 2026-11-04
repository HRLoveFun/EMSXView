import { describe, expect, it } from 'vitest';
import {
  adverseBps,
  costToneClass,
  formatSignedBps,
  isAdverse,
  segmentWidthPct,
} from './cost-sign';

/** 成本符号方向的单测锁：负=不利，正=有利，0/null 中性（§3.8） */
describe('cost-sign（成本符号统一口径）', () => {
  it('adverseBps：负值翻正，正值翻负，null 原样', () => {
    expect(adverseBps(-4.2)).toBe(4.2);
    expect(adverseBps(3)).toBe(-3);
    expect(adverseBps(0)).toBe(0);
    expect(adverseBps(null)).toBeNull();
  });

  it('isAdverse：仅负值算不利（0 与 null 不算）', () => {
    expect(isAdverse(-0.01)).toBe(true);
    expect(isAdverse(0)).toBe(false);
    expect(isAdverse(null)).toBe(false);
  });

  it('costToneClass：不利红、有利绿、中性灰', () => {
    expect(costToneClass(-1)).toContain('rose');
    expect(costToneClass(1)).toContain('emerald');
    expect(costToneClass(0)).toContain('muted');
    expect(costToneClass(null)).toContain('muted');
  });

  it('formatSignedBps：正数带 + 号，不可得显示破折号', () => {
    expect(formatSignedBps(-4.2)).toBe('-4.20 bps');
    expect(formatSignedBps(6)).toBe('+6.00 bps');
    expect(formatSignedBps(null)).toBe('—');
  });

  it('segmentWidthPct：有利分量不参与相抵，只按不利幅度占比', () => {
    // 不利 10 + 不利 30 → 归一后 25% / 75%；有利 5 不占宽度
    expect(segmentWidthPct(-10, 40)).toBe(25);
    expect(segmentWidthPct(-30, 40)).toBe(75);
    expect(segmentWidthPct(5, 40)).toBe(0);
    expect(segmentWidthPct(-10, 0)).toBe(0);
  });
});

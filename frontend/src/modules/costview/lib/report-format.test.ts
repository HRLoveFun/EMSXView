import { describe, expect, it } from 'vitest';
import {
  appendNote,
  formatScopeLabel,
  formatScopeWarning,
  formatUnfilledSub,
  formatWeightCoverage,
  formatZeroFillSub,
} from './report-format';
import type { TcaReportExtraKpis, TcaReportScope, TcaWeightCoverageEntry } from '../types';

const entry = (overrides: Partial<TcaWeightCoverageEntry> = {}): TcaWeightCoverageEntry => ({
  n_used: 1,
  n_total: 2,
  sample_pct: 50,
  used_weight: 100,
  total_weight: 100,
  weight_pct: 100,
  insufficient: true,
  ...overrides,
});

const scope = (overrides: Partial<TcaReportScope> = {}): TcaReportScope => ({
  mode: 'bdib_whitelist',
  exchanges: ['US', 'HK'],
  out_of_scope: [],
  label: 'BDIB 白名单内 2 个市场',
  ...overrides,
});

const extra = (overrides: Partial<TcaReportExtraKpis> = {}): TcaReportExtraKpis => ({
  arrival_cost_bps: 4,
  wagner_is_bps: 6,
  cost_stddev: 1,
  cost_cvar: 2,
  cost_p95: 3,
  avg_fill: 0.95,
  unfilled_notional_usd: 1000,
  unfilled_notional_unpriced_routes: 0,
  zero_fill_routes: 1,
  zero_fill_notional_usd: 250000,
  ...overrides,
});

describe('formatWeightCoverage', () => {
  it('并列披露样本量与权重覆盖率，覆盖不足时附提示', () => {
    expect(formatWeightCoverage(entry())).toBe(
      '样本 1/2（50%） · 权重覆盖 100% · 样本/权重覆盖不足，结论仅供参考',
    );
  });

  it('覆盖充足时不给提示（仅样本与权重）', () => {
    const note = formatWeightCoverage(
      entry({ n_used: 9, n_total: 10, sample_pct: 90, weight_pct: 98, insufficient: false }),
    );
    expect(note).toBe('样本 9/10（90%） · 权重覆盖 98%');
    expect(note).not.toContain('结论仅供参考');
  });

  it('缺披露（旧 payload 无 weight_coverage）时返回空串', () => {
    expect(formatWeightCoverage(null)).toBe('');
    expect(formatWeightCoverage(undefined)).toBe('');
  });

  it('权重覆盖缺失（不可加权）时只展示样本量', () => {
    expect(formatWeightCoverage(entry({ weight_pct: null, insufficient: false }))).toBe(
      '样本 1/2（50%）',
    );
  });
});

describe('appendNote', () => {
  it('有披露时以分隔符拼接，无披露时原样返回', () => {
    expect(appendNote('成交额加权', '权重覆盖 80%')).toBe('成交额加权 · 权重覆盖 80%');
    expect(appendNote('成交额加权', '')).toBe('成交额加权');
  });
});

describe('formatScopeLabel / formatScopeWarning', () => {
  it('展示统计范围文案', () => {
    expect(formatScopeLabel(scope())).toBe('统计范围 BDIB 白名单内 2 个市场');
    expect(formatScopeLabel(null)).toBe('');
  });

  it('白名单内选择不告警；越界选择显式告警', () => {
    expect(formatScopeWarning(scope())).toBe('');
    const warning = formatScopeWarning(
      scope({ mode: 'user_exchange_filter', out_of_scope: ['CN'], label: '用户指定市场 CN, US' }),
    );
    expect(warning).toContain('CN');
    expect(warning).toContain('不在 BDIB 白名单内');
  });
});

describe('未成交缺口 / 零成交卡片副标题', () => {
  it('未成交缺口披露价格回退链与未计价条数', () => {
    expect(formatUnfilledSub(extra())).toBe('Σ(未成交 × 价格回退链 × 汇率)');
    expect(formatUnfilledSub(extra({ unfilled_notional_unpriced_routes: 3 }))).toContain(
      '未计价 3 条',
    );
    expect(formatUnfilledSub(null)).toContain('价格回退链');
  });

  it('零成交卡片展示委托金额与语义', () => {
    expect(formatZeroFillSub(extra())).toBe('委托金额 $250.0K · 完全未执行');
    expect(formatZeroFillSub(null)).toContain('—');
  });

  it('覆盖率百分数取整展示（非整数样本比四舍五入）', () => {
    const note = formatWeightCoverage(
      entry({ n_used: 5, n_total: 6, sample_pct: 83.33, weight_pct: 61.4, insufficient: true }),
    );
    expect(note).toContain('样本 5/6（83%）');
    expect(note).toContain('权重覆盖 61%');
  });
});

/** CostView 报告统一格式化工具（Report 页面与 HTML 导出共用口径） */

import type {
  TcaReportExtraKpis,
  TcaReportScope,
  TcaWeightCoverageEntry,
} from '../types';

export const formatNum = (value: number | null, digits = 2): string =>
  value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: digits });

export const formatMoney = (value: number | null): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(1)}K`;
  return `$${value.toFixed(0)}`;
};

export const formatShares = (value: number | null): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(0);
};

/** bps 值格式化（保留两位小数，None → —） */
export const formatBps = (value: number | null): string =>
  value == null || !Number.isFinite(value) ? '—' : value.toFixed(2);

/**
 * 百分比展示（0-1 小数 → %），None → —。
 *
 * **不封顶**：完成率 / 参与率 > 100% 属数据矛盾（overfill、订单参与率求和越界），
 * 必须显式暴露而非被展示层钳制 —— 与 HTML 报告 `_fmt_pct` 同口径
 * （ADR-0018 §2「移除展示层封顶」；此前 web 端封顶 100%，使「组合完成率」卡
 * 把 overfill 驱动的 >100% 钳成 100.00%，与 HTML 报告结论相反）。
 */
export const formatPct = (value: number | null): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${(value * 100.0).toFixed(2)}%`;
};

/** 风险区间展示 stddev / CVaR */
export const formatRisk = (stddev: number | null, cvar: number | null): string =>
  `${formatNum(stddev)} / ${formatNum(cvar)}`;

export const formatInt = (value: number | null): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  try {
    return `${Math.round(value).toLocaleString()}`;
  } catch {
    return '—';
  }
};

/** 历时展示：秒 → 分钟/小时 */
export const formatDuration = (seconds: number | null): string => {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`;
  if (seconds >= 60) return `${(seconds / 60).toFixed(1)}m`;
  return `${seconds.toFixed(0)}s`;
};

/** 成交金额格式化（带币种前缀），None → — */
export const formatMoneyWithCcy = (value: number | null, currency: string | null): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  const ccy = (currency ?? '').toUpperCase();
  const prefix = ccy ? `${ccy} ` : '';
  return `${prefix}${formatMoney(value)}`;
};

/** 已是百分数（0-100）的展示，0 位小数；None → —（仅供本模块内覆盖披露复用） */
const formatPctPoint = (value: number | null): string =>
  value == null || !Number.isFinite(value) ? '—' : `${Math.round(value)}%`;

/** 副标题拼接：基础文案 + 覆盖披露（无披露时原样返回） */
export const appendNote = (base: string, note?: string): string =>
  note ? `${base} · ${note}` : base;

/**
 * 加权指标的样本量与权重覆盖披露（与 HTML 报告 `_weight_note` 的**核心句**逐字对齐）。
 *
 * 条数覆盖与权重覆盖必须并列：BDIB 缺口集中在少数大单时，条数覆盖可以很高而
 * 权重覆盖很低 —— 此时 KPI 是子样本口径，量级不足以支撑跨期对比。
 *
 * 与 HTML 渲染器的**有意偏差**（改动前须两端同步决策，勿单侧「修复」）：
 * 1. 百分数精度：此处取整（`50%`），HTML `_fmt_pct_raw` 保留两位（`50.00%`）——
 *    UI 卡片宽度受限，取整已由 `report-format.test.ts` 固化；
 * 2. 分隔符：此处用 ` · `，HTML 用全角空格 —— 沿用前端既有副标题排版惯例。
 */
export const formatWeightCoverage = (entry?: TcaWeightCoverageEntry | null): string => {
  if (!entry) return '';
  const parts: string[] = [];
  if (entry.n_total) {
    parts.push(`样本 ${entry.n_used}/${entry.n_total}（${formatPctPoint(entry.sample_pct)}）`);
  }
  if (entry.weight_pct != null) parts.push(`权重覆盖 ${formatPctPoint(entry.weight_pct)}`);
  if (entry.insufficient) parts.push('样本/权重覆盖不足，结论仅供参考');
  return parts.join(' · ');
};

/**
 * 报告统计范围文案（filters.scope / metric_coverage.scope）。
 *
 * 「（全报告统一口径）」后缀与 HTML 报告头逐字对齐：它承载「KPI / 走势 / 排行 /
 * 市场概览 / 异常明细 / 覆盖率同口径」这一关键承诺，不可省略。
 */
export const formatScopeLabel = (scope?: TcaReportScope | null): string =>
  scope?.label ? `统计范围 ${scope.label}（全报告统一口径）` : '';

/** 白名单外市场告警文案（与 HTML 报告头 `_scope_note` 对齐）；无越界选择 → 空串 */
export const formatScopeWarning = (scope?: TcaReportScope | null): string => {
  const outside = scope?.out_of_scope ?? [];
  if (!outside.length) return '';
  return `所选市场 ${outside.join(', ')} 不在 BDIB 白名单内 —— 这些市场不拉取 BDIB`
    + ' 行情，其 BDIB 依赖指标必然为 NULL，覆盖率与走势请对照下方覆盖率表解读。';
};

/** 未成交金额缺口副标题：口径说明 + 未能计价路由数（缺口低估规模可见） */
export const formatUnfilledSub = (extra?: TcaReportExtraKpis | null): string => {
  const base = 'Σ(未成交 × 价格回退链 × 汇率)';
  const unpriced = extra?.unfilled_notional_unpriced_routes;
  return unpriced ? `${base} · 未计价 ${formatInt(unpriced)} 条（未计入）` : base;
};

/**
 * 零成交路由卡副标题：委托金额 + 语义说明。
 *
 * 与 HTML 渲染器的**有意偏差**：此处带 `$` 前缀（该字段确为 USD 口径），
 * HTML 侧走 `_fmt_big` 无前缀（金额单位由卡片标题承载）。
 */
export const formatZeroFillSub = (extra?: TcaReportExtraKpis | null): string =>
  `委托金额 ${formatMoney(extra?.zero_fill_notional_usd ?? null)} · 完全未执行`;

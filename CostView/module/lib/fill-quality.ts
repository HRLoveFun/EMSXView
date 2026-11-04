/**
 * 详情卡第二屏的口径常量与判定（210 §4.5 / §4.6）。
 *
 * 阈值与判定只在这里写一次：组件只负责渲染，不各自写 `< 6` / `> 0.7` 这类魔法数。
 * 后端 `trader_metrics` 的 fill_distribution / liquidity_split 负责算数，
 * 本模块只解释结果（哪些值构成「线索」、哪些份额要打标）。
 */

/** §4.5 集中扫单线索：至少 6 笔（少量成交的 top3 占比没有解释力） */
export const SWEEP_MIN_FILLS = 6;
/** §4.5 集中扫单线索：前 3 笔占比 ≥ 70% */
export const SWEEP_TOP3_SHARE = 0.7;
/** §4.5 集中扫单线索：最大单笔占委托股数 ≥ 30% */
export const SWEEP_MAX_FILL_RATIO = 0.3;

/** §4.6 未知流动性占比警示线（>10% 在订单卡与 KPI 上打 liquidity_unknown） */
export const UNKNOWN_WARN_SHARE = 0.1;

/** 集中扫单线索判定结果（text 为空表示不提示） */
export interface SweepHint {
  triggered: boolean;
  text: string;
}

/**
 * 集中扫单 / 切片不均线索（§4.5）。
 *
 * 样本不足（`fill_count < 6`）与统计量不可得时**不提示**——这类订单的 top3 占比
 * 天然偏高，拿它下「扫单」结论就是噪声；返回空文案让 UI 什么都不加。
 */
export function sweepHint(
  fillCount: number | null,
  top3Share: number | null,
  maxFillRatio: number | null,
): SweepHint {
  if (fillCount == null || fillCount < SWEEP_MIN_FILLS) {
    return { triggered: false, text: '' };
  }
  const concentrated =
    top3Share != null && maxFillRatio != null
    && top3Share >= SWEEP_TOP3_SHARE && maxFillRatio >= SWEEP_MAX_FILL_RATIO;
  return concentrated
    ? { triggered: true, text: '集中扫单 / 切片不均（线索）' }
    : { triggered: false, text: '' };
}

/** 被动/主动成本差：`passive − aggressive`，**负 = 被动更差**（§4.6） */
export function passiveCostDiff(
  passive: number | null, aggressive: number | null,
): number | null {
  if (passive == null || aggressive == null) return null;
  return passive - aggressive;
}

/** 未知占积分级：none / info（>10%）/ warn（>25%，多数成交无法分类） */
export function unknownShareLevel(share: number | null): 'none' | 'info' | 'warn' {
  if (share == null || share <= UNKNOWN_WARN_SHARE) return 'none';
  return share > 0.25 ? 'warn' : 'info';
}

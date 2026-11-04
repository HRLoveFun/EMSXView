/**
 * 成本符号的唯一实现（210 §3.5 / §3.8）。
 *
 * 上游成本字段是**有符号**值（`arrival_cost_bps` / `wagner_is_bps` / 各分量 bps）：
 * **负 = 成本不利**（跑输基准），正 = 成本有利。后端 `trader_metrics.adverse_bps`
 * 已把该约定收敛为 `adverse = -value`（正 = 差），前端一律经本模块判断方向，
 * 禁止各组件自己写 `value < 0`（两处符号一旦不一致，颜色会与数字相反）。
 */

/** 不利幅度：正 = 成本不利（`null` / 非有限值 → `null`，不按 0 解读） */
export const adverseBps = (value: number | null): number | null => {
  if (value == null || !Number.isFinite(value)) return null;
  // 避免 -0（Object.is(-0, 0) === false，会污染严格相等断言与 React 比较）
  return value === 0 ? 0 : -value;
};

/** 是否为不利方向（0 与 null 均不算不利） */
export const isAdverse = (value: number | null): boolean => {
  const adverse = adverseBps(value);
  return adverse != null && adverse > 0;
};

/** 成本数值的语义色（不利红 / 有利绿 / 0 与不可得灰） */
export const costToneClass = (value: number | null): string => {
  if (value == null || !Number.isFinite(value) || value === 0) return 'text-muted-foreground';
  return isAdverse(value) ? 'text-rose-500' : 'text-emerald-500';
};

/** 带符号 bps 文案（显式正负号；不可得 → 「—」） */
export const formatSignedBps = (value: number | null): string =>
  value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)} bps`;

/** 堆叠条段长：按不利幅度归一（有利分量不参与相抵，见 §4.3「不把正负相抵」） */
export const segmentWidthPct = (value: number | null, totalAdverse: number): number => {
  const adverse = adverseBps(value);
  if (adverse == null || adverse <= 0 || totalAdverse <= 0) return 0;
  return (adverse / totalAdverse) * 100;
};

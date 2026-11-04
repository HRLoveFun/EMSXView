import { formatMoney, formatPct } from '../../lib/report-format';
import { adverseBps, costToneClass, formatSignedBps, segmentWidthPct } from '../../lib/cost-sign';
import type { TraderCostBreakdown } from '../../types';

/** 三个成本分量的展示顺序与配色（顺序 = 堆叠条从左到右） */
const SEGMENTS: Array<{
  key: 'delay_bps' | 'trading_bps' | 'opportunity_bps';
  costKey: 'delay_cost' | 'trading_cost' | 'opportunity_cost';
  label: string;
  color: string;
}> = [
  { key: 'delay_bps', costKey: 'delay_cost', label: '延迟', color: '#60a5fa' },
  { key: 'trading_bps', costKey: 'trading_cost', label: '成交', color: '#a78bfa' },
  { key: 'opportunity_bps', costKey: 'opportunity_cost', label: '机会', color: '#fb923c' },
];

interface CostBreakdownBarProps {
  cost: TraderCostBreakdown;
  /** 订单完成率（<1 时机会成本单独高亮，§4.3） */
  completion: number | null;
}

/** 堆叠条（按不利幅度归一；有利分量不参与相抵，长度记 0 并单独标注） */
function stackedBar(cost: TraderCostBreakdown) {
  const totalAdverse = SEGMENTS.reduce(
    (sum, segment) => sum + Math.max(adverseBps(cost[segment.key]) ?? 0, 0),
    0,
  );
  return (
    <div className="flex h-4 w-full overflow-hidden rounded bg-muted">
      {SEGMENTS.map((segment) => {
        const width = segmentWidthPct(cost[segment.key], totalAdverse);
        return width > 0 ? (
          <div
            key={segment.key}
            style={{ width: `${width}%`, backgroundColor: segment.color }}
            title={`${segment.label} ${formatSignedBps(cost[segment.key])}（不利占比 ${width.toFixed(1)}%）`}
          />
        ) : null;
      })}
    </div>
  );
}

/** 分母缺失时的货币成本回退展示（§4.3：只展示原始货币成本，不画 bps） */
function currencyOnly(cost: TraderCostBreakdown) {
  return (
    <div className="space-y-1">
      {SEGMENTS.map((segment) => (
        <div key={segment.key} className="flex justify-between text-xs">
          <span className="text-muted-foreground">{segment.label}成本</span>
          <span className={costToneClass(cost[segment.costKey])}>
            {formatMoney(cost[segment.costKey])}
          </span>
        </div>
      ))}
    </div>
  );
}

function segmentRows(cost: TraderCostBreakdown) {
  return (
    <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
      {SEGMENTS.map((segment) => {
        const value = cost[segment.key];
        const favorable = value != null && value > 0;
        return (
          <div key={segment.key} className="space-y-0.5">
            <div className="text-muted-foreground">{segment.label}</div>
            <div className={costToneClass(value)}>{formatSignedBps(value)}</div>
            <div className="text-[11px] text-muted-foreground">
              {formatMoney(cost[segment.costKey])}
              {favorable && '（有利，不参与堆叠）'}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/**
 * 订单级 IS 成本分解条（210 §4.3）。
 *
 * - 堆叠长度按**不利幅度**（`adverse = -value`）归一，数字标签仍是上游有符号值；
 *   有利分量为正、宽度记 0 并单独标注，不做正负相抵（否则「一半赚一半亏」会伪装成零成本）。
 * - `residual_bps = wagner_is_bps − (delay + trading + opportunity)` 是**对账项**：
 *   |residual| ≥ 0.5bps 标「对账异常」，不写「归因不全」。
 * - `p_decision` 缺失（分母为 null）时只展示货币成本，不画 bps（§4.3 硬要求）。
 */
export function CostBreakdownBar({ cost, completion }: CostBreakdownBarProps) {
  const unavailable = cost.denominator == null;
  return (
    <section className="space-y-2">
      <header className="flex items-center justify-between">
        <h3 className="text-sm font-medium">成本分解（IS，分母 RouteShares × p_decision）</h3>
        <div className="flex gap-2 text-[11px]">
          {cost.opportunity_dominant && (
            <span className="rounded bg-orange-100 px-1.5 py-0.5 text-orange-700">
              机会成本主导（|机会| &gt; |arrival|）
            </span>
          )}
          {cost.opportunity_highlight && (
            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-700">
              完成率 {formatPct(completion)}，机会成本单独高亮
            </span>
          )}
          {cost.residual_flag && (
            <span className="rounded bg-rose-100 px-1.5 py-0.5 text-rose-700">
              {cost.residual_flag}
            </span>
          )}
        </div>
      </header>

      {unavailable ? (
        <>
          <p className="text-xs text-amber-600">{cost.note ?? 'IS 分解不可用（无 BDIB/决策价）'}</p>
          {currencyOnly(cost)}
        </>
      ) : (
        <>
          {stackedBar(cost)}
          {segmentRows(cost)}
        </>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t pt-2 text-xs">
        <span>
          wagner_is <span className={costToneClass(cost.wagner_is_bps)}>
            {formatSignedBps(cost.wagner_is_bps)}
          </span>
        </span>
        <span title="分母为 p_arrival（不含路由下达→首笔的漂移），与 wagner_is 不可直接比大小">
          arrival <span className={costToneClass(cost.arrival_cost_bps)}>
            {formatSignedBps(cost.arrival_cost_bps)}
          </span>
        </span>
        <span title="wagner_is_bps − 三项分量之和；≥0.5bps 视为对账异常">
          残差 {formatSignedBps(cost.residual_bps)}
        </span>
      </div>
    </section>
  );
}

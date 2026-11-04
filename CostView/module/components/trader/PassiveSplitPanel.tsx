import { formatPct, formatShares } from '../../lib/report-format';
import { costToneClass, formatSignedBps } from '../../lib/cost-sign';
import { passiveCostDiff, unknownShareLevel } from '../../lib/fill-quality';
import type { TraderLiquiditySplit } from '../../types';

/** 四档颜色与顺序（被动 / 主动 / 竞价 / 未知） */
const SEGMENTS: Array<{ key: keyof TraderLiquiditySplit; label: string; color: string }> = [
  { key: 'passive_share_strict', label: '被动', color: '#26a69a' },
  { key: 'aggressive_share_strict', label: '主动', color: '#ef5350' },
  { key: 'auction_share', label: '竞价', color: '#42a5f5' },
  { key: 'unknown_share', label: '未知', color: '#9e9e9e' },
];

/** 堆叠条：宽度按占比（不可得 → 0 宽度但仍在图例列出） */
function SplitBar({ liquidity }: { liquidity: TraderLiquiditySplit }) {
  return (
    <div className="flex h-4 w-full overflow-hidden rounded bg-muted">
      {SEGMENTS.map((segment) => {
        const share = liquidity[segment.key] as number | null;
        if (share == null || share <= 0) return null;
        return (
          <div
            key={segment.key}
            style={{ width: `${share * 100}%`, backgroundColor: segment.color }}
            title={`${segment.label} ${formatPct(share)}`}
          />
        );
      })}
    </div>
  );
}

/**
 * 主动 / 被动成交拆分与成本差（210 §4.6）。
 *
 * 分类走 FIX Tag 851 严格映射（后端 `liquidity_split`），未知档不并入主动/被动；
 * 成本差 `passive − aggressive`，**负 = 被动更差**，符号判断统一走 lib/cost-sign。
 */
export function PassiveSplitPanel({ liquidity }: { liquidity: TraderLiquiditySplit }) {
  const unknownLevel = unknownShareLevel(liquidity.unknown_share);
  const diff = passiveCostDiff(liquidity.passive_cost_bps, liquidity.aggressive_cost_bps);
  return (
    <section className="space-y-2">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">主动 / 被动拆分（FIX 851 严格映射）</h3>
        {unknownLevel !== 'none' && (
          <span
            className={`rounded px-1.5 py-0.5 text-[11px] ${
              unknownLevel === 'warn'
                ? 'bg-rose-100 text-rose-700' : 'bg-amber-100 text-amber-700'
            }`}
            title="Liquidity 未识别的成交股数占比；3/0/5/6/Z/P/A 映射待业务确认"
          >
            未识别 {formatPct(liquidity.unknown_share)}
          </span>
        )}
      </header>
      <SplitBar liquidity={liquidity} />
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        {SEGMENTS.map((segment) => (
          <div key={segment.key} className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: segment.color }} />
            <span className="text-muted-foreground">{segment.label}</span>
            <span className="font-medium">
              {formatPct(liquidity[segment.key] as number | null)}
            </span>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-2 border-t pt-2 text-xs">
        <div>
          <div className="text-[11px] text-muted-foreground">被动成本（对 arrival）</div>
          <div className={costToneClass(liquidity.passive_cost_bps)}>
            {formatSignedBps(liquidity.passive_cost_bps)}
          </div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground">主动成本（对 arrival）</div>
          <div className={costToneClass(liquidity.aggressive_cost_bps)}>
            {formatSignedBps(liquidity.aggressive_cost_bps)}
          </div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground" title="passive − aggressive：负 = 被动更差">
            成本差（被动 − 主动）
          </div>
          <div className={costToneClass(diff)}>{formatSignedBps(diff)}</div>
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground">
        成交股数合计 {formatShares(liquidity.total_shares)}；已识别占比{' '}
        {formatPct(liquidity.recognized_share)}；映射口径 {liquidity.mapping}（1=被动 2=主动
        4=竞价，其余为未知）。
      </p>
    </section>
  );
}

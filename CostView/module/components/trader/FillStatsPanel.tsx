import { formatInt, formatNum, formatPct, formatShares } from '../../lib/report-format';
import { sweepHint } from '../../lib/fill-quality';
import type { TraderFillStats } from '../../types';

interface FillStatsPanelProps {
  stats: TraderFillStats;
  /** 订单成交笔数（扫单线索的样本门槛用） */
  fillCount: number | null;
}

/** 指标单元格：值与口径说明分离，null 一律 N/A（禁止按 0 解读） */
function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded border p-2" title={note}>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}

const na = (text: string) => (text === '—' ? 'N/A' : text);

/**
 * 单次填充量分布与扫单线索（210 §4.5）。
 *
 * 统计量全部由后端 `trader_metrics.fill_distribution` 给出，前端只负责格式化；
 * 单笔成交（`fill_count < 2`）后端已把 CV / top3 置空 → 此处显示 N/A 而不是 0。
 */
export function FillStatsPanel({ stats, fillCount }: FillStatsPanelProps) {
  const hint = sweepHint(fillCount, stats.top3_share, stats.max_fill_ratio);
  return (
    <section className="space-y-2">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">单次填充量分布</h3>
        {hint.triggered && (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-700">
            {hint.text}
          </span>
        )}
      </header>
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3 lg:grid-cols-6">
        <Metric label="中位单笔（股）" value={na(formatShares(stats.median))} />
        <Metric label="P90 单笔（股）" value={na(formatShares(stats.p90))} />
        <Metric
          label="单笔 CV" value={na(formatNum(stats.cv))}
          note="标准差 / 均值；单笔成交不计算"
        />
        <Metric
          label="最大单笔 / 委托" value={na(formatPct(stats.max_fill_ratio))}
          note="max(FillShares) / RouteShares"
        />
        <Metric
          label="Top3 占比" value={na(formatPct(stats.top3_share))}
          note="前 3 大成交股数 / 总成交股数；<3 笔为 N/A"
        />
        <Metric
          label="成交频率" value={na(formatNum(stats.fills_per_min))}
          note="笔 / 分钟（首笔→末笔跨度）"
        />
      </div>
      <p className="text-[11px] text-muted-foreground">
        成交笔数 {formatInt(fillCount)}；线索判定：≥{6} 笔且 Top3 占比 ≥70% 且最大单笔
        占委托 ≥30%（样本不足不提示）。
      </p>
    </section>
  );
}

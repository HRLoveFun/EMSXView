import { formatInt, formatNum } from '../../lib/report-format';
import type { TraderPeerMetric, TraderPeerStats } from '../../types';

/** 分位条：0–100，50 为 peer 中位参考线（§4.7 不用雷达图） */
function PercentileBar({ metric }: { metric: TraderPeerMetric }) {
  const pct = Math.max(0, Math.min(1, metric.percentile ?? 0)) * 100;
  const better = metric.direction === 'higher_better' ? '越高越好' : '越低越好';
  return (
    <div className="space-y-0.5" title={`${metric.label}：分位 ${pct.toFixed(0)}（${better}）`}>
      <div className="flex items-baseline justify-between text-xs">
        <span>{metric.label}</span>
        <span className="tabular-nums text-muted-foreground">
          {formatNum(metric.value)} · 中位 {formatNum(metric.median)} · 分位 {pct.toFixed(0)}
        </span>
      </div>
      <div className="relative h-2 rounded bg-muted">
        <div
          className="h-2 rounded bg-primary"
          style={{ width: `${pct}%` }}
        />
        {/* 中位 50 参考线 */}
        <span
          className="absolute top-[-2px] h-3 w-px bg-foreground/40"
          style={{ left: '50%' }}
          aria-hidden="true"
        />
      </div>
    </div>
  );
}

/**
 * 算法特征指纹（210 §4.7）：8 维 peer 分位条 + 中位 50 参考线。
 *
 * 三条硬规则：
 * 1. `sample_insufficient`（n 未达最小样本）时**不画分位**，只列原值与 n；
 * 2. 单维 `available=false` 时显示「未计算」与原因（逐笔类维度在订单层不可得）；
 * 3. 方向写在 tooltip 里（成本类分位越低越差），不靠颜色暗示好坏。
 */
export function PeerFingerprint({ peer }: { peer: TraderPeerStats }) {
  const available = peer.metrics.filter((metric) => metric.available);
  const missing = peer.metrics.filter((metric) => !metric.available);
  return (
    <section className="space-y-2">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">同类分位（{peer.group.window_days} 天）</h3>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <span>{peer.group.note}</span>
          <span>n = {formatInt(peer.n)}</span>
          {!peer.sample_insufficient && (
            <span>偏离中位维度 {peer.deviation_count}</span>
          )}
        </div>
      </header>

      {peer.sample_insufficient ? (
        <div className="space-y-1 rounded border border-amber-300/60 bg-amber-50/40 p-2 text-xs">
          <div className="text-amber-700">
            样本不足（n = {formatInt(peer.n)}，未达最小样本），不展示分位，只列原值。
          </div>
          <ul className="grid grid-cols-2 gap-x-3 gap-y-0.5 sm:grid-cols-4">
            {peer.metrics.map((metric) => (
              <li key={metric.key} className="text-muted-foreground">
                {metric.label}：{metric.value == null ? 'N/A' : formatNum(metric.value)}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="space-y-1.5">
          {available.map((metric) => (
            <PercentileBar key={metric.key} metric={metric} />
          ))}
        </div>
      )}

      {missing.length > 0 && (
        <ul className="space-y-0.5 text-[11px] text-muted-foreground">
          {missing.map((metric) => (
            <li key={metric.key}>
              {metric.label}：未计算{metric.note ? `（${metric.note}）` : ''}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

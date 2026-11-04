import { formatShares } from '../../lib/report-format';
import { computeTrajectory } from '../../lib/trajectory';
import type { TraderOrderDetail } from '../../types';

function spanText(seconds: number | null): string {
  if (seconds == null) return 'N/A（单笔成交）';
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`;
  if (seconds >= 60) return `${(seconds / 60).toFixed(1)}m`;
  return `${seconds.toFixed(0)}s`;
}

function ratioText(value: number | null): string {
  return value == null || !Number.isFinite(value) ? 'N/A' : value.toFixed(2);
}

/**
 * 完成轨迹摘要（210 §4.4）：跨度 / 速度 / 速度变异 / 峰值速度比 / 零成交桶 / 加速度 Top2。
 *
 * 逐桶累计完成率曲线由 `ExecutionTimeline` 的下方面板呈现，本组件只做**数字摘要**；
 * 统计口径与公式在 `lib/trajectory.ts`（纯函数、可单测），组件不内联计算。
 */
export function CompletionTrajectory({ detail }: { detail: TraderOrderDetail }) {
  const stats = computeTrajectory(detail);
  const items: Array<{ label: string; value: string; title?: string }> = [
    { label: '成交跨度', value: spanText(stats.spanSec) },
    {
      label: '平均速度',
      value: stats.speedPerMin == null ? 'N/A' : `${formatShares(stats.speedPerMin)}/分钟`,
    },
    {
      label: '速度 CV（非零桶）',
      value: ratioText(stats.speedCv),
      title: 'std / mean，仅统计有成交的桶（与后端 fill_span_stats 同口径）',
    },
    {
      label: '峰值速度比',
      value: ratioText(stats.maxSpeedRatio),
      title: '最大非零桶速度 / 非零桶均值',
    },
    {
      label: '零成交桶',
      value: String(stats.zeroBuckets),
      title: 'CV 很小但中间长期不动时，该值会暴露出来',
    },
  ];
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium">完成轨迹（速度与加速度）</h3>
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
        {items.map((item) => (
          <div key={item.label} className="rounded border p-2" title={item.title}>
            <div className="text-[11px] text-muted-foreground">{item.label}</div>
            <div className="font-medium">{item.value}</div>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-muted-foreground">
        {stats.accelTop.length === 0
          ? '加速度：仅 1 个桶，无加速度可算（N/A）'
          : `加速度最大：${stats.accelTop
              .map((item) => `${item.label} ${formatShares(item.accel)}/分钟²`)
              .join('、')}`}
      </p>
    </section>
  );
}

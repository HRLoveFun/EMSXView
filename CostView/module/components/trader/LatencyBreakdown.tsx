import { formatDuration } from '../../lib/report-format';
import type { TraderLatency } from '../../types';

/** 秒值展示：不可得 → 「—」，<60s 保留 1 位小数，更长走 formatDuration */
function seconds(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return Math.abs(value) < 60 ? `${value.toFixed(1)}s` : formatDuration(value);
}

/**
 * 延迟分解（210 §4.9）：下达→路由 / 路由→首笔 / 合计到达首笔 / 首笔连续成交偏移。
 *
 * 收盘与竞价单的三段延迟是**排程**而不是延迟，后端已置 `scheduled=true`：此时只显示
 * 「按计划成交」，不把数值读成执行问题；`latency_anomaly`（首笔非竞价成交早于路由
 * 下达 >1s）单独标红。peer p90 随 peer 端点接入（§4.13），此处显式写「未接入」。
 */
export function LatencyBreakdown({ latency }: { latency: TraderLatency }) {
  const rows: Array<{ label: string; value: number | null; note?: string }> = [
    { label: '下达 → 路由', value: latency.order_to_route_sec },
    { label: '路由 → 首笔成交', value: latency.route_to_first_fill_sec },
    { label: '合计：下达 → 首笔', value: latency.order_to_first_fill_sec },
    {
      label: '首笔连续成交偏移',
      value: latency.first_continuous_fill_sec,
      note: '相对路由下达时刻；负值 <1s 视为舍入（后端已钳 0）',
    },
  ];
  return (
    <section className="space-y-2">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">延迟分解</h3>
        {latency.scheduled && (
          <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[11px] text-sky-700">
            按计划在收盘竞价成交（延迟不作异常）
          </span>
        )}
        {latency.latency_anomaly && (
          <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[11px] text-rose-700">
            首笔非竞价成交早于路由下达 &gt;1s
          </span>
        )}
      </header>
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        {rows.map((row) => (
          <div key={row.label} className="rounded border p-2" title={row.note}>
            <div className="text-[11px] text-muted-foreground">{row.label}</div>
            <div className="font-medium">{seconds(row.value)}</div>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-muted-foreground">
        时间戳取自 raw_fills 的 NY 时区字段（同一时区差值，与时区偏移无关）；peer p90
        对比随 peer 端点接入（当前未接入，不是「通过」）。
      </p>
    </section>
  );
}

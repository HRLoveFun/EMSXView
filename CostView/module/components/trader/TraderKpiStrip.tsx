import { AlertTriangle, CheckCircle2, CircleSlash } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import type { TraderListPayload, TraderProbeCheck } from '../../types';

/** KPI 卡定义：key 对应 payload.kpi 的键；null 一律显示「—」（禁止按 0 解读） */
interface KpiCardDef {
  key: string;
  label: string;
  format: (value: number) => string;
  caption?: (kpi: TraderListPayload['kpi'][string]) => string | null;
}

const pct = (value: number) => `${(value * 100).toFixed(1)}%`;
const seconds = (value: number) => `${Math.round(value)}s`;
const count = (value: number) => value.toLocaleString();

const KPI_CARDS: KpiCardDef[] = [
  { key: 'orders', label: '订单数', format: count },
  { key: 'low_completion_ratio', label: '低完成率占比', format: pct },
  { key: 'opp_dominant_ratio', label: '机会成本主导占比', format: pct },
  {
    key: 'passive_ratio',
    label: '被动占比（当前页）',
    format: pct,
    caption: (kpi) => (kpi.unknown_share == null ? null : `未知 ${(kpi.unknown_share * 100).toFixed(1)}%`),
  },
  {
    key: 'release_delay_p90',
    label: '释放延迟 p90',
    format: seconds,
    caption: () => '仅连续算法（收盘/竞价单不计）',
  },
  {
    key: 'anomaly_orders',
    label: '异常订单',
    format: count,
    caption: (kpi) => (kpi.critical == null ? null : `critical ${kpi.critical} / warning ${kpi.warning ?? 0}`),
  },
  { key: 'peer_small_orders', label: 'peer 样本不足', format: count },
];

/** KPI 首屏条（210 §4.13）：值缺失显示「—」，副标题承载样本量/口径注记 */
export function TraderKpiStrip({ kpi }: { kpi: TraderListPayload['kpi'] }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
      {KPI_CARDS.map((card) => {
        const entry = kpi[card.key];
        const value = entry?.value ?? null;
        const caption = entry && card.caption ? card.caption(entry) : null;
        return (
          <Card key={card.key}>
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">{card.label}</div>
              <div className="mt-1 text-xl font-semibold">{value == null ? '—' : card.format(value)}</div>
              <div className="mt-0.5 truncate text-[10px] text-muted-foreground" title={caption ?? ''}>
                {caption ?? (entry?.note ?? '')}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

const PROBE_LABELS: Record<string, string> = {
  quantity: '数量一致性',
  participation: '参与率一致性',
  cost_missing: '成本字段缺失',
  fill_quality: '逐笔质量',
};

/** 全局可信度横幅（210 §4.12）：4 类检查始终显示，未检查不伪装通过 */
export function TraderProbesBanner({ probes }: { probes: TraderProbeCheck[] }) {
  return (
    <Alert>
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>数据可信度检查</AlertTitle>
      <AlertDescription>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {probes.map((probe) => (
            <ProbeItem key={probe.id} probe={probe} />
          ))}
        </div>
      </AlertDescription>
    </Alert>
  );
}

function ProbeItem({ probe }: { probe: TraderProbeCheck }) {
  const label = PROBE_LABELS[probe.id] ?? probe.id;
  if (!probe.checked) {
    return (
      <div className="flex items-start gap-1.5 text-xs text-muted-foreground" title={probe.note ?? ''}>
        <CircleSlash className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          {label}：<span className="italic">未检查</span>
          {probe.note ? `（${probe.note}）` : ''}
        </span>
      </div>
    );
  }
  const triggered = probe.triggered ?? 0;
  return (
    <div className="flex items-start gap-1.5 text-xs">
      {triggered > 0 ? (
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
      ) : (
        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
      )}
      <span>
        {label}：
        {triggered > 0 ? (
          <span className="font-medium text-amber-600">{triggered} 单受影响</span>
        ) : (
          <span className="text-emerald-600">通过</span>
        )}
        {probe.note ? `（${probe.note}）` : ''}
      </span>
    </div>
  );
}

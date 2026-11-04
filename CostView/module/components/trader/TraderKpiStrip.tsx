import { Card, CardContent } from '@/components/ui/card';
import type { TraderListPayload } from '../../types';

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



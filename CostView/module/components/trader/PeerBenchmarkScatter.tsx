import {
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { formatBps, formatInt } from '../../lib/report-format';
import type { TraderPeerPoint, TraderPeerStats } from '../../types';

/** 取某维度的 peer 中位（后端已算好，前端不重算中位数） */
function dimensionMedian(peer: TraderPeerStats, key: string): number | null {
  const metric = peer.metrics.find((item) => item.key === key);
  return metric?.median ?? null;
}

function hasBoth(point: TraderPeerPoint): boolean {
  return point.arrival_cost_bps != null && point.opportunity_cost_bps != null;
}

/**
 * 同类订单散点（210 §4.7 / §3.5）：横轴 arrival、纵轴机会成本，中位十字线，
 * 本单单独高亮（红色大点）。
 *
 * 中位线取自 peer payload 的 `metrics.median`（与指纹同源），不在前端再算一遍；
 * 采样上限由后端控制（`points_truncated` 披露被截断的点数）。
 */
export function PeerBenchmarkScatter({ peer }: { peer: TraderPeerStats }) {
  const valid = peer.points.filter(hasBoth);
  const peers = valid.filter((point) => !point.is_self);
  const self = valid.filter((point) => point.is_self);
  const medianX = dimensionMedian(peer, 'arrival_cost_bps');
  const medianY = dimensionMedian(peer, 'opportunity_cost_bps');
  const selfPoint = self[0];

  return (
    <section className="space-y-2">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">同类订单散点（arrival × 机会成本）</h3>
        <span className="text-[11px] text-muted-foreground">
          可比点 {formatInt(peers.length)} 个
          {peer.points_truncated > 0 && `（另截断 ${formatInt(peer.points_truncated)} 个）`}
        </span>
      </header>

      {valid.length < 2 ? (
        <p className="text-xs text-muted-foreground">
          可比样本不足（{formatInt(valid.length)} 个），不画散点。
        </p>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={240}>
            <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
              <XAxis
                type="number" dataKey="arrival_cost_bps" name="arrival"
                tick={{ fontSize: 11 }} tickFormatter={(value: number) => value.toFixed(1)}
              />
              <YAxis
                type="number" dataKey="opportunity_cost_bps" name="机会成本"
                width={64} tick={{ fontSize: 11 }}
                tickFormatter={(value: number) => value.toFixed(1)}
              />
              <Tooltip formatter={(value: number | string) => formatBps(Number(value))} />
              <Legend />
              <Scatter name="同类订单" data={peers} fill="#7d8fa3" />
              <Scatter name="本单" data={self} fill="#ef5350" />
              {medianX != null && (
                <ReferenceLine x={medianX} stroke="#9e9e9e" strokeDasharray="4 4" />
              )}
              {medianY != null && (
                <ReferenceLine y={medianY} stroke="#9e9e9e" strokeDasharray="4 4" />
              )}
            </ScatterChart>
          </ResponsiveContainer>
          <p className="text-[11px] text-muted-foreground">
            中位十字线：arrival {formatBps(medianX)} · 机会成本 {formatBps(medianY)}（bps）；
            本单 {selfPoint ? `arrival ${formatBps(selfPoint.arrival_cost_bps)} / 机会成本 ${formatBps(selfPoint.opportunity_cost_bps)}` : '落在不可比区间'}
            。两轴均为成本类指标，分位越低越差（见指纹 tooltip）。
          </p>
        </>
      )}
    </section>
  );
}

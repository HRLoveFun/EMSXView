import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  formatBps,
  formatDuration,
  formatInt,
  formatMoney,
  formatMoneyWithCcy,
  formatNum,
  formatPct,
  formatShares,
} from '../../lib/report-format';
import type { TcaAnomaly, TcaAnomalyRow } from '../../types';

/** 前端异常明细渲染上限（与 HTML 报告一致，避免数千行撑爆页面） */
const MAX_ANOMALY_ROWS_RENDERED = 1000;

function formatHitValue(value: number | undefined, unit: 'bps' | 'percent' | string | undefined): string {
  if (value == null || Number.isNaN(value)) return '-';
  const suffix = unit === 'bps' ? ' bps' : '%';
  return `${value.toFixed(1)}${suffix}`;
}

function AnomalyRowView({ r }: { r: TcaAnomalyRow }) {
  return (
    <tr className="border-t border-muted">
      <td className="py-0.5 pr-2 text-left">
        {r.hits.map((h) => (
          <span
            key={h.key}
            className="mr-1 inline-block rounded bg-destructive/20 px-1.5 py-0.5 text-[10px] text-destructive"
          >
            {`${h.label} ${formatHitValue(h.value, h.unit)}`}
          </span>
        ))}
      </td>
      <td className="py-0.5 pr-2 text-left text-muted-foreground">{r.date}</td>
      <td className="py-0.5 pr-2 text-left">{r.order_id}</td>
      <td className="py-0.5 pr-2 text-left">{r.route_id}</td>
      <td className="py-0.5 pr-2 text-left">{r.ticker}</td>
      <td className="py-0.5 pr-2 text-left text-muted-foreground">{r.exchange ?? ''}</td>
      <td className="py-0.5 pr-2 text-left">{r.side ?? ''}</td>
      <td className="py-0.5 pr-2 text-left">{formatMoneyWithCcy(r.notional_local, r.currency)}</td>
      <td className="py-0.5 pr-2 text-left">{formatMoney(r.notional_usd)}</td>
      <td className="py-0.5 pr-2 text-left">{r.broker ?? ''}</td>
      <td className="py-0.5 pr-2 text-left">{r.algo ?? ''}</td>
      <td className="py-0.5 pr-2 text-right">{formatPct(r.completion_rate)}</td>
      <td className="py-0.5 pr-2 text-right">{formatPct(r.par_rate)}</td>
      <td className="py-0.5 pr-2 text-right">{formatPct(r.order_par_rate)}</td>
      <td className="py-0.5 pr-2 text-right">{formatInt(r.fill_count)}</td>
      <td className="py-0.5 pr-2 text-right">{formatShares(r.route_shares)}</td>
      <td className="py-0.5 pr-2 text-right">{formatShares(r.fill)}</td>
      <td className="py-0.5 pr-2 text-right">{formatNum(r.pnl_vwap)}</td>
      <td className="py-0.5 pr-2 text-right">{formatBps(r.arrival_cost_bps)}</td>
      <td className="py-0.5 pr-2 text-right">{formatBps(r.wagner_is_bps)}</td>
      <td className="py-0.5 pr-2 text-right">{formatBps(r.opportunity_cost)}</td>
      <td className="py-0.5 pr-2 text-right">{formatShares(r.unfilled)}</td>
      <td className="py-0.5 pr-2 text-right">{formatBps(r.cost_cvar)}</td>
      <td className="py-0.5 pr-2 text-right">{formatDuration(r.order_duration_sec)}</td>
      <td className="py-0.5 pr-2 text-right">{r.recovery_truncated ? '1' : ''}</td>
    </tr>
  );
}

/** 异常路由明细表（S6）：触发阈值规则的路由逐单清单 */
export function AnomalyTable({ anomaly }: { anomaly?: TcaAnomaly | null }) {
  if (!anomaly) return null;
  const { count, rows } = anomaly;
  if (!rows || rows.length === 0) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">异常路由明细</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
            本期无异常路由（{count} 条触发阈值）
          </div>
        </CardContent>
      </Card>
    );
  }
  const truncated = Math.max(0, rows.length - MAX_ANOMALY_ROWS_RENDERED);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">异常路由明细（{count} 条）</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="mb-2 rounded border border-yellow-500/40 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-300">
          仅渲染前 {MAX_ANOMALY_ROWS_RENDERED} 条异常路由明细（按成本由优到劣）；其余 {truncated} 条已计入上方「异常路由」KPI 计数，
          可缩小时间范围或收紧阈值查看明细
        </div>
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 z-10 bg-card">
              <tr className="text-muted-foreground">
                <th className="py-1 pr-2 text-left">命中规则</th>
                <th className="py-1 pr-2 text-left">日期</th>
                <th className="py-1 pr-2 text-left">订单</th>
                <th className="py-1 pr-2 text-left">路由</th>
                <th className="py-1 pr-2 text-left">标的</th>
                <th className="py-1 pr-2 text-left">交易所</th>
                <th className="py-1 pr-2 text-left">方向</th>
                <th className="py-1 pr-2 text-left">成交金额(本币)</th>
                <th className="py-1 pr-2 text-left">成交金额(USD)</th>
                <th className="py-1 pr-2 text-left">Broker</th>
                <th className="py-1 pr-2 text-left">Algo</th>
                <th className="py-1 pr-2 text-right">完成率</th>
                <th className="py-1 pr-2 text-right">路由参与率</th>
                <th className="py-1 pr-2 text-right">订单参与率</th>
                <th className="py-1 pr-2 text-right">填充笔数</th>
                <th className="py-1 pr-2 text-right">路由股数</th>
                <th className="py-1 pr-2 text-right">成交股数</th>
                <th className="py-1 pr-2 text-right">pnl_vwap</th>
                <th className="py-1 pr-2 text-right">arrival</th>
                <th className="py-1 pr-2 text-right">IS</th>
                <th className="py-1 pr-2 text-right">机会成本</th>
                <th className="py-1 pr-2 text-right">未成交</th>
                <th className="py-1 pr-2 text-right">CVaR</th>
                <th className="py-1 pr-2 text-right">历时</th>
                <th className="py-1 pr-2 text-right">跨日</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, MAX_ANOMALY_ROWS_RENDERED).map((r) => (
                <AnomalyRowView key={`${r.order_id}-${r.route_id}-${r.date}`} r={r} />
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

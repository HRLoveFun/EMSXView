import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { SearchableSelect } from '../SearchableSelect';
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

/** 严重度配色：critical 红 / warning 橙（ADR-0018 两档） */
function severityClass(severity: 'warning' | 'critical'): string {
  return severity === 'critical'
    ? 'bg-destructive/20 text-destructive'
    : 'bg-amber-500/20 text-amber-400';
}

function AnomalyRowView({ r }: { r: TcaAnomalyRow }) {
  return (
    <tr className="border-t border-muted">
      <td className="py-0.5 pr-2 text-left">
        {r.hits.map((h) => (
          <span
            key={h.key}
            className={`mr-1 inline-block rounded px-1.5 py-0.5 text-[10px] ${severityClass(h.severity)}`}
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
      <td className="py-0.5 pr-2 text-right">
        {formatPct(r.completion_rate)}
        {r.overfill ? (
          <span className="ml-1 inline-block rounded bg-destructive/20 px-1 py-0.5 text-[10px] text-destructive">
            超成交
          </span>
        ) : null}
      </td>
      <td className="py-0.5 pr-2 text-right">{formatPct(r.par_rate)}</td>
      <td className="py-0.5 pr-2 text-right">
        {r.order_par_routes != null && r.order_par_routes > 1 ? (
          <>
            {`max ${formatPct(r.order_par_max ?? null)}`}
            <span className="ml-1 inline-block rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
              {`${r.order_par_routes} routes`}
            </span>
          </>
        ) : (
          formatPct(r.order_par_rate)
        )}
        {r.par_suspect ? (
          <span className="ml-1 inline-block rounded bg-destructive/20 px-1 py-0.5 text-[10px] text-destructive">
            &gt;100%
          </span>
        ) : null}
      </td>
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
  // hooks 必须先于早退执行；无 anomaly 时以空集参与计算
  const rows = useMemo(() => anomaly?.rows ?? [], [anomaly]);
  const [marketFilter, setMarketFilter] = useState<string[]>([]);
  const [ruleFilter, setRuleFilter] = useState<string[]>([]);

  const marketMeta = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const row of rows) {
      if (!row.exchange) continue;
      counts[row.exchange] = (counts[row.exchange] ?? 0) + 1;
    }
    return { options: Object.keys(counts).sort(), counts };
  }, [rows]);

  const ruleMeta = useMemo(() => {
    const labels = new Map<string, string>();
    const counts: Record<string, number> = {};
    for (const row of rows) {
      for (const hit of row.hits) {
        if (!labels.has(hit.key)) labels.set(hit.key, hit.label);
        counts[hit.key] = (counts[hit.key] ?? 0) + 1;
      }
    }
    const options = [...labels.keys()].sort((a, b) =>
      (labels.get(a) ?? a).localeCompare(labels.get(b) ?? b),
    );
    return { options, displayNames: Object.fromEntries(labels), counts };
  }, [rows]);

  // 报告作用域变化后旧筛选值可能已不存在（如换了日期区间）：按当前数据裁剪，
  // 否则残留值会把新报告的明细全部隐藏成空表。
  const activeMarketFilter = useMemo(
    () => marketFilter.filter((market) => marketMeta.counts[market] != null),
    [marketFilter, marketMeta],
  );
  const activeRuleFilter = useMemo(
    () => ruleFilter.filter((rule) => ruleMeta.counts[rule] != null),
    [ruleFilter, ruleMeta],
  );

  const filteredRows = useMemo(() => {
    const markets = new Set(activeMarketFilter);
    const rules = new Set(activeRuleFilter);
    if (!markets.size && !rules.size) return rows;
    return rows.filter(
      (row) =>
        (!markets.size || (row.exchange != null && markets.has(row.exchange)))
        && (!rules.size || row.hits.some((hit) => rules.has(hit.key))),
    );
  }, [rows, activeMarketFilter, activeRuleFilter]);

  if (!anomaly) return null;
  const { count } = anomaly;
  const hasFilter = activeMarketFilter.length > 0 || activeRuleFilter.length > 0;
  if (rows.length === 0) {
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
  // 优先使用后端给出的截断计数（count 为全量命中数，rows 可能已被 limit 截断）
  const truncated = anomaly.rows_truncated
    ?? Math.max(0, count - Math.min(rows.length, MAX_ANOMALY_ROWS_RENDERED));
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">异常路由明细（{count} 条）</CardTitle>
      </CardHeader>
      <CardContent>
        {truncated > 0 ? (
          <div className="mb-2 rounded border border-yellow-500/40 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-300">
            已按严重度降序（critical 优先）渲染最严重的前 {MAX_ANOMALY_ROWS_RENDERED} 条；其余 {truncated} 条已计入上方「异常路由」KPI 计数，
            可缩小时间范围或收紧阈值查看明细
            {anomaly.export_ref ? (
              <>
                {" "}
                <a className="underline" href={anomaly.export_ref} download>下载全量明细 CSV</a>
              </>
            ) : null}
          </div>
        ) : null}
        <div className="mb-2 flex flex-wrap items-end gap-2">
          <SearchableSelect
            label="市场"
            ariaLabel="筛选异常市场"
            options={marketMeta.options}
            value={activeMarketFilter}
            onChange={setMarketFilter}
            counts={marketMeta.counts}
            recentScope="report.anomaly.markets"
            columns={2}
            triggerClassName="w-36"
          />
          <SearchableSelect
            label="命中规则"
            ariaLabel="筛选异常命中规则"
            options={ruleMeta.options}
            value={activeRuleFilter}
            onChange={setRuleFilter}
            displayNames={ruleMeta.displayNames}
            counts={ruleMeta.counts}
            recentScope="report.anomaly.rules"
            columns={2}
            triggerClassName="w-44"
          />
          <span className="pb-2 text-xs text-muted-foreground">
            显示 {filteredRows.length} / {rows.length} 条
          </span>
          {hasFilter ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-9 text-xs"
              onClick={() => {
                setMarketFilter([]);
                setRuleFilter([]);
              }}
            >
              清除筛选
            </Button>
          ) : null}
        </div>
        {filteredRows.length === 0 ? (
          <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
            当前筛选无匹配明细
          </div>
        ) : (
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
                <th className="py-1 pr-2 text-right">订单参与率（多路由为 max）</th>
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
              {filteredRows.slice(0, MAX_ANOMALY_ROWS_RENDERED).map((r) => (
                <AnomalyRowView key={`${r.order_id}-${r.route_id}-${r.date}`} r={r} />
              ))}
            </tbody>
          </table>
        </div>
        )}
      </CardContent>
    </Card>
  );
}

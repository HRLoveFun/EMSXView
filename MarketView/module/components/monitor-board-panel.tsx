/**
 * 监控台（057 节点一）：高亮信息面板 + 监控表。
 *
 * 三个高亮模块（Liquidity / Volatility / Risk notes）与表内同名三列同源同值——
 * 全部由后端 `monitor-board` 一次装配返回，前端不做二次判定，避免「面板说异常、
 * 表里正常」。
 *
 * 表内 Last / Chg % / Total Vol 优先用 core 的实时行情（`useMarketStateStream`），
 * 无订阅或休市时回落到当日 bar 聚合值；两者来源都在表头 chip 与行 tooltip 标注。
 */

import { useEffect, useMemo, useState } from 'react';

import { useAsyncData } from '@shared/hooks/use-async-data';

import { fetchMonitorBoard } from '../services/api';
import { fmtSignedPercent, liveVolumeVsAdvPct, pctToneClass } from '../lib/workspace';
import {
  fmtCompact,
  fmtNumber,
  fmtPercent,
  getSeverityText,
  getSeverityTone,
  renderMarketStatusBadge,
  renderSecurityName,
} from '../marketview-utils';
import type {
  LiveQuotes,
  MarketAlertSeverity,
  MonitorHighlightItem,
  MonitorRow,
} from '../types';

interface MonitorBoardPanelProps {
  poolId?: string;
  tradeDate?: string | null;
  live: LiveQuotes;
  names: Map<string, string>;
  selectedTicker: string | null;
  onSelectTicker: (ticker: string) => void;
  onUniverseChange?: (tickers: string[]) => void;
}

const EMPTY_TEXT: Record<string, string> = {
  liquidity: '无量比异常',
  volatility: '无波动异常',
  risk_notes: '无数据风险提示',
};

const severityRank = (severity: MarketAlertSeverity): number =>
  severity === 'critical' ? 2 : severity === 'warning' ? 1 : 0;

const SeverityCell = ({ severity }: { severity: MarketAlertSeverity }) => {
  if (severity === 'none' || severity === 'normal') {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${getSeverityTone(severity)}`}
    >
      {getSeverityText(severity)}
    </span>
  );
};

/** ticker → 交易所码（'MC EU Equity' → 'EU'）；用于市场层聚合。 */
const marketOf = (equTicker: string): string => {
  const parts = equTicker.split(' ');
  return (parts.length >= 2 ? parts[parts.length - 2] : '').toUpperCase() || '?';
};

interface HighlightModuleProps {
  title: string;
  metricHint: string;
  items: MonitorHighlightItem[];
  emptyText: string;
  selectedTicker: string | null;
  onSelectTicker: (ticker: string) => void;
  /** 统一折叠：为 true 时只保留标题行，市场层与股票列表整体收起 */
  collapsed: boolean;
}

const HighlightModule = ({
  title,
  metricHint,
  items,
  emptyText,
  selectedTicker,
  onSelectTicker,
  collapsed,
}: HighlightModuleProps) => {
  // 市场层多选：点击市场展开其信号股票，再次点击反选取消
  const [openMarkets, setOpenMarkets] = useState<ReadonlySet<string>>(new Set());

  const groups = useMemo(() => {
    const map = new Map<string, MonitorHighlightItem[]>();
    for (const item of items) {
      const key = marketOf(item.equ_ticker);
      map.set(key, [...(map.get(key) ?? []), item]);
    }
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [items]);

  const visibleItems = useMemo(
    () => groups.flatMap(([market, list]) => (openMarkets.has(market) ? list : [])),
    [groups, openMarkets],
  );

  const toggleMarket = (market: string): void => {
    setOpenMarkets((current) => {
      const next = new Set(current);
      if (next.has(market)) {
        next.delete(market);
      } else {
        next.add(market);
      }
      return next;
    });
  };

  return (
    <div
      role="group"
      aria-label={title}
      className={`flex flex-col rounded-xl border border-border/70 bg-background/60 p-3 ${
        collapsed ? '' : 'h-[320px]'
      }`}
    >
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <span className="text-[11px] text-muted-foreground">{items.length} alert(s)</span>
      </div>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{metricHint}</p>
      {collapsed ? null : (
        <>
          <div className="mt-2 flex min-h-[28px] flex-wrap gap-1.5">
            {groups.length ? (
              groups.map(([market, list]) => {
                const active = openMarkets.has(market);
                return (
                  <button
                    key={market}
                    type="button"
                    aria-pressed={active}
                    onClick={() => toggleMarket(market)}
                    className={`rounded-full border px-2 py-1 text-[11px] transition ${
                      active
                        ? 'border-sky-500/60 bg-sky-500/10 text-sky-700'
                        : 'border-border/60 text-muted-foreground hover:text-foreground'
                    }`}
                    title={`点击展开/收起 ${market} 的信号股票`}
                  >
                    {market} · {list.length}
                  </button>
                );
              })
            ) : (
              <span className="text-[11px] text-muted-foreground">{emptyText}</span>
            )}
          </div>
          <ul className="mt-2 flex-1 space-y-1.5 overflow-y-auto">
            {visibleItems.length ? (
              visibleItems.map((item) => (
                <li key={`${item.metric}-${item.equ_ticker}`}>
                  <button
                    type="button"
                    onClick={() => onSelectTicker(item.equ_ticker)}
                    className={`w-full rounded-lg border px-2 py-1.5 text-left transition hover:bg-muted/40 ${
                      selectedTicker === item.equ_ticker ? 'border-sky-500/60' : 'border-border/60'
                    }`}
                    title={item.note || item.threshold}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-xs text-foreground">{item.equ_ticker}</span>
                      <span
                        className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] ${getSeverityTone(item.severity)}`}
                      >
                        {getSeverityText(item.severity)}
                      </span>
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                      {item.note || item.metric}
                    </span>
                  </button>
                </li>
              ))
            ) : (
              <li className="rounded-lg border border-dashed border-border/60 px-2 py-2 text-[11px] text-muted-foreground">
                {groups.length ? '点击市场查看信号股票' : emptyText}
              </li>
            )}
          </ul>
        </>
      )}
    </div>
  );
};

const Row = ({
  row,
  name,
  live,
  selected,
  onSelect,
}: {
  row: MonitorRow;
  name?: string;
  live: LiveQuotes;
  selected: boolean;
  onSelect: () => void;
}) => {
  const quote = live.byTicker.get(row.equ_ticker);
  const usingLive = quote?.last != null;
  const last = usingLive ? quote?.last : row.last;
  const chg = usingLive ? quote?.pct_change_1d : row.chg_pct;
  const volume = usingLive ? (quote?.volume ?? row.total_volume) : row.total_volume;
  const volVsAdv = usingLive ? liveVolumeVsAdvPct(volume, row.adv_20d) : row.vol_vs_adv20;
  const notes = row.risk_notes.join('；');

  return (
    <tr
      className={`cursor-pointer border-t border-border/60 transition hover:bg-muted/30 ${
        selected ? 'bg-sky-500/5' : ''
      }`}
      onClick={onSelect}
      title={`${row.equ_ticker} · bars ${row.bar_count} · ${row.first_bar_time ?? '—'}–${row.last_bar_time ?? '—'} · trade_date ${row.trade_date ?? '—'} · baseline ${row.baseline_date ?? '—'}`}
    >
      <td className="px-3 py-2 font-mono text-xs font-medium text-foreground">
        {row.equ_ticker}
        {usingLive ? (
          <span className="ml-1 text-[10px] text-emerald-600" title="Last/Chg/Vol 来自实时行情">
            ●
          </span>
        ) : null}
      </td>
      <td className="px-3 py-2 text-xs">{renderSecurityName(name ?? row.name)}</td>
      <td className="px-3 py-2">{renderMarketStatusBadge(row.market_status, row.market_time)}</td>
      <td className="px-3 py-2 text-right font-mono">{fmtNumber(last, 2)}</td>
      <td className={`px-3 py-2 text-right font-mono ${pctToneClass(chg)}`}>{fmtSignedPercent(chg)}</td>
      <td className="px-3 py-2 text-right font-mono">{fmtNumber(row.close, 2)}</td>
      <td className="px-3 py-2 text-right font-mono">{fmtCompact(volume)}</td>
      <td className="px-3 py-2 text-right font-mono">{fmtCompact(row.adv_20d)}</td>
      <td className="px-3 py-2 text-right font-mono">{fmtPercent(volVsAdv, 1)}</td>
      <td className="px-3 py-2 text-right font-mono">{fmtPercent(row.daily_volatility, 1)}</td>
      <td className="px-3 py-2 text-right font-mono">{fmtPercent(row.intraday_volatility, 2)}</td>
      <td className="px-3 py-2 text-center">
        <SeverityCell severity={row.liquidity} />
      </td>
      <td className="px-3 py-2 text-center">
        <SeverityCell severity={row.volatility} />
      </td>
      <td
        className={`px-3 py-2 text-xs ${notes ? 'text-amber-600' : 'text-muted-foreground'}`}
        title={notes}
      >
        <span className="block max-w-[240px] truncate">{notes || '—'}</span>
      </td>
    </tr>
  );
};

export const MonitorBoardPanel = ({
  poolId,
  tradeDate,
  live,
  names,
  selectedTicker,
  onSelectTicker,
  onUniverseChange,
}: MonitorBoardPanelProps) => {
  const key = `${poolId ?? ''}|${tradeDate ?? ''}`;
  const { data, isLoading, error, reload } = useAsyncData(key, () =>
    fetchMonitorBoard(poolId, tradeDate ?? undefined),
  );
  // 三个高亮模块统一折叠 / 展开
  const [modulesCollapsed, setModulesCollapsed] = useState(false);

  useEffect(() => {
    if (!data?.rows.length) return;
    onUniverseChange?.(data.rows.map((row) => row.equ_ticker));
  }, [data, onUniverseChange]);

  const highlights = data?.highlights;
  const liveCount = live.byTicker.size;
  const liveChip = !live.enabled
    ? 'live off'
    : live.status === 'live'
      ? `${liveCount} live`
      : live.status === 'polling'
        ? `${liveCount} live · REST`
        : 'live 连接中';

  const rows = useMemo(() => data?.rows ?? [], [data]);
  const maxSeverity = useMemo(
    () => rows.reduce((max, row) => Math.max(max, severityRank(row.volatility), severityRank(row.liquidity)), 0),
    [rows],
  );

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border/70 bg-background/70 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-foreground">
              {data?.pool.label ?? 'Monitor board'}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {data?.pool.description ?? '池成员来自配置；指数成分股表就绪后切换（DL-31）。'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="rounded-full border border-border px-3 py-1">
              pool {data?.pool.pool_id ?? '—'} · {data?.pool.source ?? '—'}
            </span>
            <span className="rounded-full border border-border px-3 py-1">
              trade date {data?.trade_date ?? '—'}
            </span>
            <span className="rounded-full border border-border px-3 py-1">
              {data?.row_count ?? 0} rows
            </span>
            <span
              className={`rounded-full border px-3 py-1 ${
                maxSeverity >= 2 ? 'border-red-500/40 text-red-600' : 'border-border'
              }`}
            >
              {maxSeverity >= 2 ? 'critical present' : maxSeverity === 1 ? 'warning present' : 'no alert'}
            </span>
            <span
              className={`rounded-full border px-3 py-1 ${live.status === 'live' ? 'border-emerald-500/40 text-emerald-600' : 'border-border'}`}
              title={live.asOf ? `行情时间 ${live.asOf}` : '尚无实时行情'}
            >
              {liveChip}
            </span>
            <button
              type="button"
              className="rounded-full border border-border px-3 py-1 transition hover:text-foreground"
              onClick={() => setModulesCollapsed((current) => !current)}
            >
              {modulesCollapsed ? '展开模块' : '折叠模块'}
            </button>
            <button
              type="button"
              className="rounded-full border border-border px-3 py-1 transition hover:text-foreground"
              onClick={() => reload()}
            >
              Refresh
            </button>
          </div>
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          口径：Last / Chg % / Total Vol 优先实时行情、否则当日 10 秒 bar 聚合；Close 为前收盘（涨跌幅基准）；
          ADV 20D / Daily Vol / Intraday Vol 取日度基线，逐行 baseline 日期见行 tooltip。
        </p>
      </div>

      {isLoading ? (
        <div className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
          Loading monitor board…
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-6 text-sm text-red-700">
          {error.message}
        </div>
      ) : data ? (
        <>
          <div className="grid gap-3 xl:grid-cols-3">
            <HighlightModule
              title="Liquidity"
              metricHint="量比越阈（ADV20 的 2×/5× 或 0.5×/0.25×）"
              items={highlights?.liquidity ?? []}
              emptyText={EMPTY_TEXT.liquidity}
              selectedTicker={selectedTicker}
              onSelectTicker={onSelectTicker}
              collapsed={modulesCollapsed}
            />
            <HighlightModule
              title="Volatility"
              metricHint="日波动 ≥25/40 或日内波动 ≥2/3"
              items={highlights?.volatility ?? []}
              emptyText={EMPTY_TEXT.volatility}
              selectedTicker={selectedTicker}
              onSelectTicker={onSelectTicker}
              collapsed={modulesCollapsed}
            />
            <HighlightModule
              title="Risk notes"
              metricHint="数据缺口 / 基线滞后 / 涨跌越阈"
              items={highlights?.risk_notes ?? []}
              emptyText={EMPTY_TEXT.risk_notes}
              selectedTicker={selectedTicker}
              onSelectTicker={onSelectTicker}
              collapsed={modulesCollapsed}
            />
          </div>

          <div className="overflow-hidden rounded-xl border border-border">
            {data.rows.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1420px] text-sm">
                  <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="px-3 py-3 text-left font-medium">Ticker</th>
                      <th className="px-3 py-3 text-left font-medium">Name</th>
                      <th className="px-3 py-3 text-left font-medium">Status</th>
                      <th className="px-3 py-3 text-right font-medium">Last</th>
                      <th className="px-3 py-3 text-right font-medium">Chg %</th>
                      <th className="px-3 py-3 text-right font-medium">Close</th>
                      <th className="px-3 py-3 text-right font-medium">Total Vol</th>
                      <th className="px-3 py-3 text-right font-medium">ADV 20D</th>
                      <th className="px-3 py-3 text-right font-medium">Vol / ADV20</th>
                      <th className="px-3 py-3 text-right font-medium">Daily Vol</th>
                      <th className="px-3 py-3 text-right font-medium">Intraday Vol</th>
                      <th className="px-3 py-3 text-center font-medium">Liquidity</th>
                      <th className="px-3 py-3 text-center font-medium">Volatility</th>
                      <th className="px-3 py-3 text-left font-medium">Risk notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((row) => (
                      <Row
                        key={row.equ_ticker}
                        row={row}
                        name={names.get(row.equ_ticker)}
                        live={live}
                        selected={selectedTicker === row.equ_ticker}
                        onSelect={() => onSelectTicker(row.equ_ticker)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-6 text-sm text-muted-foreground">
                Pool “{data.pool.pool_id}” has no members yet.
              </div>
            )}
          </div>

          <p className="text-[11px] text-muted-foreground">
            表行的 Last / Chg% / Total Vol 若带 ● 表示当前用实时行情；点击任意行打开三联图详情
            （价格—成交量分布 / 累计量 / 累计量占比）。
          </p>
        </>
      ) : null}
    </div>
  );
};

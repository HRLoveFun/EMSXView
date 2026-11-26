/**
 * 监控台（057 节点一）：高亮信息面板 + 监控表。
 *
 * 三个高亮模块（Liquidity / Volatility / Risk notes）与表内同名三列同源同值——
 * 全部由后端 `monitor-board` 一次装配返回，前端不做二次判定，避免「面板说异常、
 * 表里正常」。
 *
 * 交互约定：
 * - 市场标签所有模块共享：点一次市场，三个模块同时只看该市场的信号股票；
 *   支持多选、反选取消，并提供一键全选 / 一键反选。
 * - 表格 Exchange / Status / Liquidity / Volatility / Risk notes 五列可点击表头
 *   打开筛选面板（多选、反选取消、全选 / 反选）。
 * - 表内 Last / Chg % / Total Vol 优先用 core 的实时行情（`useMarketStateStream`），
 *   无订阅或休市时回落到当日 bar 聚合值；来源在表头 chip 与行 tooltip 标注。
 */

import { useEffect, useMemo, useState } from 'react';

import { useAsyncData } from '@shared/hooks/use-async-data';

import { fetchMonitorBoard } from '../services/api';
import {
  FILTER_COLUMNS,
  effectiveSelection,
  marketOf,
  rowValues,
  severityRank,
  uniqueValues,
  type FilterKey,
  type FilterState,
} from './monitor-board/filters';
import {
  FilterPanel,
  FilterableHeader,
  HighlightModule,
  Row,
} from './monitor-board/parts';
import type { LiveQuotes } from '../types';

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
  liquidity: 'No liquidity alerts',
  volatility: 'No volatility alerts',
  risk_notes: 'No risk notes',
};

// ── 面板 ────────────────────────────────────────────────────────────────────

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
  // 市场标签所有模块共享（多选，空 = 未选）
  const [selectedMarkets, setSelectedMarkets] = useState<ReadonlySet<string>>(new Set());
  const [filters, setFilters] = useState<FilterState>({});
  const [openFilter, setOpenFilter] = useState<FilterKey | null>(null);

  useEffect(() => {
    if (!data?.rows.length) return;
    onUniverseChange?.(data.rows.map((row) => row.equ_ticker));
  }, [data, onUniverseChange]);

  const rows = useMemo(() => data?.rows ?? [], [data]);
  const highlights = data?.highlights;

  // 市场标签：跨三个模块取并集，计数为去重后的信号股票数
  const marketBuckets = useMemo(() => {
    const map = new Map<string, Set<string>>();
    const all = [
      ...(highlights?.liquidity ?? []),
      ...(highlights?.volatility ?? []),
      ...(highlights?.risk_notes ?? []),
    ];
    for (const item of all) {
      const market = marketOf(item.equ_ticker);
      const set = map.get(market) ?? new Set<string>();
      set.add(item.equ_ticker);
      map.set(market, set);
    }
    return Array.from(map.entries())
      .map(([market, tickers]) => ({ market, count: tickers.size }))
      .sort((a, b) => a.market.localeCompare(b.market));
  }, [highlights]);

  const toggleMarket = (market: string): void => {
    setSelectedMarkets((current) => {
      const next = new Set(current);
      if (next.has(market)) {
        next.delete(market);
      } else {
        next.add(market);
      }
      return next;
    });
  };
  const selectAllMarkets = (): void =>
    setSelectedMarkets(new Set(marketBuckets.map((bucket) => bucket.market)));
  const invertMarkets = (): void =>
    setSelectedMarkets((current) => {
      const all = marketBuckets.map((bucket) => bucket.market);
      return new Set(all.filter((market) => !current.has(market)));
    });

  // 列筛选：选项来自当前行集合；选择为空表示不筛选
  const filterOptions = useMemo(() => {
    const result = {} as Record<FilterKey, string[]>;
    for (const column of FILTER_COLUMNS) {
      result[column] = uniqueValues(rows, column);
    }
    return result;
  }, [rows]);

  const visibleRows = useMemo(
    () =>
      rows.filter((row) =>
        FILTER_COLUMNS.every((column) => {
          const selection = filters[column];
          if (!selection) return true;
          return rowValues(row, column).some((value) => selection.includes(value));
        }),
      ),
    [rows, filters],
  );

  const toggleFilterValue = (column: FilterKey, value: string): void => {
    const options = filterOptions[column];
    setFilters((current) => {
      const selection = effectiveSelection(current, column, options);
      const next = selection.includes(value)
        ? selection.filter((item) => item !== value)
        : [...selection, value];
      return { ...current, [column]: next.length === options.length ? undefined : next };
    });
  };
  const selectAllValues = (column: FilterKey): void =>
    setFilters((current) => ({ ...current, [column]: undefined }));
  const invertValues = (column: FilterKey): void => {
    const options = filterOptions[column];
    setFilters((current) => {
      const selection = effectiveSelection(current, column, options);
      const next = options.filter((value) => !selection.includes(value));
      return { ...current, [column]: next.length === options.length ? undefined : next };
    });
  };

  const liveCount = live.byTicker.size;
  const liveChip = !live.enabled
    ? 'live off'
    : live.status === 'live'
      ? `${liveCount} live`
      : live.status === 'polling'
        ? `${liveCount} live · REST`
        : 'live connecting';

  const maxSeverity = useMemo(
    () => rows.reduce((max, row) => Math.max(max, severityRank(row.volatility), severityRank(row.liquidity)), 0),
    [rows],
  );

  const activeFilter = openFilter ? filters[openFilter] : undefined;
  const activeSelection = openFilter
    ? (activeFilter ?? filterOptions[openFilter])
    : [];

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border/70 bg-background/70 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-foreground">
              {data?.pool.label ?? 'Monitor board'}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {data?.pool.description ??
                'Pool members come from config; switches to index constituents once the table lands (DL-31).'}
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
              title={live.asOf ? `Quote time ${live.asOf}` : 'No live quotes yet'}
            >
              {liveChip}
            </span>
            <button
              type="button"
              className="rounded-full border border-border px-3 py-1 transition hover:text-foreground"
              onClick={() => setModulesCollapsed((current) => !current)}
            >
              {modulesCollapsed ? 'Expand modules' : 'Collapse modules'}
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
          Basis: Last / Chg % / Total Vol prefer the live feed, else today&apos;s 10-second bar aggregate; Close is the
          previous close (change base); ADV 20D / Daily Vol / Intraday Vol come from the daily baseline — per-row
          baseline date in the row tooltip.
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
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Markets</span>
              {marketBuckets.length ? (
                marketBuckets.map(({ market, count }) => {
                  const active = selectedMarkets.has(market);
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
                      title={`Click to show/hide ${market} signals (shared by all modules)`}
                    >
                      {market} · {count}
                    </button>
                  );
                })
              ) : (
                <span className="text-[11px] text-muted-foreground">No markets with signals</span>
              )}
              <button
                type="button"
                className="rounded-full border border-border px-2 py-1 text-[11px] text-muted-foreground transition hover:text-foreground"
                onClick={selectAllMarkets}
              >
                Select all markets
              </button>
              <button
                type="button"
                className="rounded-full border border-border px-2 py-1 text-[11px] text-muted-foreground transition hover:text-foreground"
                onClick={invertMarkets}
              >
                Invert markets
              </button>
            </div>

            <div className="grid gap-3 xl:grid-cols-3">
              <HighlightModule
                title="Liquidity"
                metricHint="Vol/ADV20 ≥2×/5× or ≤0.5×/0.25×"
                items={highlights?.liquidity ?? []}
                emptyText={EMPTY_TEXT.liquidity}
                selectedTicker={selectedTicker}
                onSelectTicker={onSelectTicker}
                collapsed={modulesCollapsed}
                selectedMarkets={selectedMarkets}
              />
              <HighlightModule
                title="Volatility"
                metricHint="Daily vol ≥25/40 or intraday ≥2/3"
                items={highlights?.volatility ?? []}
                emptyText={EMPTY_TEXT.volatility}
                selectedTicker={selectedTicker}
                onSelectTicker={onSelectTicker}
                collapsed={modulesCollapsed}
                selectedMarkets={selectedMarkets}
              />
              <HighlightModule
                title="Risk notes"
                metricHint="Gaps / stale baseline / large move"
                items={highlights?.risk_notes ?? []}
                emptyText={EMPTY_TEXT.risk_notes}
                selectedTicker={selectedTicker}
                onSelectTicker={onSelectTicker}
                collapsed={modulesCollapsed}
                selectedMarkets={selectedMarkets}
              />
            </div>
          </div>

          {/* relative 包裹：筛选弹层浮在表格上方居中，不被 overflow 裁切 */}
          <div className="relative">
            <div className="overflow-hidden rounded-xl border border-border">
              {visibleRows.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1500px] text-sm">
                  <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <FilterableHeader
                        filterKey="exchange"
                        filters={filters}
                        options={filterOptions.exchange}
                        onOpen={() => setOpenFilter('exchange')}
                      />
                      <th className="px-3 py-3 text-left font-medium">Ticker</th>
                      <th className="px-3 py-3 text-left font-medium">Name</th>
                      <FilterableHeader
                        filterKey="status"
                        filters={filters}
                        options={filterOptions.status}
                        onOpen={() => setOpenFilter('status')}
                      />
                      <th className="px-3 py-3 text-right font-medium">Last</th>
                      <th className="px-3 py-3 text-right font-medium">Chg %</th>
                      <th className="px-3 py-3 text-right font-medium">Close</th>
                      <th className="px-3 py-3 text-right font-medium">Total Vol</th>
                      <th className="px-3 py-3 text-right font-medium">ADV 20D</th>
                      <th className="px-3 py-3 text-right font-medium">Vol / ADV20</th>
                      <th className="px-3 py-3 text-right font-medium">Daily Vol</th>
                      <th className="px-3 py-3 text-right font-medium">Intraday Vol</th>
                      <FilterableHeader
                        filterKey="liquidity"
                        filters={filters}
                        options={filterOptions.liquidity}
                        onOpen={() => setOpenFilter('liquidity')}
                      />
                      <FilterableHeader
                        filterKey="volatility"
                        filters={filters}
                        options={filterOptions.volatility}
                        onOpen={() => setOpenFilter('volatility')}
                      />
                      <FilterableHeader
                        filterKey="riskNotes"
                        filters={filters}
                        options={filterOptions.riskNotes}
                        onOpen={() => setOpenFilter('riskNotes')}
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((row) => (
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
                {rows.length
                  ? 'No rows under the current filters — adjust the column filters.'
                  : `Pool “${data.pool.pool_id}” has no members yet.`}
              </div>
            )}
            </div>
            {openFilter ? (
              <FilterPanel
                filterKey={openFilter}
                options={filterOptions[openFilter]}
                selection={activeSelection}
                onToggleValue={(value) => toggleFilterValue(openFilter, value)}
                onSelectAll={() => selectAllValues(openFilter)}
                onInvert={() => invertValues(openFilter)}
                onClose={() => setOpenFilter(null)}
              />
            ) : null}
          </div>

          <p className="text-[11px] text-muted-foreground">
            Rows with ● use the live feed for Last / Chg% / Total Vol. Click any row to open the three-chart detail
            (price × volume, cumulative volume, cumulative share).
          </p>
        </>
      ) : null}
    </div>
  );
};

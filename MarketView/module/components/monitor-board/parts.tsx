/** MonitorBoardPanel presentational parts (A14/229). */
/* eslint-disable react-refresh/only-export-components */

import { useMemo, useRef } from 'react';

import { useClickOutside } from '@shared/hooks/use-click-outside';

import { fmtSignedPercent, liveVolumeVsAdvPct, pctToneClass } from '../../lib/workspace';
import {
  fmtCompact,
  fmtNumber,
  fmtPercent,
  getSeverityText,
  getSeverityTone,
  renderMarketStatusBadge,
  renderSecurityName,
} from '../../marketview-utils';
import type {
  LiveQuotes,
  MarketAlertSeverity,
  MonitorHighlightItem,
  MonitorRow,
} from '../../types';
import {
  FILTER_LABELS,
  isFiltered,
  marketOf,
  valueLabel,
  type FilterKey,
  type FilterState,
} from './filters';

export const SeverityCell = ({ severity }: { severity: MarketAlertSeverity }) => {
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

// ── 高亮模块 ────────────────────────────────────────────────────────────────

export interface HighlightModuleProps {
  title: string;
  metricHint: string;
  items: MonitorHighlightItem[];
  emptyText: string;
  selectedTicker: string | null;
  onSelectTicker: (ticker: string) => void;
  /** 统一折叠：为 true 时只保留标题行，股票列表整体收起 */
  collapsed: boolean;
  /** 共享市场选择：为空 = 未选市场，模块不展开股票 */
  selectedMarkets: ReadonlySet<string>;
}

export const HighlightModule = ({
  title,
  metricHint,
  items,
  emptyText,
  selectedTicker,
  onSelectTicker,
  collapsed,
  selectedMarkets,
}: HighlightModuleProps) => {
  const visibleItems = useMemo(
    () => items.filter((item) => selectedMarkets.has(marketOf(item.equ_ticker))),
    [items, selectedMarkets],
  );

  return (
    <div
      role="group"
      aria-label={title}
      className={`flex flex-col rounded-xl border border-border/70 bg-background/60 p-3 ${
        collapsed ? '' : 'h-[300px]'
      }`}
    >
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <span className="text-[11px] text-muted-foreground">{items.length} alert(s)</span>
      </div>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{metricHint}</p>
      {collapsed ? null : (
        <ul className="mt-2 flex-1 space-y-1 overflow-y-auto">
          {visibleItems.length ? (
            visibleItems.map((item) => (
              <li key={`${item.metric}-${item.equ_ticker}`}>
                <button
                  type="button"
                  onClick={() => onSelectTicker(item.equ_ticker)}
                  className={`w-full rounded-lg border px-2 py-1 text-left transition hover:bg-muted/40 ${
                    selectedTicker === item.equ_ticker ? 'border-sky-500/60' : 'border-border/60'
                  }`}
                  title={item.note || item.threshold}
                >
                  <span className="flex items-center gap-1">
                    <span className="max-w-[45%] shrink-0 truncate font-mono text-[11px] text-foreground">
                      {item.equ_ticker}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">
                      {item.note || item.metric}
                    </span>
                    <span
                      className={`shrink-0 rounded-full border px-1.5 text-[9px] ${getSeverityTone(item.severity)}`}
                    >
                      {getSeverityText(item.severity)}
                    </span>
                  </span>
                </button>
              </li>
            ))
          ) : (
            <li className="rounded-lg border border-dashed border-border/60 px-2 py-1.5 text-[11px] text-muted-foreground">
              {items.length
                ? selectedMarkets.size
                  ? 'No signals in the selected market'
                  : 'Select a market above to list signals'
                : emptyText}
            </li>
          )}
        </ul>
      )}
    </div>
  );
};

// ── 表格筛选面板 ────────────────────────────────────────────────────────────

/** 列筛选弹层：浮在表格上方居中，内容紧密排列。 */
export const FilterPanel = ({
  filterKey,
  options,
  selection,
  onToggleValue,
  onSelectAll,
  onInvert,
  onClose,
}: {
  filterKey: FilterKey;
  options: string[];
  selection: string[];
  onToggleValue: (value: string) => void;
  onSelectAll: () => void;
  onInvert: () => void;
  onClose: () => void;
}) => {
  const panelRef = useRef<HTMLDivElement | null>(null);
  // 点击面板外空白处即关闭；点表头（自身负责 toggle）不算「外部」
  useClickOutside(panelRef, onClose, { ignoreSelector: '[data-filter-trigger]' });

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label={`Filter ${FILTER_LABELS[filterKey]}`}
      className="absolute left-1/2 top-2 z-30 w-[min(560px,92%)] -translate-x-1/2 rounded-xl border border-border bg-card p-2.5 shadow-2xl"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-medium text-foreground">
          Filter · {FILTER_LABELS[filterKey]}
          <span className="ml-1.5 font-normal text-muted-foreground">
            selected {selection.length}/{options.length}
          </span>
        </p>
        <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
          <button type="button" className="rounded-full border border-border px-2 py-0.5" onClick={onSelectAll}>
            Select all
          </button>
          <button type="button" className="rounded-full border border-border px-2 py-0.5" onClick={onInvert}>
            Invert
          </button>
          <button type="button" className="rounded-full border border-border px-2 py-0.5" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap justify-center gap-1">
        {options.map((value) => {
          const active = selection.includes(value);
          return (
            <button
              key={value || 'empty'}
              type="button"
              aria-pressed={active}
              onClick={() => onToggleValue(value)}
              className={`rounded-full border px-2 py-0.5 text-[10px] transition ${
                active
                  ? 'border-sky-500/60 bg-sky-500/10 text-sky-700'
                  : 'border-border/60 text-muted-foreground hover:text-foreground'
              }`}
            >
              {valueLabel(value)}
            </button>
          );
        })}
      </div>
    </div>
  );
};

// ── 表格行 ──────────────────────────────────────────────────────────────────

export const Row = ({
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
  const notes = row.risk_notes.join('; ');

  return (
    <tr
      className={`cursor-pointer border-t border-border/60 transition hover:bg-muted/30 ${
        selected ? 'bg-sky-500/5' : ''
      }`}
      onClick={onSelect}
      title={`${row.equ_ticker} · bars ${row.bar_count} · ${row.first_bar_time ?? '—'}–${row.last_bar_time ?? '—'} · trade_date ${row.trade_date ?? '—'} · baseline ${row.baseline_date ?? '—'}`}
    >
      <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{marketOf(row.equ_ticker)}</td>
      <td className="px-3 py-2 font-mono text-xs font-medium text-foreground">
        {row.equ_ticker}
        {usingLive ? (
          <span className="ml-1 text-[10px] text-emerald-600" title="Last/Chg/Vol from the live feed">
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

export const FilterableHeader = ({
  filterKey,
  filters,
  options,
  onOpen,
}: {
  filterKey: FilterKey;
  filters: FilterState;
  options: string[];
  onOpen: () => void;
}) => {
  const active = isFiltered(filters, filterKey, options);
  return (
    <th className="px-3 py-3 text-left font-medium">
      {/* 按钮化表头：边框 + 底色 + hover，明确「可点击筛选」 */}
      <button
        type="button"
        data-filter-trigger
        aria-haspopup="dialog"
        onClick={onOpen}
        className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium normal-case tracking-normal shadow-sm transition ${
          active
            ? 'border-sky-500/60 bg-sky-500/10 text-sky-700'
            : 'border-border bg-muted/60 text-foreground/80 hover:bg-muted hover:text-foreground'
        }`}
        title={`Click to filter ${FILTER_LABELS[filterKey]}`}
      >
        {FILTER_LABELS[filterKey]}
        <span aria-hidden className="text-[9px] opacity-70">
          ▾
        </span>
      </button>
    </th>
  );
};

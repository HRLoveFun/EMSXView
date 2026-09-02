import { AlertTriangle } from 'lucide-react';

import type { MarketSnapshotRow } from '../types';
import { fmtCompact, fmtNumber, fmtPercent, getSeverityText, renderSeverityBadge } from '../marketview-utils';

interface SnapshotTableProps {
  rows: MarketSnapshotRow[];
  selectedTickers: string[];
  drillTicker: string | null;
  onToggleTicker: (ticker: string) => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
  onDrillToggle: (ticker: string) => void;
}

// 单行风险告警备注
const RiskNotes = ({ row }: { row: MarketSnapshotRow }) => {
  if (!row.alerts.length) {
    return <span>Within current thresholds.</span>;
  }
  return (
    <>
      {row.alerts.map((alert) => (
        <div key={`${row.equ_ticker}-${alert.code}`} className="rounded-lg border border-border/60 bg-background/80 px-2 py-1">
          <div className="font-medium text-foreground">{getSeverityText(alert.severity)}</div>
          <div>{alert.message}</div>
        </div>
      ))}
    </>
  );
};

// 盘前快照表格：候选选择 + 指标展示 + 日内钻取入口
export const SnapshotTable = ({
  rows,
  selectedTickers,
  drillTicker,
  onToggleTicker,
  onSelectAll,
  onClearSelection,
  onDrillToggle,
}: SnapshotTableProps) => (
  <div className="overflow-hidden rounded-xl border border-border">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 bg-muted/20 px-4 py-3 text-sm">
      <div className="flex items-center gap-2 text-muted-foreground">
        <AlertTriangle className="h-4 w-4" />
        Each row comes from the latest daily snapshot and does not include real-time order book data.
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onSelectAll}
          className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition hover:text-foreground"
        >
          Select visible
        </button>
        <button
          type="button"
          onClick={onClearSelection}
          className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition hover:text-foreground"
        >
          Use filtered universe
        </button>
      </div>
    </div>

    <div className="overflow-x-auto">
      <table className="w-full min-w-[1180px] text-sm">
        <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-3 text-left font-medium">Pick</th>
            <th className="px-3 py-3 text-left font-medium">Ticker</th>
            <th className="px-3 py-3 text-right font-medium">Close</th>
            <th className="px-3 py-3 text-right font-medium">Total Vol</th>
            <th className="px-3 py-3 text-right font-medium">ADV 20D</th>
            <th className="px-3 py-3 text-right font-medium">Vol / ADV20</th>
            <th className="px-3 py-3 text-right font-medium">Daily Vol</th>
            <th className="px-3 py-3 text-right font-medium">Intraday Vol</th>
            <th className="px-3 py-3 text-left font-medium">Liquidity</th>
            <th className="px-3 py-3 text-left font-medium">Volatility</th>
            <th className="px-3 py-3 text-left font-medium">Risk notes</th>
            <th className="px-3 py-3 text-right font-medium">Drill</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isSelected = selectedTickers.includes(row.equ_ticker);
            return (
              <tr key={`${row.equ_ticker}-${row.trade_date}`} className="border-t border-border/60 align-top">
                <td className="px-3 py-3">
                  <input
                    aria-label={`Select ${row.equ_ticker}`}
                    checked={isSelected}
                    className="h-4 w-4 rounded border-border"
                    type="checkbox"
                    onChange={() => onToggleTicker(row.equ_ticker)}
                  />
                </td>
                <td className="px-3 py-3 font-medium text-foreground">{row.equ_ticker}</td>
                <td className="px-3 py-3 text-right">{fmtNumber(row.daily_close, 2)}</td>
                <td className="px-3 py-3 text-right">{fmtCompact(row.total_volume)}</td>
                <td className="px-3 py-3 text-right">{fmtCompact(row.adv_20d)}</td>
                <td className="px-3 py-3 text-right">{fmtPercent(row.volume_vs_adv20_pct, 1)}</td>
                <td className="px-3 py-3 text-right">{fmtPercent(row.daily_volatility, 1)}</td>
                <td className="px-3 py-3 text-right">{fmtPercent(row.intraday_volatility, 1)}</td>
                <td className="px-3 py-3">{renderSeverityBadge('Liquidity', row.liquidity_alert)}</td>
                <td className="px-3 py-3">{renderSeverityBadge('Volatility', row.volatility_alert)}</td>
                <td className="px-3 py-3 text-xs leading-5 text-muted-foreground">
                  <RiskNotes row={row} />
                </td>
                <td className="px-3 py-3 text-right">
                  <button
                    type="button"
                    onClick={() => onDrillToggle(row.equ_ticker)}
                    className={`rounded-full border px-3 py-1 text-xs transition ${
                      drillTicker === row.equ_ticker
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-border text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {drillTicker === row.equ_ticker ? 'Hide' : 'Intraday'}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  </div>
);

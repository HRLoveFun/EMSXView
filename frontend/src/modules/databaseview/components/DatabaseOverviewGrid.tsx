import type { DatabaseOverview } from '../types';
import { formatBytes, formatRelativeTime, formatRowCount, healthColor, normalizeTradeDate } from '../lib/format';

interface DatabaseOverviewGridProps {
  items: DatabaseOverview[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
}

export function DatabaseOverviewGrid({ items, selectedKey, onSelect }: DatabaseOverviewGridProps) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {items.map((item) => {
        const latest = normalizeTradeDate(item.latest_trade_date);
        const earliest = normalizeTradeDate(item.earliest_trade_date);
        const isActive = selectedKey === item.key;
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => onSelect(item.key)}
            className={`rounded-xl border p-4 text-left transition-colors ${
              isActive
                ? 'border-primary bg-primary/5 shadow-sm'
                : 'border-border bg-card hover:border-primary/60 hover:bg-muted/40'
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-sm font-semibold">{item.label}</div>
                <div className="text-[11px] text-muted-foreground">{item.key}</div>
              </div>
              <span className={`text-xs font-medium ${healthColor(item.health)}`}>
                {item.health.toUpperCase()}
              </span>
            </div>
            <p className="mt-2 text-xs text-muted-foreground leading-snug">{item.description}</p>
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <dt className="text-muted-foreground">Latest</dt>
              <dd className="font-mono">{latest ?? '—'}</dd>
              <dt className="text-muted-foreground">Earliest</dt>
              <dd className="font-mono">{earliest ?? '—'}</dd>
              <dt className="text-muted-foreground">Rows</dt>
              <dd className="font-mono">{formatRowCount(item.total_rows)}</dd>
              <dt className="text-muted-foreground">Size</dt>
              <dd className="font-mono">{formatBytes(item.size_bytes)}</dd>
              <dt className="text-muted-foreground">Updated</dt>
              <dd className="font-mono">{formatRelativeTime(item.last_modified)}</dd>
            </dl>
          </button>
        );
      })}
    </div>
  );
}
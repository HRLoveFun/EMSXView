// Normalize heterogeneous date formats used by CostView SQLite databases.
// - raw_fills: "YYYY-MM-DD HH:MM:SS" (datetime string)
// - processed_fills / raw_bdib / fill_bdib: "YYYYMMDD" (lex-sorted)
// - nulls / empties: returns null.

export function normalizeTradeDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = String(value).trim();
  if (!trimmed) return null;

  // "YYYYMMDD"
  if (/^\d{8}$/.test(trimmed)) {
    return `${trimmed.slice(0, 4)}-${trimmed.slice(4, 6)}-${trimmed.slice(6, 8)}`;
  }

  // "YYYY-MM-DD..."
  const isoMatch = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (isoMatch) {
    return `${isoMatch[1]}-${isoMatch[2]}-${isoMatch[3]}`;
  }

  return trimmed;
}

export function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function formatRowCount(rows: number): string {
  if (!rows) return '0';
  if (rows >= 1e9) return `${(rows / 1e9).toFixed(2)} B`;
  if (rows >= 1e6) return `${(rows / 1e6).toFixed(2)} M`;
  if (rows >= 1e3) return `${(rows / 1e3).toFixed(1)} K`;
  return rows.toLocaleString();
}

export function formatRelativeTime(iso: string | null): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diffMs = Date.now() - then;
  const diffHr = diffMs / 3.6e6;
  if (diffHr < 1) return `${Math.max(1, Math.round(diffMs / 60000))} min ago`;
  if (diffHr < 24) return `${Math.round(diffHr)} h ago`;
  const diffDay = diffHr / 24;
  if (diffDay < 30) return `${Math.round(diffDay)} d ago`;
  return new Date(iso).toISOString().slice(0, 10);
}

export function healthColor(health: string): string {
  switch (health) {
    case 'ok':
      return 'text-emerald-600';
    case 'stale':
      return 'text-amber-600';
    case 'empty':
    case 'missing':
      return 'text-zinc-500';
    case 'error':
      return 'text-rose-600';
    default:
      return 'text-muted-foreground';
  }
}

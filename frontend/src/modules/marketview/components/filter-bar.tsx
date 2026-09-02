import type { MarketSnapshotRequest, MarketStockPool } from '../types';
import { fromISODateInput, toISODateInput } from '../lib/workspace';

// 数值型筛选键（四个阈值输入框共用同一处理逻辑）
export type NumericQueryKey =
  | 'min_adv_20d'
  | 'min_total_volume'
  | 'min_daily_volatility'
  | 'min_intraday_volatility';

const LIMIT_OPTIONS = [20, 40, 60, 100];

const SORT_OPTIONS: Array<{ value: NonNullable<MarketSnapshotRequest['sort_by']>; label: string }> = [
  { value: 'total_volume', label: 'Total Volume' },
  { value: 'adv_20d', label: 'ADV 20D' },
  { value: 'adv_5d', label: 'ADV 5D' },
  { value: 'daily_volatility', label: 'Daily Volatility' },
  { value: 'intraday_volatility', label: 'Intraday Volatility' },
  { value: 'volume_vs_adv20_pct', label: 'Volume / ADV20' },
  { value: 'equ_ticker', label: 'Ticker' },
  { value: 'liquidity_alert', label: 'Liquidity Alert' },
  { value: 'volatility_alert', label: 'Volatility Alert' },
];

const ALERT_FILTER_OPTIONS = [
  { value: 'all', label: 'All rows' },
  { value: 'warning', label: 'Warning+' },
  { value: 'critical', label: 'Critical only' },
] as const;

interface FilterBarProps {
  query: MarketSnapshotRequest;
  pools: MarketStockPool[];
  activePoolDescription: string | null;
  onPoolChange: (poolId: string) => void;
  onQueryChange: <K extends keyof MarketSnapshotRequest>(key: K, value: MarketSnapshotRequest[K]) => void;
  onReset: () => void;
}

// 数值阈值输入：空串表示清除该筛选条件
const NumericField = ({
  label,
  step,
  placeholder,
  value,
  onChange,
}: {
  label: string;
  step: string;
  placeholder: string;
  value: number | undefined;
  onChange: (raw: string) => void;
}) => (
  <label className="space-y-1 text-sm">
    <span className="text-muted-foreground">{label}</span>
    <input
      className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
      type="number"
      min="0"
      step={step}
      value={value ?? ''}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
    />
  </label>
);

// 筛选控制条：股票池切换 + 阈值/告警/排序/日期筛选 + 重置
export const FilterBar = ({
  query,
  pools,
  activePoolDescription,
  onPoolChange,
  onQueryChange,
  onReset,
}: FilterBarProps) => {
  const updateNumeric = (key: NumericQueryKey, rawValue: string): void => {
    onQueryChange(key, rawValue.trim() === '' ? undefined : Number(rawValue));
  };

  return (
    <div className="mt-5 space-y-4">
      <div className="flex flex-wrap gap-2">
        {pools.map((pool) => {
          const isActive = (query.pool_id ?? 'all') === pool.pool_id;
          return (
            <button
              key={pool.pool_id}
              type="button"
              onClick={() => onPoolChange(pool.pool_id)}
              className={`rounded-full border px-3 py-1.5 text-sm transition ${
                isActive
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border bg-background text-muted-foreground hover:text-foreground'
              }`}
            >
              {pool.label}
            </button>
          );
        })}
      </div>

      <p className="text-sm text-muted-foreground">
        {activePoolDescription
          ?? 'Pools are loaded from the backend adapter so MarketView keeps a single ownership boundary.'}
      </p>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Trade Date</span>
          <input
            className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
            type="date"
            value={toISODateInput(query.trade_date)}
            onChange={(event) => onQueryChange('trade_date', fromISODateInput(event.target.value))}
          />
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Limit</span>
          <select
            className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
            value={query.limit ?? 40}
            onChange={(event) => onQueryChange('limit', Number(event.target.value))}
          >
            {LIMIT_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>

        <NumericField
          label="Min ADV 20D"
          step="1000000"
          placeholder="e.g. 10000000"
          value={query.min_adv_20d}
          onChange={(raw) => updateNumeric('min_adv_20d', raw)}
        />

        <NumericField
          label="Min Total Volume"
          step="1000000"
          placeholder="e.g. 5000000"
          value={query.min_total_volume}
          onChange={(raw) => updateNumeric('min_total_volume', raw)}
        />

        <NumericField
          label="Min Daily Vol"
          step="0.1"
          placeholder="e.g. 25"
          value={query.min_daily_volatility}
          onChange={(raw) => updateNumeric('min_daily_volatility', raw)}
        />

        <NumericField
          label="Min Intraday Vol"
          step="0.1"
          placeholder="e.g. 2.5"
          value={query.min_intraday_volatility}
          onChange={(raw) => updateNumeric('min_intraday_volatility', raw)}
        />

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Liquidity alert</span>
          <select
            className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
            value={query.liquidity_alert ?? 'all'}
            onChange={(event) => onQueryChange('liquidity_alert', event.target.value as MarketSnapshotRequest['liquidity_alert'])}
          >
            {ALERT_FILTER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Volatility alert</span>
          <select
            className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
            value={query.volatility_alert ?? 'all'}
            onChange={(event) => onQueryChange('volatility_alert', event.target.value as MarketSnapshotRequest['volatility_alert'])}
          >
            {ALERT_FILTER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Sort by</span>
          <select
            className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
            value={query.sort_by ?? 'total_volume'}
            onChange={(event) => onQueryChange('sort_by', event.target.value as MarketSnapshotRequest['sort_by'])}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Direction</span>
          <select
            className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
            value={query.sort_direction ?? 'desc'}
            onChange={(event) => onQueryChange('sort_direction', event.target.value as MarketSnapshotRequest['sort_direction'])}
          >
            <option value="desc">Descending</option>
            <option value="asc">Ascending</option>
          </select>
        </label>

        <div className="flex items-end">
          <button
            type="button"
            onClick={onReset}
            className="w-full rounded-xl border border-border bg-background px-3 py-2 text-sm text-muted-foreground transition hover:text-foreground"
          >
            Reset filters
          </button>
        </div>
      </div>
    </div>
  );
};

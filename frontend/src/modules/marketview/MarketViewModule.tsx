import { useEffect, useState } from 'react';
import { Activity, AlertTriangle, ArrowUpDown, Gauge } from 'lucide-react';

import { buildMarketCandidatePayload, countRowsWithSeverity } from './lib/workspace';
import { fetchIntradayFeatures, fetchMarketSnapshot } from './services/api';
import { useHandoffContracts } from '@shared/hooks/use-handoff-contracts';
import { fmtNumber, fmtCompact, fmtPercent, getSeverityTone, getSeverityText, renderSeverityBadge } from './marketview-utils';
import { IntradayFeaturePanel } from './intraday-feature-panel';
import type {
  IntradayBucketMinutes,
  IntradayFeatureSnapshot,
  MarketAlertSeverity,
  MarketSnapshotPayload,
  MarketSnapshotRequest,
} from './types';

const capabilityCards = [
  {
    title: 'Stock Pools',
    description: 'Stock pool definitions are centralized on the MarketView contract, driven by a single daily snapshot path rather than scattered across local page state.',
    icon: Activity,
  },
  {
    title: 'Risk Filters',
    description: 'Pre-market screening by ADV, daily volume, daily volatility, and intraday volatility, with direct exposure of liquidity and volatility alert levels.',
    icon: Gauge,
  },
  {
    title: 'Candidate Hand-Off',
    description: 'Candidate payload already has a clear contract and can be handed off to ExecutionView without requiring a recommendation model.',
    icon: ArrowUpDown,
  },
];

const DEFAULT_QUERY: MarketSnapshotRequest = {
  limit: 40,
  pool_id: 'all',
  liquidity_alert: 'all',
  volatility_alert: 'all',
  sort_by: 'total_volume',
  sort_direction: 'desc',
};

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

type NumericQueryKey =
  | 'min_adv_20d'
  | 'min_total_volume'
  | 'min_daily_volatility'
  | 'min_intraday_volatility';

export default function MarketViewModule() {
  const [query, setQuery] = useState<MarketSnapshotRequest>(DEFAULT_QUERY);
  const [snapshot, setSnapshot] = useState<MarketSnapshotPayload | null>(null);
  const [selectedTickers, setSelectedTickers] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drillTicker, setDrillTicker] = useState<string | null>(null);
  const { publishMarketCandidatesAction, activeCandidateHandoff } = useHandoffContracts();
  const [publishStatus, setPublishStatus] = useState<string | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [drillBucketMinutes, setDrillBucketMinutes] = useState<IntradayBucketMinutes>(30);
  const [drillSnapshot, setDrillSnapshot] = useState<IntradayFeatureSnapshot | null>(null);
  const [drillLoading, setDrillLoading] = useState(false);
  const [drillError, setDrillError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadSnapshot() {
      setIsLoading(true);
      setError(null);
      try {
        const nextSnapshot = await fetchMarketSnapshot(query);
        if (!cancelled) {
          setSnapshot(nextSnapshot);
        }
      } catch (nextError) {
        if (!cancelled) {
          setError(nextError instanceof Error ? nextError.message : 'Failed to load MarketView workstation');
          setSnapshot(null);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadSnapshot();
    return () => {
      cancelled = true;
    };
  }, [
    query.limit,
    query.pool_id,
    query.min_adv_20d,
    query.min_total_volume,
    query.min_daily_volatility,
    query.min_intraday_volatility,
    query.liquidity_alert,
    query.volatility_alert,
    query.sort_by,
    query.sort_direction,
    query.trade_date,
  ]);

  useEffect(() => {
    if (!snapshot) {
      setSelectedTickers([]);
      return;
    }

    setSelectedTickers((current) =>
      current.filter((ticker) => snapshot.rows.some((row) => row.equ_ticker === ticker)),
    );
  }, [snapshot]);

  useEffect(() => {
    if (!drillTicker || !snapshot?.trade_date) {
      setDrillSnapshot(null);
      setDrillError(null);
      return;
    }

    let cancelled = false;
    setDrillLoading(true);
    setDrillError(null);

    fetchIntradayFeatures({
      tickers: [drillTicker],
      trade_date: snapshot.trade_date,
      bucket_minutes: drillBucketMinutes,
    })
      .then((result) => {
        if (!cancelled) {
          setDrillSnapshot(result);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setDrillError(err instanceof Error ? err.message : 'Failed to load intraday features');
          setDrillSnapshot(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDrillLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [drillTicker, drillBucketMinutes, snapshot?.trade_date]);

  function updateQuery<K extends keyof MarketSnapshotRequest>(key: K, value: MarketSnapshotRequest[K]): void {
    setQuery((current) => ({
      ...current,
      [key]: value,
    }));
  }

  function updateNumericQuery(key: NumericQueryKey, rawValue: string): void {
    setQuery((current) => ({
      ...current,
      [key]: rawValue.trim() === '' ? undefined : Number(rawValue),
    }));
  }

  function handlePoolChange(poolId: string): void {
    const nextPool = snapshot?.available_pools.find((pool) => pool.pool_id === poolId);
    setQuery((current) => ({
      ...current,
      pool_id: poolId,
      sort_by: nextPool?.default_sort_by ?? current.sort_by ?? 'total_volume',
      sort_direction: nextPool?.default_sort_direction ?? current.sort_direction ?? 'desc',
    }));
  }

  function toggleTicker(ticker: string): void {
    setSelectedTickers((current) =>
      current.includes(ticker)
        ? current.filter((item) => item !== ticker)
        : [...current, ticker],
    );
  }

  const rows = snapshot?.rows ?? [];
  const criticalCount = countRowsWithSeverity(rows, 'critical');
  const warningCount = countRowsWithSeverity(rows, 'warning');
  const handoffPayload = snapshot ? buildMarketCandidatePayload(snapshot, selectedTickers) : null;
  const activePool = snapshot?.available_pools.find((pool) => pool.pool_id === snapshot.active_pool_id) ?? null;

  return (
    <section className="space-y-6 rounded-2xl border bg-card p-6 shadow-sm">
      <div className="space-y-3">
        <div className="inline-flex items-center rounded-full border border-border bg-background px-3 py-1 text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
          MarketView
        </div>
        <div className="space-y-2">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">Pre-trade workspace</h2>
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
            Here we continue to use the same daily snapshot path, but it is no longer just a fixed table. MarketView now uses stock pools as the entry point, bringing together filtering, sorting, liquidity and volatility alerts, and the candidate contract for subsequent handoff into a pre-trade workspace.
          </p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {capabilityCards.map((card) => (
          <article key={card.title} className="rounded-2xl border border-border/70 bg-background/80 p-5">
            <card.icon className="h-5 w-5 text-primary" />
            <h3 className="mt-4 text-base font-semibold text-foreground">{card.title}</h3>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">{card.description}</p>
          </article>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-4">
        <article className="rounded-2xl border border-border/70 bg-background/70 p-5">
          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Visible rows</div>
          <div className="mt-3 text-3xl font-semibold text-foreground">{snapshot?.row_count ?? 0}</div>
          <p className="mt-2 text-sm text-muted-foreground">Number of candidates in the current stock pool after filtering and sorting.</p>
        </article>
        <article className="rounded-2xl border border-red-500/20 bg-red-500/5 p-5">
          <div className="text-xs uppercase tracking-[0.2em] text-red-700/80">Critical alerts</div>
          <div className="mt-3 text-3xl font-semibold text-red-700">{criticalCount}</div>
          <p className="mt-2 text-sm text-red-700/80">Number of symbols reaching critical level on any dimension.</p>
        </article>
        <article className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-5">
          <div className="text-xs uppercase tracking-[0.2em] text-amber-700/80">Warning alerts</div>
          <div className="mt-3 text-3xl font-semibold text-amber-700">{warningCount}</div>
          <p className="mt-2 text-sm text-amber-700/80">Symbols with at least one warning but not reaching critical level, worth pre-trade attention.</p>
        </article>
        <article className="rounded-2xl border border-border/70 bg-background/70 p-5">
          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Hand-off candidates</div>
          <div className="mt-3 text-3xl font-semibold text-foreground">{handoffPayload?.row_count ?? 0}</div>
          <p className="mt-2 text-sm text-muted-foreground">
            {selectedTickers.length ? 'Handoff payload generated based on explicitly selected tickers.' : 'Defaults to current filter results when nothing is selected.'}
          </p>
          <button
            type="button"
            className="mt-3 inline-flex items-center gap-2 rounded-lg border border-primary/60 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition hover:bg-primary/20 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={isPublishing || !handoffPayload || handoffPayload.row_count === 0}
            onClick={async () => {
              if (!handoffPayload) return;
              setIsPublishing(true);
              setPublishStatus(null);
              try {
                const result = await publishMarketCandidatesAction({
                  pool_id: handoffPayload.pool_id,
                  tickers: selectedTickers.length ? selectedTickers : undefined,
                });
                setPublishStatus(
                  `Delivered to ExecutionView: ${result.candidate_payload.row_count} symbols (trace_id=${result.metadata.trace_id.slice(0, 12)}…)`,
                );
              } catch (err) {
                setPublishStatus(err instanceof Error ? `Send failed: ${err.message}` : 'Send failed');
              } finally {
                setIsPublishing(false);
              }
            }}
          >
            {isPublishing ? 'Sending…' : 'Send to ExecutionView →'}
          </button>
          {publishStatus && (
            <p className="mt-2 text-xs text-muted-foreground">{publishStatus}</p>
          )}
          {activeCandidateHandoff && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              Last handoff: {activeCandidateHandoff.candidate_payload.row_count} candidates,
              {new Date(activeCandidateHandoff.metadata.generated_at).toLocaleString()}
            </p>
          )}
        </article>
      </div>

      <div className="rounded-2xl border border-border/70 bg-background/70 p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-sm font-medium text-foreground">Stock-pool workstation</p>
            <p className="mt-1 text-sm text-muted-foreground">
              The data source is still the latest trading day snapshot from `bdib_daily_summary`, exposed to MarketView through the `platform_data` adapter layer. All filtering and alerts here are based on daily data and do not represent real-time market conditions.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <div className="rounded-full border border-border px-3 py-1">
              {snapshot?.trade_date ? `Trade Date ${snapshot.trade_date}` : 'No snapshot date'}
            </div>
            <div className="rounded-full border border-border px-3 py-1">{activePool?.label ?? 'Stock pool'}</div>
            <div className="rounded-full border border-border px-3 py-1">{rows.length} rows</div>
          </div>
        </div>

        <div className="mt-5 space-y-4">
          <div className="flex flex-wrap gap-2">
            {(snapshot?.available_pools ?? []).map((pool) => {
              const isActive = (query.pool_id ?? 'all') === pool.pool_id;
              return (
                <button
                  key={pool.pool_id}
                  type="button"
                  onClick={() => handlePoolChange(pool.pool_id)}
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
            {activePool?.description
              ?? 'Pools are loaded from the backend adapter so MarketView keeps a single ownership boundary.'}
          </p>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Limit</span>
              <select
                className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
                value={query.limit ?? 40}
                onChange={(event) => updateQuery('limit', Number(event.target.value))}
              >
                {[20, 40, 60, 100].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Min ADV 20D</span>
              <input
                className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
                type="number"
                min="0"
                step="1000000"
                value={query.min_adv_20d ?? ''}
                onChange={(event) => updateNumericQuery('min_adv_20d', event.target.value)}
                placeholder="e.g. 10000000"
              />
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Min Total Volume</span>
              <input
                className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
                type="number"
                min="0"
                step="1000000"
                value={query.min_total_volume ?? ''}
                onChange={(event) => updateNumericQuery('min_total_volume', event.target.value)}
                placeholder="e.g. 5000000"
              />
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Min Daily Vol</span>
              <input
                className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
                type="number"
                min="0"
                step="0.1"
                value={query.min_daily_volatility ?? ''}
                onChange={(event) => updateNumericQuery('min_daily_volatility', event.target.value)}
                placeholder="e.g. 25"
              />
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Min Intraday Vol</span>
              <input
                className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
                type="number"
                min="0"
                step="0.1"
                value={query.min_intraday_volatility ?? ''}
                onChange={(event) => updateNumericQuery('min_intraday_volatility', event.target.value)}
                placeholder="e.g. 2.5"
              />
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Liquidity alert</span>
              <select
                className="w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
                value={query.liquidity_alert ?? 'all'}
                onChange={(event) => updateQuery('liquidity_alert', event.target.value as MarketSnapshotRequest['liquidity_alert'])}
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
                onChange={(event) => updateQuery('volatility_alert', event.target.value as MarketSnapshotRequest['volatility_alert'])}
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
                onChange={(event) => updateQuery('sort_by', event.target.value as MarketSnapshotRequest['sort_by'])}
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
                onChange={(event) => updateQuery('sort_direction', event.target.value as MarketSnapshotRequest['sort_direction'])}
              >
                <option value="desc">Descending</option>
                <option value="asc">Ascending</option>
              </select>
            </label>

            <div className="flex items-end">
              <button
                type="button"
                onClick={() => setQuery(DEFAULT_QUERY)}
                className="w-full rounded-xl border border-border bg-background px-3 py-2 text-sm text-muted-foreground transition hover:text-foreground"
              >
                Reset filters
              </button>
            </div>
          </div>
        </div>

        {isLoading ? (
          <div className="mt-4 rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
            Loading MarketView workstation...
          </div>
        ) : error ? (
          <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/5 p-6 text-sm text-red-700">
            {error}
          </div>
        ) : snapshot && snapshot.rows.length ? (
          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.95fr)]">
            <div className="overflow-hidden rounded-xl border border-border">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 bg-muted/20 px-4 py-3 text-sm">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <AlertTriangle className="h-4 w-4" />
                  Each row comes from the latest daily snapshot and does not include real-time order book data.
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setSelectedTickers(rows.map((row) => row.equ_ticker))}
                    className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition hover:text-foreground"
                  >
                    Select visible
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedTickers([])}
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
                              onChange={() => toggleTicker(row.equ_ticker)}
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
                            {row.alerts.length ? (
                              row.alerts.map((alert) => (
                                <div key={`${row.equ_ticker}-${alert.code}`} className="rounded-lg border border-border/60 bg-background/80 px-2 py-1">
                                  <div className="font-medium text-foreground">{getSeverityText(alert.severity)}</div>
                                  <div>{alert.message}</div>
                                </div>
                              ))
                            ) : (
                              <span>Within current thresholds.</span>
                            )}
                          </td>
                          <td className="px-3 py-3 text-right">
                            <button
                              type="button"
                              onClick={() =>
                                setDrillTicker((current) => (current === row.equ_ticker ? null : row.equ_ticker))
                              }
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

            <aside className="space-y-4 rounded-xl border border-border bg-background/90 p-4">
              <div>
                <p className="text-sm font-medium text-foreground">ExecutionView hand-off preview</p>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  This is the candidate payload contract reserved for ExecutionView. When nothing is selected, the current filter results are used; when tickers are selected, only the explicit candidates are included.
                </p>
              </div>

              <div className="rounded-xl border border-border/70 bg-muted/20 p-4 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Payload source</span>
                  <span className="font-medium text-foreground">{handoffPayload?.source ?? 'N/A'}</span>
                </div>
                <div className="mt-2 flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Handoff target</span>
                  <span className="font-medium text-foreground">{handoffPayload?.handoff_target ?? 'N/A'}</span>
                </div>
                <div className="mt-2 flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Candidate count</span>
                  <span className="font-medium text-foreground">{handoffPayload?.row_count ?? 0}</span>
                </div>
              </div>

              <div className="rounded-xl border border-border/70 bg-background p-4">
                <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap break-all text-xs leading-5 text-muted-foreground">
                  {handoffPayload ? JSON.stringify(handoffPayload, null, 2) : 'No candidate payload available.'}
                </pre>
              </div>

              <div className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
                The current contract only carries daily candidates and risk labels. It does not derive execution recommendations, nor does it mistake the snapshot for a real-time market data stream.
              </div>
            </aside>
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
            No market snapshot data available yet. Run the CostView pipeline through Stage 7 to populate `bdib_daily_summary`.
          </div>
        )}
      </div>

      {drillTicker ? (
        <IntradayFeaturePanel
          ticker={drillTicker}
          bucketMinutes={drillBucketMinutes}
          onBucketMinutesChange={setDrillBucketMinutes}
          snapshot={drillSnapshot}
          loading={drillLoading}
          error={drillError}
          onClose={() => setDrillTicker(null)}
        />
      ) : null}
    </section>
  );
}
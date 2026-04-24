import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BarChart3, Download, RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { fetchScorecard } from '../services/api';
import { useHandoffContracts } from '../../../hooks/use-handoff-contracts';
import {
  DEFAULT_SCORECARD_FORM_STATE,
  loadCostViewScorecardForm,
  saveCostViewScorecardForm,
} from '../lib/storage';
import {
  evaluateCohortSeverity,
  formatAnomalyFlag,
  getSeverityText,
  getSeverityTone,
} from '../lib/thresholds';
import type {
  CostViewConfig,
  CostViewFilterFormState,
  ScorecardCohort,
  ScorecardCohortMetrics,
  ScorecardFormState,
  ScorecardReport,
  TcaFilterPayload,
} from '../types';

interface ScorecardViewProps {
  config: CostViewConfig;
  analysisFilters: CostViewFilterFormState;
}

const COHORT_OPTIONS: Array<{ value: ScorecardCohort; label: string; hint: string }> = [
  { value: 'broker', label: 'Broker', hint: 'Compare brokers across current filter set' },
  { value: 'strategy', label: 'Strategy (algo)', hint: 'Compare broker algorithms by name' },
  { value: 'broker_strategy', label: 'Broker × Strategy', hint: 'Finest-grained broker+algo cell' },
  { value: 'asset_class', label: 'Asset class', hint: 'Derived from Bloomberg ticker suffix' },
  { value: 'time_of_day', label: 'Time of day', hint: 'Open / mid / close buckets from order start time' },
  { value: 'liquidity_adv20', label: 'Liquidity bucket', hint: 'Low / Mid / High participation vs ADV20' },
  { value: 'volatility', label: 'Volatility regime', hint: 'Calm / typical / stressed by daily volatility' },
];

function formatNumber(value: number | null, decimals = 1, suffix = ''): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value.toFixed(decimals)}${suffix}`;
}

function analysisFiltersToPayload(form: CostViewFilterFormState): TcaFilterPayload {
  const payload: TcaFilterPayload = {};
  const orderIds = form.orderIds
    .split(/[\n,]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (orderIds.length) payload.order_ids = orderIds;
  if (form.algo) payload.algo = form.algo;
  if (form.startDate) payload.start_date = form.startDate.replace(/-/g, '');
  if (form.endDate) payload.end_date = form.endDate.replace(/-/g, '');
  if (form.broker) payload.broker = form.broker.trim();
  if (form.symbol) payload.symbol = form.symbol.trim();
  return payload;
}

function toCsv(report: ScorecardReport): string {
  const headers = [
    'cohort',
    'sample_size',
    'avg_tracking_error_bps',
    'median_tracking_error_bps',
    'p95_tracking_error_bps',
    'stddev_tracking_error_bps',
    'avg_fill_pct',
    'avg_volume_pct_adv20',
    'avg_volume_pct_interval',
    'avg_daily_volatility',
    'avg_price_movement_pct',
    'data_quality_ratio',
    'sample_size_warning',
    'anomaly_flags',
  ];
  const rows = report.cohorts.map((cohort) =>
    [
      cohort.cohort_label,
      cohort.sample_size,
      cohort.avg_tracking_error_bps,
      cohort.median_tracking_error_bps,
      cohort.p95_tracking_error_bps,
      cohort.stddev_tracking_error_bps,
      cohort.avg_fill_pct,
      cohort.avg_volume_pct_adv20,
      cohort.avg_volume_pct_interval,
      cohort.avg_daily_volatility,
      cohort.avg_price_movement_pct,
      cohort.data_quality_ratio,
      cohort.sample_size_warning,
      cohort.anomaly_flags.join('|'),
    ]
      .map((value) => (value == null ? '' : String(value).replace(/"/g, '""')))
      .map((value) => (value.includes(',') ? `"${value}"` : value))
      .join(','),
  );
  return [headers.join(','), ...rows].join('\n');
}

function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function ScorecardView({ config, analysisFilters }: ScorecardViewProps) {
  const [formState, setFormState] = useState<ScorecardFormState>(() => loadCostViewScorecardForm());
  const [report, setReport] = useState<ScorecardReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    saveCostViewScorecardForm(formState);
  }, [formState]);

  const runScorecard = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const next = await fetchScorecard({
        cohort: formState.cohort,
        filters: analysisFiltersToPayload(analysisFilters),
        min_sample_size: formState.minSampleSize,
        max_orders: formState.maxOrders,
      });
      setReport(next);
    } catch (cause) {
      setReport(null);
      setError(cause instanceof Error ? cause.message : 'Unknown scorecard error');
    } finally {
      setIsLoading(false);
    }
  }, [analysisFilters, formState]);

  const handleExport = useCallback(() => {
    if (!report) return;
    const name = `costview-scorecard-${report.cohort}-${new Date().toISOString().slice(0, 10)}.csv`;
    downloadCsv(name, toCsv(report));
  }, [report]);

  const eligibleCohorts = useMemo(
    () => report?.cohorts.filter((cohort) => !cohort.sample_size_warning) ?? [],
    [report],
  );
  const underpoweredCohorts = useMemo(
    () => report?.cohorts.filter((cohort) => cohort.sample_size_warning) ?? [],
    [report],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-xl border bg-card p-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Broker & Strategy Scorecard</h2>
          <p className="text-sm text-muted-foreground">
            Aggregated TCA statistics by cohort. Inherits the Analysis tab filters (date range, broker, algo, symbol).
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={runScorecard} disabled={isLoading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
            {report ? 'Rerun' : 'Compute Scorecard'}
          </Button>
          <Button variant="outline" onClick={handleExport} disabled={!report}>
            <Download className="mr-2 h-4 w-4" />Export CSV
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Cohort settings</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <div className="space-y-1">
            <Label htmlFor="scorecard-cohort">Cohort dimension</Label>
            <Select
              value={formState.cohort}
              onValueChange={(value) => setFormState((current) => ({ ...current, cohort: value as ScorecardCohort }))}
            >
              <SelectTrigger id="scorecard-cohort">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COHORT_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {COHORT_OPTIONS.find((option) => option.value === formState.cohort)?.hint}
            </p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="scorecard-min-sample">Minimum sample size</Label>
            <Input
              id="scorecard-min-sample"
              type="number"
              min={1}
              max={1000}
              value={formState.minSampleSize}
              onChange={(event) =>
                setFormState((current) => ({
                  ...current,
                  minSampleSize: Math.max(1, Math.min(1000, Number(event.target.value) || 1)),
                }))
              }
            />
            <p className="text-xs text-muted-foreground">
              Cohorts below this floor are flagged and sorted last to avoid unstable rankings.
            </p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="scorecard-max-orders">Max orders scanned</Label>
            <Input
              id="scorecard-max-orders"
              type="number"
              min={50}
              max={10000}
              step={50}
              value={formState.maxOrders}
              onChange={(event) =>
                setFormState((current) => ({
                  ...current,
                  maxOrders: Math.max(50, Math.min(10000, Number(event.target.value) || 2000)),
                }))
              }
            />
            <p className="text-xs text-muted-foreground">
              Hard cap to bound query cost. When hit, the UI shows a coverage warning.
            </p>
          </div>
          <div className="md:col-span-3">
            <Button size="sm" variant="ghost" onClick={() => setFormState(DEFAULT_SCORECARD_FORM_STATE)}>
              Reset to defaults
            </Button>
          </div>
        </CardContent>
      </Card>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Scorecard request failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {report?.data_source_warning ? (
        <Alert>
          <AlertTitle>Pipeline data incomplete</AlertTitle>
          <AlertDescription>{report.data_source_warning}</AlertDescription>
        </Alert>
      ) : null}

      {report?.total_orders_capped ? (
        <Alert>
          <AlertTitle>Order scan capped</AlertTitle>
          <AlertDescription>
            Reached the max orders scanned limit ({formState.maxOrders}). Narrow the date range or raise the cap for complete coverage.
          </AlertDescription>
        </Alert>
      ) : null}

      {report ? (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <SummaryStat label="Cohorts (eligible)" value={String(eligibleCohorts.length)} />
            <SummaryStat label="Cohorts (small sample)" value={String(underpoweredCohorts.length)} warn={underpoweredCohorts.length > 0} />
            <SummaryStat label="Orders scanned" value={String(report.total_orders_considered)} />
            <SummaryStat label="Generated" value={new Date(report.generated_at).toLocaleString()} />
          </div>
          <ScorecardTable config={config} report={report} cohort={formState.cohort} />
        </>
      ) : (
        <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          <BarChart3 className="mx-auto mb-3 h-6 w-6 opacity-60" />
          Run the scorecard to compare broker/strategy execution across the selected cohort dimension.
        </div>
      )}
    </div>
  );
}

function SummaryStat({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-semibold ${warn ? 'text-amber-600' : ''}`}>{value}</div>
      </CardContent>
    </Card>
  );
}

function ScorecardTable({
  config,
  report,
  cohort,
}: {
  config: CostViewConfig;
  report: ScorecardReport;
  cohort: ScorecardCohort;
}) {
  if (!report.cohorts.length) {
    return (
      <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        No cohorts to display for the current filter set.
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1100px] text-sm">
          <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-3 text-left font-medium">Cohort</th>
              <th className="px-3 py-3 text-right font-medium">N</th>
              <th className="px-3 py-3 text-left font-medium">Severity</th>
              <th className="px-3 py-3 text-right font-medium">Avg TE (bps)</th>
              <th className="px-3 py-3 text-right font-medium">Median TE</th>
              <th className="px-3 py-3 text-right font-medium">P95 TE</th>
              <th className="px-3 py-3 text-right font-medium">Std Dev</th>
              <th className="px-3 py-3 text-right font-medium">Fill %</th>
              <th className="px-3 py-3 text-right font-medium">Vol % ADV20</th>
              <th className="px-3 py-3 text-right font-medium">Vol % Interval</th>
              <th className="px-3 py-3 text-right font-medium">Daily Vol %</th>
              <th className="px-3 py-3 text-left font-medium">Flags</th>
              <th className="px-3 py-3 text-left font-medium">Handoff</th>
            </tr>
          </thead>
          <tbody>
            {report.cohorts.map((c) => (
              <CohortRow key={c.cohort_key} cohort={c} config={config} cohortDimension={cohort} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CohortRow({
  cohort,
  config,
  cohortDimension,
}: {
  cohort: ScorecardCohortMetrics;
  config: CostViewConfig;
  cohortDimension: ScorecardCohort;
}) {
  const severity = evaluateCohortSeverity(cohort, config);
  const { pinRecommendationAction } = useHandoffContracts();
  const [isPinning, setIsPinning] = useState(false);
  const [pinnedTraceId, setPinnedTraceId] = useState<string | null>(null);
  const [pinError, setPinError] = useState<string | null>(null);

  const onPin = async () => {
    setIsPinning(true);
    setPinError(null);
    try {
      // Derive broker / strategy / asset_class from cohort_key when possible.
      const label = cohort.cohort_label;
      const parts = label.split(/\s*[×xX]\s*|\s*\/\s*|\s*-\s*/);
      let broker: string | undefined;
      let strategy: string | undefined;
      let assetClass: string | undefined;
      if (cohortDimension === 'broker') {
        broker = label;
      } else if (cohortDimension === 'strategy') {
        strategy = label;
      } else if (cohortDimension === 'broker_strategy') {
        broker = parts[0]?.trim();
        strategy = parts.slice(1).join(' ').trim() || undefined;
      } else if (cohortDimension === 'asset_class') {
        assetClass = label;
      }
      await pinRecommendationAction({
        cohort: cohortDimension,
        broker,
        strategy,
        asset_class: assetClass,
        sample_size: cohort.sample_size,
        arrival_bps: cohort.avg_tracking_error_bps ?? null,
        implementation_bps: cohort.p95_tracking_error_bps ?? null,
        severity,
        rationale: `${cohort.cohort_label} — N=${cohort.sample_size}, avg TE ${cohort.avg_tracking_error_bps?.toFixed(1) ?? '—'} bps`,
      });
      setPinnedTraceId('pinned');
    } catch (err) {
      setPinError(err instanceof Error ? err.message : 'Pin failed');
    } finally {
      setIsPinning(false);
    }
  };

  return (
    <tr className={`border-t border-border/60 ${cohort.sample_size_warning ? 'bg-muted/30' : ''}`}>
      <td className="px-3 py-3 font-medium">
        <div className="flex items-center gap-2">
          {cohort.sample_size_warning ? <AlertTriangle className="h-3.5 w-3.5 text-amber-600" /> : null}
          <span>{cohort.cohort_label}</span>
        </div>
      </td>
      <td className="px-3 py-3 text-right font-mono">{cohort.sample_size}</td>
      <td className="px-3 py-3">
        <span className={`inline-flex rounded border px-2 py-0.5 text-xs ${getSeverityTone(severity)}`}>
          {getSeverityText(severity)}
        </span>
      </td>
      <td className="px-3 py-3 text-right">{formatNumber(cohort.avg_tracking_error_bps, 1)}</td>
      <td className="px-3 py-3 text-right">{formatNumber(cohort.median_tracking_error_bps, 1)}</td>
      <td className="px-3 py-3 text-right">{formatNumber(cohort.p95_tracking_error_bps, 1)}</td>
      <td className="px-3 py-3 text-right">{formatNumber(cohort.stddev_tracking_error_bps, 1)}</td>
      <td className="px-3 py-3 text-right">{formatNumber(cohort.avg_fill_pct, 1, '%')}</td>
      <td className="px-3 py-3 text-right">{formatNumber(cohort.avg_volume_pct_adv20, 2, '%')}</td>
      <td className="px-3 py-3 text-right">{formatNumber(cohort.avg_volume_pct_interval, 2, '%')}</td>
      <td className="px-3 py-3 text-right">{formatNumber(cohort.avg_daily_volatility, 2, '%')}</td>
      <td className="px-3 py-3">
        <div className="flex flex-wrap gap-1">
          {cohort.anomaly_flags.length ? (
            cohort.anomaly_flags.map((flag) => (
              <span key={flag} className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                {formatAnomalyFlag(flag)}
              </span>
            ))
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          )}
        </div>
      </td>
      <td className="px-3 py-3">
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs"
          disabled={isPinning}
          onClick={onPin}
          title="Pin as CostView → ExecutionView recommendation"
        >
          {isPinning ? 'Pinning…' : pinnedTraceId ? '✓ Pinned' : 'Pin →EV'}
        </Button>
        {pinError && <div className="mt-1 text-[10px] text-red-600">{pinError}</div>}
      </td>
    </tr>
  );
}

export default ScorecardView;

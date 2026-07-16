import { Suspense, lazy } from 'react';
import { Download, RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { averageMetric, countAlertOrders, evaluateThreshold, getSeverityText, getSeverityTone } from '../lib/thresholds';
import type { AlertSeverity, CostViewConfig, CostViewFilterFormState, TcaRouteSummary, TcaReport } from '../types';
import { TcaFilterWorkbench } from './TcaFilterWorkbench';
import { TcaOrderTable } from './TcaOrderTable';

const LazyPriceDynamicsChart = lazy(async () => {
  const module = await import('./PriceDynamicsChart');
  return { default: module.PriceDynamicsChart };
});

const LazyVolumeDynamicsChart = lazy(async () => {
  const module = await import('./VolumeDynamicsChart');
  return { default: module.VolumeDynamicsChart };
});

interface AnalysisViewProps {
  config: CostViewConfig;
  error: string | null;
  filterForm: CostViewFilterFormState;
  isLoading: boolean;
  report: TcaReport | null;
  selectedRoute: TcaRouteSummary | null;
  onFilterChange: (next: CostViewFilterFormState) => void;
  onOpenExport: () => void;
  onPageChange: (offset: number) => void;
  onRefresh: () => void;
  onResetFilters: () => void;
  onRunSearch: () => void;
  onSelectRoute: (route: TcaRouteSummary | null) => void;
}

interface SummaryCard {
  label: string;
  value: string;
  severity: AlertSeverity;
}

function ChartFallback({ title }: { title: string }) {
  return (
    <div className="flex h-[280px] items-center justify-center rounded-xl border border-dashed border-border text-sm text-muted-foreground">
      Loading {title.toLowerCase()}…
    </div>
  );
}

function createSummaryCards(report: TcaReport | null, config: CostViewConfig) {
  if (!report) {
    return [
      { label: 'Matched Routes', value: '—', severity: 'none' as const },
      { label: 'Avg Pnl VWAP', value: '—', severity: 'none' as const },
      { label: 'Alert Routes', value: '—', severity: 'none' as const },
      { label: 'Avg Fill %', value: '—', severity: 'none' as const },
      { label: 'Avg Par Rate (Cont)', value: '—', severity: 'none' as const },
    ] satisfies SummaryCard[];
  }

  const avgPnlVwap = averageMetric(report.orders, 'tracking_error_bps');
  const avgFill = averageMetric(report.orders, 'fill_pct');
  const avgParRateContinuous = averageMetric(report.orders, 'volume_pct_interval');
  const alertCount = countAlertOrders(report.orders, config);

  return [
    {
      label: 'Matched Routes',
      value: String(report.total_orders),
      severity: 'normal' as const,
    },
    {
      label: 'Avg Pnl VWAP',
      value: avgPnlVwap != null ? `${avgPnlVwap.toFixed(1)} bps` : '—',
      severity: evaluateThreshold(config.rules.tracking_error_bps, avgPnlVwap),
    },
    {
      label: 'Alert Routes',
      value: String(alertCount),
      severity: alertCount > 0 ? 'warning' : 'normal',
    },
    {
      label: 'Avg Fill %',
      value: avgFill != null ? `${avgFill.toFixed(1)}%` : '—',
      severity: evaluateThreshold(config.rules.fill_pct, avgFill),
    },
    {
      label: 'Avg Par Rate (Cont)',
      value: avgParRateContinuous != null ? `${avgParRateContinuous.toFixed(2)}%` : '—',
      severity: evaluateThreshold(config.rules.volume_pct_interval, avgParRateContinuous),
    },
  ] satisfies SummaryCard[];
}

export function AnalysisView({ config, error, filterForm, isLoading, report, selectedRoute, onFilterChange, onOpenExport, onPageChange, onRefresh, onResetFilters, onRunSearch, onSelectRoute }: AnalysisViewProps) {
  const summaryCards = createSummaryCards(report, config);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-xl border bg-card p-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Route Analysis</h2>
          <p className="text-sm text-muted-foreground">Run filtered TCA analysis, drill into individual routes, and export the current working set.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={onRefresh}><RefreshCw className="mr-2 h-4 w-4" />Refresh</Button>
          <Button variant="outline" onClick={onOpenExport}><Download className="mr-2 h-4 w-4" />Export</Button>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Analysis request failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {filterForm.warningOnly ? (
        <Alert>
          <AlertTitle>Warning-only view enabled</AlertTitle>
          <AlertDescription>Only warning and critical rows from the full backend result set are shown. Pagination and all-filtered export now use the same filtered source.</AlertDescription>
        </Alert>
      ) : null}

      <TcaFilterWorkbench form={filterForm} isLoading={isLoading} onChange={onFilterChange} onReset={onResetFilters} onSearch={onRunSearch} />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {summaryCards.map((card) => (
          <Card key={card.label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{card.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-semibold">{card.value}</div>
              <div className={`mt-2 inline-flex rounded border px-2 py-0.5 text-xs ${getSeverityTone(card.severity)}`}>
                {getSeverityText(card.severity)}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {report ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
            <div>
              {report.total_orders} route{report.total_orders !== 1 ? 's' : ''} matched · Generated {new Date(report.generated_at).toLocaleString()}
            </div>
            <div className="flex flex-wrap gap-2">
              {report.filters.start_date ? <span className="rounded-full border px-2 py-0.5 text-xs">{report.filters.start_date} - {report.filters.end_date}</span> : null}
              {report.filters.algo ? <span className="rounded-full border px-2 py-0.5 text-xs">{report.filters.algo}</span> : null}
              {report.filters.broker ? <span className="rounded-full border px-2 py-0.5 text-xs">{report.filters.broker}</span> : null}
              {report.filters.symbol ? <span className="rounded-full border px-2 py-0.5 text-xs">{report.filters.symbol}</span> : null}
            </div>
          </div>

          <TcaOrderTable
            config={config}
            report={report}
            selectedRouteKey={selectedRoute ? `${selectedRoute.order_id}/${selectedRoute.route_id}/${selectedRoute.order_as_of_date}` : null}
            onPageChange={onPageChange}
            onSelectRoute={onSelectRoute}
          />

          {selectedRoute ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Selected Route Detail</CardTitle>
                <p className="text-sm text-muted-foreground">{selectedRoute.order_id} · {selectedRoute.route_id} · {selectedRoute.equ_ticker ?? 'Unknown symbol'} · {selectedRoute.order_as_of_date}</p>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {[
                    { label: 'Fill %', value: selectedRoute.fill != null ? `${selectedRoute.fill.toFixed(1)}%` : '—', severity: evaluateThreshold(config.rules.fill_pct, selectedRoute.fill) },
                    { label: 'Pnl VWAP', value: selectedRoute.pnl_vwap != null ? `${selectedRoute.pnl_vwap.toFixed(1)} bps` : '—', severity: evaluateThreshold(config.rules.tracking_error_bps, selectedRoute.pnl_vwap) },
                    { label: 'Par Rate', value: selectedRoute.par_rate != null ? `${(selectedRoute.par_rate * 100).toFixed(2)}%` : '—', severity: evaluateThreshold(config.rules.volume_pct_adv20, selectedRoute.par_rate != null ? selectedRoute.par_rate * 100 : null) },
                    { label: 'Par Rate (Cont)', value: selectedRoute.par_rate_continuous != null ? `${(selectedRoute.par_rate_continuous * 100).toFixed(2)}%` : '—', severity: evaluateThreshold(config.rules.volume_pct_interval, selectedRoute.par_rate_continuous != null ? selectedRoute.par_rate_continuous * 100 : null) },
                  ].map((metric) => (
                    <div key={metric.label} className="rounded-lg border border-border bg-muted/30 p-3">
                      <div className="text-xs text-muted-foreground">{metric.label}</div>
                      <div className="mt-1 text-lg font-semibold">{metric.value}</div>
                      <div className={`mt-2 inline-flex rounded border px-2 py-0.5 text-xs ${getSeverityTone(metric.severity)}`}>{getSeverityText(metric.severity)}</div>
                    </div>
                  ))}
                </div>

                <div className="grid gap-4 xl:grid-cols-2">
                  <Suspense fallback={<ChartFallback title="Price Dynamics" />}>
                    <LazyPriceDynamicsChart orderId={selectedRoute.order_id} routes={[selectedRoute]} />
                  </Suspense>
                  <Suspense fallback={<ChartFallback title="Volume Participation" />}>
                    <LazyVolumeDynamicsChart orderId={selectedRoute.order_id} routes={[selectedRoute]} />
                  </Suspense>
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
              Select a route row to inspect price/volume dynamics and TCA metrics.
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          Run Analyze to load the first TCA report.
        </div>
      )}
    </div>
  );
}
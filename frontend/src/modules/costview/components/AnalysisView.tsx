import { Suspense, lazy } from 'react';
import { Download, RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { averageMetric, countAlertOrders, evaluateThreshold, getSeverityText, getSeverityTone } from '../lib/thresholds';
import type { AlertSeverity, CostViewConfig, CostViewFilterFormState, TcaOrderSummary, TcaReport } from '../types';
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
  selectedOrder: TcaOrderSummary | null;
  onFilterChange: (next: CostViewFilterFormState) => void;
  onOpenExport: () => void;
  onPageChange: (offset: number) => void;
  onRefresh: () => void;
  onResetFilters: () => void;
  onRunSearch: () => void;
  onSelectOrder: (order: TcaOrderSummary | null) => void;
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
      { label: 'Matched Orders', value: '—', severity: 'none' as const },
      { label: 'Avg Tracking Error', value: '—', severity: 'none' as const },
      { label: 'Alert Orders', value: '—', severity: 'none' as const },
      { label: 'Avg Fill %', value: '—', severity: 'none' as const },
      { label: 'Avg Vol % Interval', value: '—', severity: 'none' as const },
    ] satisfies SummaryCard[];
  }

  const avgTracking = averageMetric(report.orders, 'tracking_error_bps');
  const avgFill = averageMetric(report.orders, 'fill_pct');
  const avgInterval = averageMetric(report.orders, 'volume_pct_interval');
  const alertCount = countAlertOrders(report.orders, config);

  return [
    {
      label: 'Matched Orders',
      value: String(report.total_orders),
      severity: 'normal' as const,
    },
    {
      label: 'Avg Tracking Error',
      value: avgTracking != null ? `${avgTracking.toFixed(1)} bps` : '—',
      severity: evaluateThreshold(config.rules.tracking_error_bps, avgTracking),
    },
    {
      label: 'Alert Orders',
      value: String(alertCount),
      severity: alertCount > 0 ? 'warning' : 'normal',
    },
    {
      label: 'Avg Fill %',
      value: avgFill != null ? `${avgFill.toFixed(1)}%` : '—',
      severity: evaluateThreshold(config.rules.fill_pct, avgFill),
    },
    {
      label: 'Avg Vol % Interval',
      value: avgInterval != null ? `${avgInterval.toFixed(2)}%` : '—',
      severity: evaluateThreshold(config.rules.volume_pct_interval, avgInterval),
    },
  ] satisfies SummaryCard[];
}

export function AnalysisView({ config, error, filterForm, isLoading, report, selectedOrder, onFilterChange, onOpenExport, onPageChange, onRefresh, onResetFilters, onRunSearch, onSelectOrder }: AnalysisViewProps) {
  const summaryCards = createSummaryCards(report, config);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-xl border bg-card p-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Orders & Routes Analysis</h2>
          <p className="text-sm text-muted-foreground">Run filtered TCA analysis, drill into routes, and export the current working set.</p>
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
              {report.total_orders} order{report.total_orders !== 1 ? 's' : ''} matched · Generated {new Date(report.generated_at).toLocaleString()}
            </div>
            <div className="flex flex-wrap gap-2">
              {report.filters.start_date ? <span className="rounded-full border px-2 py-0.5 text-xs">{report.filters.start_date} - {report.filters.end_date}</span> : null}
              {report.filters.algo ? <span className="rounded-full border px-2 py-0.5 text-xs">{report.filters.algo}</span> : null}
              {report.filters.broker ? <span className="rounded-full border px-2 py-0.5 text-xs">{report.filters.broker}</span> : null}
              {report.filters.symbol ? <span className="rounded-full border px-2 py-0.5 text-xs">{report.filters.symbol}</span> : null}
            </div>
          </div>

          <TcaOrderTable config={config} report={report} selectedOrderId={selectedOrder?.order_id ?? null} onPageChange={onPageChange} onSelectOrder={onSelectOrder} />

          {selectedOrder ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Selected Order Detail</CardTitle>
                <p className="text-sm text-muted-foreground">{selectedOrder.order_id} · {selectedOrder.equ_ticker ?? 'Unknown symbol'} · {selectedOrder.order_as_of_date}</p>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {[{ label: 'Fill %', value: selectedOrder.fill_pct != null ? `${selectedOrder.fill_pct.toFixed(1)}%` : '—', severity: evaluateThreshold(config.rules.fill_pct, selectedOrder.fill_pct) }, { label: 'Tracking Error', value: selectedOrder.tracking_error_bps != null ? `${selectedOrder.tracking_error_bps.toFixed(1)} bps` : '—', severity: evaluateThreshold(config.rules.tracking_error_bps, selectedOrder.tracking_error_bps) }, { label: 'Vol % ADV20', value: selectedOrder.volume_pct_adv20 != null ? `${selectedOrder.volume_pct_adv20.toFixed(2)}%` : '—', severity: evaluateThreshold(config.rules.volume_pct_adv20, selectedOrder.volume_pct_adv20) }, { label: 'Intraday Vol', value: selectedOrder.intraday_volatility != null ? `${selectedOrder.intraday_volatility.toFixed(2)}%` : '—', severity: evaluateThreshold(config.rules.intraday_volatility, selectedOrder.intraday_volatility) }].map((metric) => (
                    <div key={metric.label} className="rounded-lg border border-border bg-muted/30 p-3">
                      <div className="text-xs text-muted-foreground">{metric.label}</div>
                      <div className="mt-1 text-lg font-semibold">{metric.value}</div>
                      <div className={`mt-2 inline-flex rounded border px-2 py-0.5 text-xs ${getSeverityTone(metric.severity)}`}>{getSeverityText(metric.severity)}</div>
                    </div>
                  ))}
                </div>

                <Card className="gap-3 border-dashed">
                  <CardHeader className="pb-0">
                    <CardTitle className="text-sm">Route Comparison</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
                          <tr>
                            <th className="py-2 pr-3 text-left font-medium">Route</th>
                            <th className="py-2 pr-3 text-left font-medium">Broker</th>
                            <th className="py-2 pr-3 text-right font-medium">Fill %</th>
                            <th className="py-2 pr-3 text-right font-medium">Exec</th>
                            <th className="py-2 pr-3 text-right font-medium">VWAP</th>
                            <th className="py-2 pr-3 text-right font-medium">Tracking Error</th>
                            <th className="py-2 text-right font-medium">Vol % Interval</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedOrder.routes.map((route) => (
                            <tr key={route.route_id} className="border-b border-border/40 last:border-b-0">
                              <td className="py-2 pr-3 font-mono">{route.route_id}</td>
                              <td className="py-2 pr-3">{route.broker ?? '—'}</td>
                              <td className="py-2 pr-3 text-right">{route.fill_pct != null ? `${route.fill_pct.toFixed(1)}%` : '—'}</td>
                              <td className="py-2 pr-3 text-right">{route.exec_price != null ? route.exec_price.toFixed(2) : '—'}</td>
                              <td className="py-2 pr-3 text-right">{route.interval_vwap != null ? route.interval_vwap.toFixed(2) : '—'}</td>
                              <td className="py-2 pr-3 text-right">{route.tracking_error_bps != null ? `${route.tracking_error_bps.toFixed(1)} bps` : '—'}</td>
                              <td className="py-2 text-right">{route.volume_pct_interval != null ? `${route.volume_pct_interval.toFixed(2)}%` : '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>

                <div className="grid gap-4 xl:grid-cols-2">
                  <Suspense fallback={<ChartFallback title="Price Dynamics" />}>
                    <LazyPriceDynamicsChart orderId={selectedOrder.order_id} routes={selectedOrder.routes} />
                  </Suspense>
                  <Suspense fallback={<ChartFallback title="Volume Participation" />}>
                    <LazyVolumeDynamicsChart orderId={selectedOrder.order_id} routes={selectedOrder.routes} />
                  </Suspense>
                </div>

                {selectedOrder.data_quality_warning ? (
                  <Alert>
                    <AlertTitle>Data quality warning</AlertTitle>
                    <AlertDescription>Benchmark or time-series coverage looks incomplete for this order. Treat route comparisons as indicative, not definitive.</AlertDescription>
                  </Alert>
                ) : null}
              </CardContent>
            </Card>
          ) : (
            <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
              Select an order row to inspect route comparison and price/volume dynamics.
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
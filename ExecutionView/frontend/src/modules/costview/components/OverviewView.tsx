import { Database, Download, RefreshCw, ShieldAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { averageMetric, countAlertOrders, getHighestOrderSeverity, getSeverityText, getSeverityTone } from '../lib/thresholds';
import type { CostViewConfig, CostViewExportState, TcaReport } from '../types';

interface OverviewViewProps {
  config: CostViewConfig;
  error: string | null;
  exportState: CostViewExportState;
  isLoading: boolean;
  report: TcaReport | null;
  onGoToAnalysis: () => void;
  onOpenExport: () => void;
  onRefresh: () => void;
  onNavigateToDatabase?: () => void;
}

function formatRelativeTime(value: string | null): string | null {
  if (!value) return null;

  const deltaMs = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(deltaMs) || deltaMs < 0) {
    return null;
  }

  const seconds = Math.round(deltaMs / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

export function OverviewView({ config, error, exportState, isLoading, report, onGoToAnalysis, onOpenExport, onRefresh, onNavigateToDatabase }: OverviewViewProps) {
  const avgTracking = report ? averageMetric(report.orders, 'tracking_error_bps') : null;
  const avgFill = report ? averageMetric(report.orders, 'fill_pct') : null;
  const avgAdv = report ? averageMetric(report.orders, 'volume_pct_adv20') : null;
  const avgVol = report ? averageMetric(report.orders, 'intraday_volatility') : null;
  const alertCount = report ? countAlertOrders(report.orders, config) : 0;
  const recentOrders = report?.orders.slice(0, 5) ?? [];
  const latestOrderDate = report?.orders.reduce<string | null>((acc, order) => {
    const d = order.order_as_of_date;
    if (!d) return acc;
    return !acc || d > acc ? d : acc;
  }, null) ?? null;
  const generatedAge = formatRelativeTime(report?.generated_at ?? null);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-xl border bg-card p-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">CostView Overview</h2>
          <p className="text-sm text-muted-foreground">Freshness, coverage, and high-signal execution quality indicators.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={onRefresh} disabled={isLoading}><RefreshCw className="mr-2 h-4 w-4" />Refresh</Button>
          <Button variant="outline" onClick={onOpenExport}><Download className="mr-2 h-4 w-4" />Export</Button>
          {onNavigateToDatabase && (
            <Button variant="outline" onClick={onNavigateToDatabase}>
              <Database className="mr-2 h-4 w-4" />Manage Data
            </Button>
          )}
        </div>
      </div>

      {error ? (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" />
          <AlertTitle>Analysis error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Data Freshness</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold font-mono">{latestOrderDate ?? '—'}</div>
            <p className="mt-2 text-xs text-muted-foreground">
              Latest order date in the loaded result set
              {generatedAge ? ` · fetched ${generatedAge}` : ''}.
            </p>
            {onNavigateToDatabase && (
              <button
                type="button"
                onClick={onNavigateToDatabase}
                className="mt-2 text-xs font-medium text-primary hover:underline"
              >
                Open Database module →
              </button>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Coverage</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{report?.total_orders ?? 0}</div>
            <p className="mt-2 text-xs text-muted-foreground">Orders in the latest loaded result set.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Alert Orders</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{alertCount}</div>
            <p className="mt-2 text-xs text-muted-foreground">Orders currently breaching local threshold rules.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Last Export</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm font-medium">{exportState.lastExportFormat ? `${exportState.lastExportFormat.toUpperCase()} · ${exportState.lastExportScope}` : 'None yet'}</div>
            <p className="mt-2 text-xs text-muted-foreground">{exportState.lastExportAt ? new Date(exportState.lastExportAt).toLocaleString() : 'No export has been run in this browser.'}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[{ label: 'Avg Tracking Error', value: avgTracking != null ? `${avgTracking.toFixed(1)} bps` : '—' }, { label: 'Avg Fill %', value: avgFill != null ? `${avgFill.toFixed(1)}%` : '—' }, { label: 'Avg Vol % ADV20', value: avgAdv != null ? `${avgAdv.toFixed(2)}%` : '—' }, { label: 'Avg Intraday Vol', value: avgVol != null ? `${avgVol.toFixed(2)}%` : '—' }].map((metric) => (
          <Card key={metric.label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{metric.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-semibold">{metric.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">Recent High-Signal Orders</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">Quick drill-in list using the currently loaded analysis set.</p>
            </div>
            <Button variant="outline" onClick={onGoToAnalysis}>Open Analysis</Button>
          </div>
        </CardHeader>
        <CardContent>
          {recentOrders.length ? (
            <div className="space-y-2">
              {recentOrders.map((order) => {
                const severity = getHighestOrderSeverity(order, config);
                return (
                  <div key={order.order_id} className="flex flex-col gap-2 rounded-lg border border-border p-3 md:flex-row md:items-center md:justify-between">
                    <div>
                      <div className="font-mono text-sm">{order.order_id}</div>
                      <div className="text-xs text-muted-foreground">{order.equ_ticker ?? 'Unknown symbol'} · {order.order_as_of_date}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{order.algo ?? '—'}</Badge>
                      <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-medium ${getSeverityTone(severity)}`}>{getSeverityText(severity)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              Open Analysis or refresh CostView to load the latest default query.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
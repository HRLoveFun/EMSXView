import { Download, Play, RefreshCw, ShieldAlert, Check, Loader2, Circle } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { averageMetric, countAlertOrders, getHighestOrderSeverity, getSeverityText, getSeverityTone } from '../lib/thresholds';
import type { CostViewConfig, CostViewExportState, StageInfo, TcaReport, UpdateStatusResponse } from '../types';

// ── Pipeline stage definitions (mirrors backend _PIPELINE_STAGES) ────────────
const STAGES: { name: StageInfo['name']; label: string; icon: typeof Check }[] = [
  { name: 'initialization', label: 'Initialization', icon: Check },
  { name: 'fill_fetch',     label: 'Fill Fetch',     icon: Download },
  { name: 'processing',     label: 'Processing',     icon: RefreshCw },
  { name: 'completion',     label: 'Completion',     icon: Check },
];

interface OverviewViewProps {
  config: CostViewConfig;
  error: string | null;
  exportState: CostViewExportState;
  isLoading: boolean;
  report: TcaReport | null;
  updateStatus: UpdateStatusResponse | null;
  onGoToAnalysis: () => void;
  onOpenExport: () => void;
  onRefresh: () => void;
  onTriggerUpdate: () => void;
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

// ── Stage Progress Bar ───────────────────────────────────────────────────────

function StageProgress({ status }: { status: UpdateStatusResponse | null }) {
  const currentStage = status?.stage ?? null;
  const overall = status?.overall_progress ?? 0;
  const isTerminal = status?.status === 'completed' || status?.status === 'failed';
  const currentStageIndex = currentStage
    ? STAGES.findIndex((stage) => stage.name === currentStage.name)
    : -1;
  const isFailed = status?.status === 'failed';

  return (
    <div className="space-y-2">
      {/* Overall progress bar */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-muted-foreground">Overall Progress</span>
          <span className={`font-mono tabular-nums font-medium ${
            isTerminal
              ? status?.status === 'completed'
                ? 'text-emerald-600'
                : 'text-red-600'
              : 'text-primary'
          }`}>
            {overall}%
          </span>
        </div>
        <div className="h-1.5 w-full rounded-full bg-secondary overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ease-out ${
              status?.status === 'failed'
                ? 'bg-red-500'
                : status?.status === 'completed'
                  ? 'bg-emerald-500'
                  : 'bg-primary'
            }`}
            style={{ width: `${isTerminal && status?.status !== 'failed' ? 100 : overall}%` }}
          />
        </div>
      </div>

      {/* Stage indicators */}
      <div className="flex items-center gap-1 pt-1">
        {STAGES.map((stage, index) => {
          const isActive = currentStage?.name === stage.name;
          const isPast = currentStageIndex >= 0 && index < currentStageIndex;
          const isComplete = isFailed ? isPast : isTerminal || isPast;
          const isFailedStage = isFailed && isActive;

          return (
            <div key={stage.name} className="flex flex-1 items-center gap-1.5">
              <div
                title={`${stage.label}${isActive ? ` (${currentStage?.progress ?? 0}%)` : ''}`}
                className={`
                  flex items-center justify-center w-5 h-5 rounded-full border transition-colors duration-300
                  ${isComplete
                    ? stage.name === 'fill_fetch'
                      ? 'border-blue-500/50 bg-blue-500/15 text-blue-400'
                      : 'border-emerald-500/50 bg-emerald-500/15 text-emerald-400'
                    : isFailedStage
                      ? 'border-red-500/60 bg-red-500/15 text-red-500'
                    : isActive
                      ? 'border-primary/60 bg-primary/20 text-primary ring-2 ring-primary/20 animate-pulse'
                      : 'border-border bg-muted/30 text-muted-foreground/40'
                  }
                `}
              >
                {isComplete ? (
                  <Check className="w-3 h-3" />
                ) : isActive ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Circle className="w-2.5 h-2.5" />
                )}
              </div>
              <span className={`leading-none truncate ${
                isActive
                  ? 'text-foreground font-medium text-[10px]'
                  : isFailedStage
                    ? 'text-red-600 text-[10px]'
                  : isComplete
                    ? 'text-muted-foreground text-[10px]'
                    : 'text-muted-foreground/50 text-[9px]'
              }`}>
                {stage.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Error detail */}
      {status?.error && (
        <p className="text-[10px] text-red-600 mt-1 truncate">{status.error}</p>
      )}
    </div>
  );
}

export function OverviewView({ config, error, exportState, isLoading, report, updateStatus, onGoToAnalysis, onOpenExport, onRefresh, onTriggerUpdate }: OverviewViewProps) {
  const avgTracking = report ? averageMetric(report.orders, 'tracking_error_bps') : null;
  const avgFill = report ? averageMetric(report.orders, 'fill_pct') : null;
  const avgAdv = report ? averageMetric(report.orders, 'volume_pct_adv20') : null;
  const avgVol = report ? averageMetric(report.orders, 'intraday_volatility') : null;
  const alertCount = report ? countAlertOrders(report.orders, config) : 0;
  const recentOrders = report?.orders.slice(0, 5) ?? [];
  const activityAge = formatRelativeTime(updateStatus?.last_activity_at ?? null);
  const isActiveJob = updateStatus?.status === 'running' || updateStatus?.status === 'started';
  const isStale = isActiveJob && updateStatus?.last_activity_at
    ? Date.now() - new Date(updateStatus.last_activity_at).getTime() > 90_000
    : false;
  const stageSummary = updateStatus?.stage
    ? `${updateStatus.stage.label} ${updateStatus.stage.progress}%`
    : 'Waiting for first stage marker';

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
          <Button onClick={onTriggerUpdate}><Play className="mr-2 h-4 w-4" />Trigger Update</Button>
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
            <CardTitle className="text-sm">Pipeline Status</CardTitle>
          </CardHeader>
          <CardContent>
            <StageProgress status={updateStatus} />
            {!updateStatus && (
              <p className="mt-2 text-xs text-muted-foreground">No active update job.</p>
            )}
            {isActiveJob && (
              <>
                <p className="mt-1.5 text-[10px] text-muted-foreground">
                  {updateStatus.status === 'started' ? 'Queued' : 'Running'} · {stageSummary}
                </p>
                <p className={`mt-1 text-[10px] ${isStale ? 'text-amber-600' : 'text-muted-foreground'}`}>
                  {isStale
                    ? `No new pipeline output for ${activityAge ?? 'a while'}. Check backend logs if this does not move.`
                    : `Last activity ${activityAge ?? 'just now'}`}
                </p>
              </>
            )}
            {updateStatus?.status === 'completed' && updateStatus.completed_at && (
              <p className="mt-1.5 text-[10px] text-emerald-600">
                Completed at {new Date(updateStatus.completed_at).toLocaleTimeString()}
              </p>
            )}
            {updateStatus?.status === 'failed' && updateStatus.completed_at && (
              <p className="mt-1.5 text-[10px] text-red-600">
                Failed at {new Date(updateStatus.completed_at).toLocaleTimeString()}
              </p>
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
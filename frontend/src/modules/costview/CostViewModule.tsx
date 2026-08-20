import { Suspense, lazy, startTransition, useCallback, useEffect, useRef, useState } from 'react';
import { Activity, BarChart3, FileBarChart, HeartPulse, RefreshCw, Settings2, Trophy } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  DEFAULT_FILTER_FORM_STATE,
  loadCostViewConfig,
  loadCostViewExportState,
  loadCostViewFilters,
  loadCostViewViewState,
  saveCostViewActiveTab,
  saveCostViewConfig,
  saveCostViewExportState,
  saveCostViewFilters,
} from './lib/storage';
import { applyCostViewClientFilters, buildWarningOnlyPage } from './lib/report-state';
import { analyzeTca, analyzeTcaOrders, fetchAllFilteredOrders, getUpdateStatus, PipelineTriggeredError, type TcaOrderReport } from './services/api';
import type {
  CostViewConfig,
  CostViewFilterFormState,
  CostViewModuleTab,
  ExportFormat,
  ExportScope,
  TcaFilterPayload,
  TcaReport,
  TcaRouteSummary,
  UpdateStatusResponse,
} from './types';
import { ExportDialog } from './components/ExportDialog';
import { OverviewView } from './components/OverviewView';

const LazyAnalysisView = lazy(async () => {
  const module = await import('./components/AnalysisView');
  return { default: module.AnalysisView };
});

const LazyConfigureView = lazy(async () => {
  const module = await import('./components/ConfigureView');
  return { default: module.ConfigureView };
});

const LazyScorecardView = lazy(async () => {
  const module = await import('./components/ScorecardView');
  return { default: module.ScorecardView };
});

const LazyReportView = lazy(async () => {
  const module = await import('./components/ReportView');
  return { default: module.ReportView };
});

const LazyMonitoringView = lazy(async () => {
  const module = await import('./components/MonitoringView');
  return { default: module.MonitoringView };
});

function normalizeOrderIds(value: string): string[] | undefined {
  const parts = value.split(/[\n,]+/).map((segment) => segment.trim()).filter(Boolean);
  return parts.length ? parts : undefined;
}

function formToPayload(form: CostViewFilterFormState): TcaFilterPayload {
  const payload: TcaFilterPayload = {};
  const orderIds = normalizeOrderIds(form.orderIds);
  if (orderIds?.length) payload.order_ids = orderIds;
  if (form.algo) payload.algo = form.algo;
  if (form.startDate) payload.start_date = form.startDate.replace(/-/g, '');
  if (form.endDate) payload.end_date = form.endDate.replace(/-/g, '');
  if (form.broker) payload.broker = form.broker.trim();
  if (form.symbol) payload.symbol = form.symbol.trim();
  return payload;
}

export default function CostViewModule({ onNavigateToDatabase }: { onNavigateToDatabase?: () => void } = {}) {
  const [activeTab, setActiveTab] = useState<CostViewModuleTab>(() => loadCostViewViewState().activeTab);
  const [config, setConfig] = useState<CostViewConfig>(() => loadCostViewConfig());
  const [filterForm, setFilterForm] = useState<CostViewFilterFormState>(() => loadCostViewFilters());
  const [report, setReport] = useState<TcaReport | null>(null);
  const [orderReport, setOrderReport] = useState<TcaOrderReport | null>(null);
  const [viewMode, setViewMode] = useState<'routes' | 'orders'>('routes');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isExportDialogOpen, setIsExportDialogOpen] = useState(false);
  const [exportState, setExportState] = useState(() => loadCostViewExportState());
  const [selectedRoute, setSelectedRoute] = useState<TcaRouteSummary | null>(null);
  const [fullResultReport, setFullResultReport] = useState<TcaReport | null>(null);
  // 数据管道状态：analyze 返回 202（默认日期无数据自动触发跑数）时设置
  const [pipelineJob, setPipelineJob] = useState<{ jobId: string; targetDate: string; form: CostViewFilterFormState } | null>(null);
  const [pipelineStatus, setPipelineStatus] = useState<UpdateStatusResponse | null>(null);
  const hasLoadedInitialRef = useRef(false);
  const pipelineTimerRef = useRef<number | null>(null);

  useEffect(() => {
    saveCostViewActiveTab(activeTab);
  }, [activeTab]);

  useEffect(() => {
    saveCostViewFilters(filterForm);
  }, [filterForm]);

  useEffect(() => {
    saveCostViewConfig(config);
  }, [config]);

  useEffect(() => {
    saveCostViewExportState(exportState);
  }, [exportState]);

  useEffect(() => {
    if (!filterForm.warningOnly || !fullResultReport) {
      return;
    }

    startTransition(() => {
      setReport((currentReport) => buildWarningOnlyPage(
        fullResultReport,
        config,
        filterForm,
        currentReport?.offset ?? 0,
      ));
    });
  }, [config, filterForm, fullResultReport]);

  const fetchReport = useCallback(async (form: CostViewFilterFormState, offset = 0) => {
    setIsLoading(true);
    setError(null);
    try {
      if (form.warningOnly) {
        const fullReport = await fetchAllFilteredOrders({
          filters: formToPayload(form),
          aggregation: 'per_order',
          limit: Math.max(form.limit, 200),
        });
        const nextReport = buildWarningOnlyPage(fullReport, config, form, offset);
        startTransition(() => {
          setFullResultReport(fullReport);
          setReport(nextReport);
          if (selectedRoute && !nextReport.orders.some((route) => route.order_id === selectedRoute.order_id && route.route_id === selectedRoute.route_id && route.order_as_of_date === selectedRoute.order_as_of_date)) {
            setSelectedRoute(null);
          }
        });
      } else {
        const nextReport = await analyzeTca({
          filters: formToPayload(form),
          limit: form.limit,
          offset,
          aggregation: 'per_order',
        });
        startTransition(() => {
          setFullResultReport(null);
          setReport(nextReport);
          if (selectedRoute && !nextReport.orders.some((route) => route.order_id === selectedRoute.order_id && route.route_id === selectedRoute.route_id && route.order_as_of_date === selectedRoute.order_as_of_date)) {
            setSelectedRoute(null);
          }
        });
      }
    } catch (nextError) {
      // 202：默认日期数据未生成，后端已自动触发管道 —— 进入跑数进度状态
      if (nextError instanceof PipelineTriggeredError) {
        setPipelineJob({ jobId: nextError.jobId, targetDate: nextError.targetDate, form });
        setReport(null);
        setFullResultReport(null);
        setSelectedRoute(null);
        return;
      }
      setError(nextError instanceof Error ? nextError.message : 'Unknown CostView error');
      setReport(null);
      setFullResultReport(null);
      setSelectedRoute(null);
    } finally {
      setIsLoading(false);
    }
  }, [config, selectedRoute]);

  const fetchOrderReport = useCallback(async (form: CostViewFilterFormState) => {
    setIsLoading(true);
    setError(null);
    try {
      const nextReport = await analyzeTcaOrders({
        filters: formToPayload(form),
        aggregation: 'aggregated',
        limit: Math.max(form.limit, 200),
        offset: 0,
      });
      startTransition(() => {
        setOrderReport(nextReport);
      });
    } catch (nextError) {
      if (nextError instanceof PipelineTriggeredError) {
        setPipelineJob({ jobId: nextError.jobId, targetDate: nextError.targetDate, form });
        setOrderReport(null);
        return;
      }
      setError(nextError instanceof Error ? nextError.message : 'Unknown CostView order aggregation error');
      setOrderReport(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (hasLoadedInitialRef.current) return;
    hasLoadedInitialRef.current = true;
    void fetchReport(filterForm, 0);
  }, [fetchReport, filterForm]);

  // 管道轮询：job 进行中每 3s 查询状态，完成自动重新加载报告，失败展示错误
  useEffect(() => {
    if (!pipelineJob) return;

    const poll = async () => {
      try {
        const status = await getUpdateStatus(pipelineJob.jobId);
        setPipelineStatus(status);
        if (status.status === 'completed' || status.status === 'failed') {
          if (pipelineTimerRef.current !== null) {
            window.clearInterval(pipelineTimerRef.current);
            pipelineTimerRef.current = null;
          }
          const { form } = pipelineJob;
          setPipelineJob(null);
          setPipelineStatus(null);
          if (status.status === 'completed') {
            void fetchReport(form, 0);
          } else {
            setError(`数据管道执行失败: ${status.error ?? '未知错误'}`);
          }
        }
      } catch {
        // 单次轮询失败静默，下一周期重试
      }
    };

    void poll();
    pipelineTimerRef.current = window.setInterval(() => void poll(), 3000);
    return () => {
      if (pipelineTimerRef.current !== null) {
        window.clearInterval(pipelineTimerRef.current);
        pipelineTimerRef.current = null;
      }
    };
  }, [pipelineJob, fetchReport]);

  const handleOpenAnalysis = useCallback(() => {
    setActiveTab('analysis');
  }, []);

  const handleRunSearch = useCallback(() => {
    void fetchReport(filterForm, 0);
  }, [fetchReport, filterForm]);

  const handleResetFilters = useCallback(() => {
    setFilterForm(DEFAULT_FILTER_FORM_STATE);
    void fetchReport(DEFAULT_FILTER_FORM_STATE, 0);
  }, [fetchReport]);

  const handlePageChange = useCallback((offset: number) => {
    if (filterForm.warningOnly && fullResultReport) {
      const nextReport = buildWarningOnlyPage(fullResultReport, config, filterForm, offset);
      startTransition(() => {
        setReport(nextReport);
        if (selectedRoute && !nextReport.orders.some((route) => route.order_id === selectedRoute.order_id && route.route_id === selectedRoute.route_id && route.order_as_of_date === selectedRoute.order_as_of_date)) {
          setSelectedRoute(null);
        }
      });
      return;
    }

    void fetchReport(filterForm, offset);
  }, [config, fetchReport, filterForm, fullResultReport, selectedRoute]);

  const handleExport = useCallback(async (format: ExportFormat, scope: ExportScope) => {
    if (!report) {
      setError('Run analysis before exporting CostView data.');
      return false;
    }

    setIsExporting(true);
    try {
      const { exportCostViewReport } = await import('./lib/export');

      let sourceReport = report;
      if (scope === 'all-filtered') {
        const backendReport = fullResultReport ?? await fetchAllFilteredOrders({
          filters: formToPayload(filterForm),
          aggregation: 'per_order',
          limit: Math.max(filterForm.limit, 200),
        });

        sourceReport = filterForm.warningOnly
          ? applyCostViewClientFilters(backendReport, config, filterForm)
          : backendReport;
      }

      await exportCostViewReport({
        format,
        scope,
        report: sourceReport,
        config,
        selectedOrder: selectedRoute,
      });

      setExportState({
        lastExportAt: new Date().toISOString(),
        lastExportFormat: format,
        lastExportScope: scope,
      });
      return true;
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'CostView export failed');
      return false;
    } finally {
      setIsExporting(false);
    }
  }, [config, filterForm, fullResultReport, report, selectedRoute]);

  return (
    <div className="space-y-4">
      {pipelineJob && (
        <div className="rounded-xl border border-primary/40 bg-primary/5 p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <RefreshCw className="h-4 w-4 animate-spin text-primary" />
            <span>正在生成 {pipelineJob.targetDate} 数据</span>
            {pipelineStatus?.stage && (
              <span className="text-muted-foreground">· {pipelineStatus.stage.label}</span>
            )}
            <span className="ml-auto text-xs text-muted-foreground">
              {pipelineStatus?.overall_progress ?? 0}%
            </span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded bg-muted">
            <div
              className="h-full rounded bg-primary transition-all duration-500"
              style={{ width: `${pipelineStatus?.overall_progress ?? 0}%` }}
            />
          </div>
          {pipelineStatus?.stage?.detail && (
            <p className="mt-1.5 text-xs text-muted-foreground">{pipelineStatus.stage.detail}</p>
          )}
        </div>
      )}
      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as CostViewModuleTab)}>
        <TabsList className="grid h-auto w-full grid-cols-6 gap-2 rounded-xl bg-muted/60 p-1 lg:w-fit">
          <TabsTrigger value="overview"><Activity className="h-4 w-4" />Overview</TabsTrigger>
          <TabsTrigger value="analysis"><BarChart3 className="h-4 w-4" />Analysis</TabsTrigger>
          <TabsTrigger value="scorecard"><Trophy className="h-4 w-4" />Scorecard</TabsTrigger>
          <TabsTrigger value="report"><FileBarChart className="h-4 w-4" />Report</TabsTrigger>
          <TabsTrigger value="monitoring"><HeartPulse className="h-4 w-4" />Monitoring</TabsTrigger>
          <TabsTrigger value="configure"><Settings2 className="h-4 w-4" />Configure</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-4">
          <OverviewView
            config={config}
            error={error}
            exportState={exportState}
            isLoading={isLoading}
            report={report}
            onGoToAnalysis={handleOpenAnalysis}
            onOpenExport={() => setIsExportDialogOpen(true)}
            onRefresh={() => void fetchReport(filterForm, 0)}
            onNavigateToDatabase={onNavigateToDatabase}
          />
        </TabsContent>

        <TabsContent value="analysis" className="mt-4">
          <Suspense fallback={<div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">Loading analysis workspace…</div>}>
            <LazyAnalysisView
              config={config}
              error={error}
              filterForm={filterForm}
              isLoading={isLoading}
              report={report}
              orderReport={orderReport}
              viewMode={viewMode}
              selectedRoute={selectedRoute}
              onFilterChange={setFilterForm}
              onOpenExport={() => setIsExportDialogOpen(true)}
              onPageChange={handlePageChange}
              onRefresh={() => void fetchReport(filterForm, 0)}
              onResetFilters={handleResetFilters}
              onRunSearch={handleRunSearch}
              onSelectRoute={(route) => setSelectedRoute(route)}
              onViewModeChange={(mode) => {
                setViewMode(mode);
                if (mode === 'orders') {
                  void fetchOrderReport(filterForm);
                }
              }}
            />
          </Suspense>
        </TabsContent>

        <TabsContent value="scorecard" className="mt-4">
          <Suspense fallback={<div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">Loading scorecard workspace…</div>}>
            <LazyScorecardView config={config} analysisFilters={filterForm} />
          </Suspense>
        </TabsContent>

        <TabsContent value="report" className="mt-4">
          <Suspense fallback={<div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">Loading report workspace…</div>}>
            <LazyReportView />
          </Suspense>
        </TabsContent>

        <TabsContent value="monitoring" className="mt-4">
          <Suspense fallback={<div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">Loading monitoring workspace…</div>}>
            <LazyMonitoringView />
          </Suspense>
        </TabsContent>

        <TabsContent value="configure" className="mt-4">
          <Suspense fallback={<div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">Loading configuration panel…</div>}>
            <LazyConfigureView config={config} onSave={setConfig} />
          </Suspense>
        </TabsContent>
      </Tabs>

      <ExportDialog
        config={config}
        isExporting={isExporting}
        open={isExportDialogOpen}
        selectedOrderAvailable={Boolean(selectedRoute)}
        onExport={handleExport}
        onOpenChange={setIsExportDialogOpen}
      />
    </div>
  );
}
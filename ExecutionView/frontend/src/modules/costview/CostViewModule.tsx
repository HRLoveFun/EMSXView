import { Suspense, lazy, startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, BarChart3, Settings2, Trophy } from 'lucide-react';
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
import { analyzeTca, fetchAllFilteredOrders, getUpdateStatus, triggerUpdate } from './services/api';
import type {
  CostViewConfig,
  CostViewFilterFormState,
  CostViewModuleTab,
  ExportFormat,
  ExportScope,
  TcaFilterPayload,
  TcaReport,
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

export default function CostViewModule() {
  const [activeTab, setActiveTab] = useState<CostViewModuleTab>(() => loadCostViewViewState().activeTab);
  const [config, setConfig] = useState<CostViewConfig>(() => loadCostViewConfig());
  const [filterForm, setFilterForm] = useState<CostViewFilterFormState>(() => loadCostViewFilters());
  const [report, setReport] = useState<TcaReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);
  const [exportState, setExportState] = useState(() => loadCostViewExportState());
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const [fullResultReport, setFullResultReport] = useState<TcaReport | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatusResponse | null>(null);
  const updatePollRef = useRef<number | null>(null);
  const hasLoadedInitialRef = useRef(false);

  const selectedOrder = useMemo(() => report?.orders.find((order) => order.order_id === selectedOrderId) ?? null, [report, selectedOrderId]);

  const clearUpdatePoll = useCallback(() => {
    if (updatePollRef.current) {
      window.clearTimeout(updatePollRef.current);
      updatePollRef.current = null;
    }
  }, []);

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
    return () => {
      clearUpdatePoll();
    };
  }, [clearUpdatePoll]);

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
          if (selectedOrderId && !nextReport.orders.some((order) => order.order_id === selectedOrderId)) {
            setSelectedOrderId(null);
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
          if (selectedOrderId && !nextReport.orders.some((order) => order.order_id === selectedOrderId)) {
            setSelectedOrderId(null);
          }
        });
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unknown CostView error');
      setReport(null);
      setFullResultReport(null);
      setSelectedOrderId(null);
    } finally {
      setIsLoading(false);
    }
  }, [config, selectedOrderId]);

  useEffect(() => {
    if (hasLoadedInitialRef.current) return;
    hasLoadedInitialRef.current = true;
    void fetchReport(filterForm, 0);
  }, [fetchReport, filterForm]);

  const handlePollUpdate = useCallback(async (jobId: string) => {
    try {
      const status = await getUpdateStatus(jobId);
      setUpdateStatus(status);
      clearUpdatePoll();
      if (status.status === 'started' || status.status === 'running') {
        updatePollRef.current = window.setTimeout(() => {
          void handlePollUpdate(jobId);
        }, 2000);
        return;
      }
      if (status.status === 'completed') {
        void fetchReport(filterForm, 0);
      }
    } catch (pollError) {
      setUpdateStatus((current) => ({
        job_id: current?.job_id ?? jobId,
        status: 'failed',
        started_at: current?.started_at ?? new Date().toISOString(),
        completed_at: new Date().toISOString(),
        error: pollError instanceof Error ? pollError.message : 'Polling failed',
        stage: current?.stage ?? null,
        overall_progress: current?.overall_progress ?? 0,
        last_activity_at: current?.last_activity_at ?? new Date().toISOString(),
      }));
    }
  }, [clearUpdatePoll, fetchReport, filterForm]);

  const handleTriggerUpdate = useCallback(async () => {
    setError(null);
    clearUpdatePoll();
    try {
      const job = await triggerUpdate();
      // Preserve backend-returned status/stage for idempotent reconnection
      setUpdateStatus({
        job_id: job.job_id,
        status: (job.status as UpdateStatusResponse['status']) || 'started',
        started_at: new Date().toISOString(),
        completed_at: null,
        error: null,
        stage: null,
        overall_progress: 0,
        last_activity_at: new Date().toISOString(),
      });
      void handlePollUpdate(job.job_id);
    } catch (triggerError) {
      setError(triggerError instanceof Error ? triggerError.message : 'Failed to trigger update');
    }
  }, [clearUpdatePoll, handlePollUpdate]);

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
        if (selectedOrderId && !nextReport.orders.some((order) => order.order_id === selectedOrderId)) {
          setSelectedOrderId(null);
        }
      });
      return;
    }

    void fetchReport(filterForm, offset);
  }, [config, fetchReport, filterForm, fullResultReport, selectedOrderId]);

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
        selectedOrder,
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
  }, [config, filterForm, fullResultReport, report, selectedOrder]);

  return (
    <div className="space-y-4">
      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as CostViewModuleTab)}>
        <TabsList className="grid h-auto w-full grid-cols-4 gap-2 rounded-xl bg-muted/60 p-1 lg:w-fit">
          <TabsTrigger value="overview"><Activity className="h-4 w-4" />Overview</TabsTrigger>
          <TabsTrigger value="analysis"><BarChart3 className="h-4 w-4" />Analysis</TabsTrigger>
          <TabsTrigger value="scorecard"><Trophy className="h-4 w-4" />Scorecard</TabsTrigger>
          <TabsTrigger value="configure"><Settings2 className="h-4 w-4" />Configure</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-4">
          <OverviewView
            config={config}
            error={error}
            exportState={exportState}
            isLoading={isLoading}
            report={report}
            updateStatus={updateStatus}
            onGoToAnalysis={handleOpenAnalysis}
            onOpenExport={() => setExportDialogOpen(true)}
            onRefresh={() => void fetchReport(filterForm, 0)}
            onTriggerUpdate={() => void handleTriggerUpdate()}
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
              selectedOrder={selectedOrder}
              updateStatus={updateStatus}
              onFilterChange={setFilterForm}
              onOpenExport={() => setExportDialogOpen(true)}
              onPageChange={handlePageChange}
              onRefresh={() => void fetchReport(filterForm, 0)}
              onResetFilters={handleResetFilters}
              onRunSearch={handleRunSearch}
              onSelectOrder={(order) => setSelectedOrderId(order?.order_id ?? null)}
            />
          </Suspense>
        </TabsContent>

        <TabsContent value="scorecard" className="mt-4">
          <Suspense fallback={<div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">Loading scorecard workspace…</div>}>
            <LazyScorecardView config={config} analysisFilters={filterForm} />
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
        open={exportDialogOpen}
        selectedOrderAvailable={Boolean(selectedOrder)}
        onExport={handleExport}
        onOpenChange={setExportDialogOpen}
      />
    </div>
  );
}
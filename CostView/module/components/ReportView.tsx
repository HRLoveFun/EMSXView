import { useCallback, useState } from 'react';
import { useAsyncData } from '@shared/hooks/use-async-data';
import { FileBarChart, FileDown, RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { fetchBdibHealth, fetchExportHtml, fetchTcaReportSummary, type ExportHtmlThresholdPayload } from '../services/api';
import { loadCostViewConfig } from '../lib/storage';
import {
  formatScopeLabel,
  formatScopeWarning,
} from '../lib/report-format';
import { KpiCards } from './report-view/kpi-cards';
import {
  DailyTrendChart,
  MarketNotionalRankingChart,
  MarketNotionalTrendChart,
  PnlHistogram,
  PwpCurveChart,
  RankingBarChart,
} from './report-view/charts';
import { DateField } from './DateField';
import { SearchableSelect } from './SearchableSelect';
import { SegmentedField } from './SegmentedField';
import { AnomalyTable } from './report/AnomalyTable';
import { BdibHealthAppendix } from './report/BdibHealthAppendix';
import { CoverageTable } from './report/CoverageTable';
import { EvaluationSummary } from './report/EvaluationSummary';
import { ImpactBreakdownTable } from './report/ImpactBreakdownTable';
import { MarketOverviewTable } from './report/MarketOverviewTable';
import type {
  BdibHealthReport,
  CostViewConfig,
  Granularity,
  LastPreset,
  TcaReportSummary,
} from '../types';

/** 时间范围预设选项（与后端 --last 一致） */
const PRESET_OPTIONS: Array<{ value: LastPreset | 'custom'; label: string }> = [
  { value: 'day', label: '最近交易日' },
  { value: 'week', label: '上周' },
  { value: 'month', label: '上月' },
  { value: 'quarter', label: '上季度' },
  { value: 'year', label: '去年' },
  { value: 'custom', label: '指定日期/范围' },
];

/** 026: 聚合粒度选项（day 为默认，与后端 report_measure.GRANULARITIES 同契约） */
const GRANULARITY_OPTIONS: Array<{ value: Granularity; label: string }> = [
  { value: 'day', label: '按日' },
  { value: 'week', label: '按周（ISO 周）' },
  { value: 'month', label: '按月' },
];

interface ReportFormState {
  preset: LastPreset | 'custom';
  startDate: string;
  endDate: string;
  brokers: string[];
  algos: string[];
  symbols: string[];
  markets: string[];
  granularity: Granularity;
}

const DEFAULT_FORM: ReportFormState = {
  preset: 'day',
  startDate: '',
  endDate: '',
  brokers: [],
  algos: [],
  symbols: [],
  markets: [],
  granularity: 'day',
};

/** 初始表单：Report 默认交易所来自 Configure 配置（reportExchanges，空数组 = 全部市场） */
function buildInitialReportForm(): ReportFormState {
  const config = loadCostViewConfig();
  return { ...DEFAULT_FORM, markets: config.reportExchanges ?? [] };
}

/** 报告区间格式化：YYYYMMDD → YYYY-MM-DD */
const formatReportDate = (value: string): string => {
  const match = /^(\d{4})(\d{2})(\d{2})$/.exec(value);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : value || '—';
};

/** 本地阈值规则 → thresholds 请求参数（与后端 ThresholdRules 契约对齐，页面明细与导出 HTML 同源判定） */
const buildThresholdsPayload = (
  rules: CostViewConfig['rules'],
): Record<string, ExportHtmlThresholdPayload> => {
  const thresholds: Record<string, ExportHtmlThresholdPayload> = {};
  for (const rule of Object.values(rules)) {
    thresholds[rule.key] = {
      mode: rule.mode,
      warning: rule.warning,
      critical: rule.critical,
      enabled: rule.enabled,
    };
  }
  return thresholds;
};

export function ReportView() {
  // 初始表单在挂载时构建一次（读取 Configure 中的默认交易所范围）；用 state 固定，
  // 既作 useState 初值、又供「重置」复用（原先用 ref 承载，会在渲染期读 ref）
  const [initialForm] = useState<ReportFormState>(() => buildInitialReportForm());
  const [form, setForm] = useState<ReportFormState>(initialForm);
  const [report, setReport] = useState<TcaReportSummary | null>(null);
  const [health, setHealth] = useState<BdibHealthReport | null>(null);
  const [options, setOptions] = useState<TcaReportSummary['filter_options']>({ brokers: [], algos: [], symbols: [], exchanges: [] });
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  // 构建查询参数（多选 → 逗号分隔；custom → 显式日期区间）
  const buildQuery = useCallback((current: ReportFormState) => {
    const config = loadCostViewConfig();
    const base: Parameters<typeof fetchTcaReportSummary>[0] = {
      broker: current.brokers,
      algo: current.algos,
      symbol: current.symbols,
      minFillCount: config.minFillCount,
      minNotionalUsd: config.minNotionalUsd,
      // 异常路由判定阈值随查询下发（后端默认阈值仅作兜底）
      thresholds: buildThresholdsPayload(config.rules),
      // 026: 聚合粒度（走势与分市场金额趋势的横轴；day 与既有按日口径一致）
      granularity: current.granularity,
    };
    if (current.markets.length) base.exchange = current.markets;
    if (current.preset === 'custom' && current.startDate && current.endDate) {
      base.startDate = current.startDate.replace(/-/g, '');
      base.endDate = current.endDate.replace(/-/g, '');
    } else if (current.preset !== 'custom') {
      base.last = current.preset;
    }
    return base;
  }, []);

  // 首屏三件事（筛选选项 / 报告 / BDIB 健康度）收敛为一个**纯取数**函数（不 setState，只返回数据），
  // 供首屏（useAsyncData）与「生成报告」按钮（事件回调）复用。
  const fetchReportPayload = useCallback(async (current: ReportFormState) => {
    const query = buildQuery(current);
    const metaQuery: Parameters<typeof fetchTcaReportSummary>[0] = { ...query };
    delete (metaQuery as { exchange?: string | string[] }).exchange;

    const [reportData, metaData, healthData] = await Promise.all([
      fetchTcaReportSummary(query),                        // 主报告：失败即整体失败
      fetchTcaReportSummary(metaQuery).catch(() => null),  // 选项：失败不阻断，保持上次清单
      (query.startDate && query.endDate)
        ? fetchBdibHealth({ startDate: query.startDate, endDate: query.endDate }).catch(() => null)
        : Promise.resolve(null),                           // 健康度：同时间范围，失败不阻断主报告
    ]);
    return { reportData, metaData, healthData, appliedPreset: current.preset };
  }, [buildQuery]);

  // 落到 state（首屏在 hook 的数据回调内、按钮路径在 .then 内，均为规则允许的形态）
  const applyReportPayload = useCallback((payload: Awaited<ReturnType<typeof fetchReportPayload>>) => {
    setReport(payload.reportData);
    if (payload.metaData) {
      const next = payload.metaData.filter_options
        ?? { brokers: [], algos: [], symbols: [], exchanges: [] };
      setOptions({
        ...next,
        exchanges: next.exchanges ?? (payload.metaData.markets ?? []).map((m) => m.exchange),
      });
    }
    setHealth(payload.healthData ?? null);
    // 预设模式下回填解析后的实际日期区间（如"上周"→ 周一~周日），
    // 使日期填充框常驻展示；custom 模式下保留用户手输日期不覆盖。
    if (payload.appliedPreset !== 'custom') {
      setForm((prev) => ({
        ...prev,
        startDate: formatReportDate(payload.reportData.filters.start_date),
        endDate: formatReportDate(payload.reportData.filters.end_date),
      }));
    }
  }, []);

  // 首屏：loading 由 key 派生、setState 只在 Promise 回调内
  const { isLoading: isInitialLoading, error: initialError } = useAsyncData(
    'report-initial',
    () => fetchReportPayload(initialForm),
    applyReportPayload,
  );
  const initialLoadError = initialError ? (initialError.message || '报告加载失败') : null;
  // 首屏取数与「生成报告」共用同一忙碌态/错误位（首屏由 hook 派生，按钮路径由本地 state 承载）
  const busy = isLoading || isInitialLoading;
  const loadError = error ?? initialLoadError;

  const updatePreset = (value: string) =>
    setForm((prev) => ({ ...prev, preset: value as ReportFormState['preset'] }));

  // 026: 粒度切换后需重新「生成报告」生效（与时间范围同一交互模型）
  const updateGranularity = (value: string) =>
    setForm((prev) => ({ ...prev, granularity: value as Granularity }));

  // 编辑日期框视为自定义范围：自动切换为"指定日期/范围"预设
  const updateField = (key: 'startDate' | 'endDate') => (value: string) =>
    setForm((prev) => ({ ...prev, preset: 'custom', [key]: value }));

  // 生成报告：重新加载筛选选项（随 broker/algo/symbol 变化）与报告。
  // 事件回调内 setState 属规则允许形态；loading/error 仍由本组件 state 承载（与导出路径共用）。
  const handleGenerate = useCallback(() => {
    setError(null);
    setIsLoading(true);
    fetchReportPayload(form)
      .then(applyReportPayload)
      .catch((nextError: unknown) => {
        setError(nextError instanceof Error ? nextError.message : '报告加载失败');
        setReport(null);
      })
      .finally(() => setIsLoading(false));
  }, [form, fetchReportPayload, applyReportPayload]);

  // 006: 阈值/填充笔数/金额下限统一由 buildQuery 携带（与页面报告同源判定口径）
  const handleExportHtml = useCallback(async () => {
    setIsExporting(true);
    setError(null);
    try {
      await fetchExportHtml(buildQuery(form));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'HTML 报告导出失败');
    } finally {
      setIsExporting(false);
    }
  }, [form, buildQuery]);

  return (
    <div className="space-y-4">
      {/* 过滤栏 */}
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <SegmentedField
            label="时间范围"
            ariaLabel="时间范围"
            options={PRESET_OPTIONS}
            value={form.preset}
            onChange={(value) => updatePreset(value as string)}
          />
          {/* 026: 聚合粒度（走势 / 分市场金额趋势 / 覆盖率分组的横轴语义） */}
          <SegmentedField
            label="聚合粒度"
            ariaLabel="聚合粒度"
            options={GRANULARITY_OPTIONS}
            value={form.granularity}
            onChange={(value) => updateGranularity(value as string)}
          />
          {/* 日期填充框常驻：预设模式下显示解析后的实际区间，编辑后切换为自定义 */}
          <div className="space-y-1">
            <Label className="text-xs">起始日期</Label>
            <DateField label="起始日期" value={form.startDate} onChange={updateField('startDate')} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">截止日期</Label>
            <DateField label="截止日期" value={form.endDate} onChange={updateField('endDate')} />
          </div>
          <SearchableSelect
            label="市场"
            options={options.exchanges ?? []}
            value={form.markets}
            onChange={(values) => setForm((prev) => ({ ...prev, markets: values }))}
            recentScope="report.markets"
            columns={2}
            triggerClassName="w-44"
          />
          <SearchableSelect
            label="Broker"
            options={options.brokers}
            value={form.brokers}
            onChange={(values) => setForm((prev) => ({ ...prev, brokers: values }))}
            recentScope="report.brokers"
            columns={2}
            triggerClassName="w-44"
          />
          <SearchableSelect
            label="Algo"
            options={options.algos}
            value={form.algos}
            onChange={(values) => setForm((prev) => ({ ...prev, algos: values }))}
            recentScope="report.algos"
            triggerClassName="w-44"
          />
          <SearchableSelect
            label="Symbol"
            options={options.symbols}
            value={form.symbols}
            onChange={(values) => setForm((prev) => ({ ...prev, symbols: values }))}
            allowCustom
            recentScope="report.symbols"
            placeholder="搜索或输入 Symbol…"
            triggerClassName="w-56"
          />
          {/* 操作按钮另起一行：占满整行，与上方筛选控件分隔 */}
          <div className="flex w-full items-center gap-3 border-t border-muted pt-3">
            <Button onClick={() => void handleGenerate()} disabled={busy}>
              <RefreshCw className={`mr-2 h-4 w-4 ${busy ? 'animate-spin' : ''}`} />
              生成报告
            </Button>
            <Button variant="outline" onClick={() => void handleExportHtml()} disabled={isExporting}>
              <FileDown className="mr-2 h-4 w-4" />
              {isExporting ? '导出中…' : '导出 HTML 报告'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {loadError && (
        <Alert variant="destructive">
          <AlertTitle>报告加载失败</AlertTitle>
          <AlertDescription>{loadError}</AlertDescription>
        </Alert>
      )}

      {report?.data_source_warning && (
        <Alert>
          <AlertTitle>数据源提示</AlertTitle>
          <AlertDescription>{report.data_source_warning}</AlertDescription>
        </Alert>
      )}

      {report && (
        <>
          {/* 报告头：显示具体日期区间、统计范围与当前筛选条件 */}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/30 px-4 py-3">
            <div className="text-sm font-medium">
              报告区间：{formatReportDate(report.filters.start_date)} ~ {formatReportDate(report.filters.end_date)}
              {report.filters.as_of_date && (
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  数据截至 {formatReportDate(report.filters.as_of_date)}
                </span>
              )}
            </div>
            <div className="text-xs text-muted-foreground">
              {formatScopeLabel(report.filters.scope)}
              {report.filters.scope ? ' · ' : ''}
              市场：{form.markets.length > 0 ? form.markets.join(', ') : '全部'}
              {form.brokers.length > 0 && ` · Broker：${form.brokers.join(', ')}`}
              {form.algos.length > 0 && ` · Algo：${form.algos.join(', ')}`}
              {form.symbols.length > 0 && ` · Symbol：${form.symbols.join(', ')}`}
            </div>
          </div>
          {formatScopeWarning(report.filters.scope) && (
            <Alert variant="destructive">
              <AlertTitle>统计范围提示</AlertTitle>
              <AlertDescription>{formatScopeWarning(report.filters.scope)}</AlertDescription>
            </Alert>
          )}
          <KpiCards
            kpi={report.kpi}
            extra={report.extra_kpis}
            anomaly={report.anomaly}
            weightCoverage={report.weight_coverage}
          />
          {/* 市场概览表（与 HTML 报告「市场概览」对齐） */}
          <MarketOverviewTable rows={report.market_notional_ranking} />
          {/* 008: 市场成交金额（美元）排名 + 每日趋势（单栏纵向排列） */}
          <div className="grid grid-cols-1 gap-4">
            <MarketNotionalRankingChart rows={report.market_notional_ranking} />
            <MarketNotionalTrendChart rows={report.market_notional_trend} />
          </div>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <PnlHistogram data={report.pnl_vwap_histogram} />
            <DailyTrendChart data={report.daily_series} />
            <RankingBarChart title="Broker 排行（加权 pnl_vwap）" rows={report.rankings.by_broker} />
            <RankingBarChart title="Algo 排行（加权 pnl_vwap）" rows={report.rankings.by_algo} />
          </div>
          <PwpCurveChart data={report.pwp_curve} />
          {/* 与 HTML 报告对齐：市场冲击分解 / 异常路由明细 / 综合评估 / 指标覆盖率 / BDIB 缺口附录 */}
          <ImpactBreakdownTable impact={report.impact_breakdown} coverage={report.weight_coverage} />
          <AnomalyTable anomaly={report.anomaly} />
          {/* 027：综合评估摘要（与 HTML 章节同位置、同数据源） */}
          <EvaluationSummary evaluation={report.evaluation} />
          <CoverageTable coverage={report.metric_coverage} />
          <BdibHealthAppendix health={health} />

          {/* 独立 HTML 导出提示 */}
          <Card>
            <CardContent className="flex items-center gap-3 p-4 text-sm text-muted-foreground">
              <FileBarChart className="h-4 w-4 shrink-0" />
              <span>
                导出的 HTML 为自包含文件（内联样式 + SVG 图表，无外部依赖），可邮件分发/离线归档。
                命令行等价：
                <code className="mx-1 rounded bg-muted px-1.5 py-0.5 text-xs">python scripts/reports/generate_tca_report.py --last {form.preset}</code>
              </span>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

import { useCallback, useState } from 'react';
import { useAsyncData } from '@shared/hooks/use-async-data';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { fetchEvaluationReport } from '../services/api';
import { analysisFiltersToPayload } from '../lib/filters';
import type {
  CostViewFilterFormState,
  EvaluationDimensionBlock,
  EvaluationGroupRow,
  EvaluationReport,
  EvaluationReportRequest,
  Granularity,
} from '../types';

/** 算法执行质量综合评估（027）。
 *
 *  **唯一输入是时间范围**（与 Report 同一筛选状态）—— 比较维度、基准、检验方法
 *  均不由用户选择：维度遍历七个、基准与方法全部并列。026 的「选维度 / 选基准 /
 *  选方法」形态已按需求修正移除。
 *
 *  「不可比」不再是终止态：组间比较在控制维度的**共同层内**进行并按层样本量加权
 *  合并，层覆盖率与置信度随行披露。
 */

/** 趋势与稳定性的聚合粒度（与后端 report_measure.GRANULARITIES 同契约） */
const GRANULARITY_OPTIONS: Array<{ value: Granularity; label: string }> = [
  { value: 'day', label: '按日' },
  { value: 'week', label: '按周（ISO 周）' },
  { value: 'month', label: '按月' },
];

const DIMENSION_LABELS: Record<string, string> = {
  broker: '券商',
  strategy: '算法',
  broker_strategy: '券商 × 算法',
  asset_class: '资产类别',
  time_of_day: '交易时段',
  liquidity_adv20: '流动性（ADV20）',
  volatility: '波动率',
};

const CONFIDENCE_LABELS: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
};

const fmt = (value: number | null | undefined, digits = 2, suffix = ''): string =>
  value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(digits)}${suffix}`;

const signed = (value: number | null | undefined, digits = 2): string =>
  value == null || !Number.isFinite(value)
    ? '—'
    : `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`;

interface EvaluationViewProps {
  analysisFilters: CostViewFilterFormState;
}

export function EvaluationView({ analysisFilters }: EvaluationViewProps) {
  const [granularity, setGranularity] = useState<Granularity>('week');
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const buildRequest = useCallback(
    (): EvaluationReportRequest => ({
      filters: analysisFiltersToPayload(analysisFilters),
      granularity,
    }),
    [analysisFilters, granularity],
  );

  const applyReport = useCallback((data: EvaluationReport) => setReport(data), []);

  // 进入视图即按当前时间范围自动评估（无需先做任何选择）
  const { isLoading: isInitialLoading, error: initialError } = useAsyncData(
    'evaluation-initial',
    () => fetchEvaluationReport(buildRequest()),
    applyReport,
  );

  const runEvaluation = useCallback(async () => {
    setIsRunning(true);
    setRunError(null);
    try {
      setReport(await fetchEvaluationReport(buildRequest()));
    } catch (cause) {
      setRunError(cause instanceof Error ? cause.message : '评估失败');
    } finally {
      setIsRunning(false);
    }
  }, [buildRequest]);

  const busy = isRunning || isInitialLoading;
  const error = runError ?? (initialError ? initialError.message || '评估加载失败' : null);
  const disabled = report != null && !report.enabled;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-xl border bg-card p-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">算法执行质量综合评估</h2>
          <p className="text-sm text-muted-foreground">
            按当前时间范围自动评估全部比较维度与基准。组间比较在控制维度（市场 / 时段 /
            流动性 / 波动率）的<b>共同层内</b>进行并按层样本量加权合并，层覆盖率与置信度
            随行披露 —— 构成差异为披露项，不阻断结论。
          </p>
        </div>
        <div className="flex items-end gap-2">
          <div className="space-y-1">
            <Label className="text-xs">趋势粒度</Label>
            <Select
              value={granularity}
              onValueChange={(value) => setGranularity(value as Granularity)}
            >
              <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
              <SelectContent>
                {GRANULARITY_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" onClick={() => void runEvaluation()} disabled={busy}>
            <RefreshCw className={`mr-2 h-4 w-4 ${busy ? 'animate-spin' : ''}`} />
            重新评估
          </Button>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>评估失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {disabled ? (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>评估层未启用</AlertTitle>
          <AlertDescription>
            TCA_EVAL_ENABLED=0；sections 为空<b>不代表</b>无数据，且不提供未校验的均值比较作为回退。
          </AlertDescription>
        </Alert>
      ) : null}

      {report?.enabled && report.sections ? (
        <>
          <ReportOverview report={report} />
          {report.sections.dimensions.map((block) => (
            <DimensionPanel key={block.dimension} block={block} />
          ))}
          <TrendPanel report={report} />
          <RiskAndMarketPanel report={report} />
        </>
      ) : null}
    </div>
  );
}

function ReportOverview({ report }: { report: EvaluationReport }) {
  const credibility = report.sections?.credibility as
    | { total_routes?: number; correction?: string; alpha?: number }
    | undefined;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">评估概要</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2 text-sm md:grid-cols-4">
        <div>
          <span className="text-muted-foreground">区间：</span>
          {report.period.start_date} ~ {report.period.end_date}
        </div>
        <div>
          <span className="text-muted-foreground">样本路由：</span>
          {report.total_routes_considered ?? credibility?.total_routes ?? 0}
          {report.total_routes_capped ? '（已截断）' : ''}
        </div>
        <div>
          <span className="text-muted-foreground">比较维度：</span>
          {report.dimensions_covered.length} 个
        </div>
        <div>
          <span className="text-muted-foreground">主基准 / 校正：</span>
          {report.primary_benchmark} / {credibility?.correction ?? '—'}
        </div>
        <div className="md:col-span-4 text-xs text-muted-foreground">
          基准全部并列：{report.benchmarks.join(' / ')}；检验方法全部并列：t / KS / χ²（校正后 p 值为准）。
        </div>
      </CardContent>
    </Card>
  );
}

function DimensionPanel({ block }: { block: EvaluationDimensionBlock }) {
  const label = DIMENSION_LABELS[block.dimension] ?? block.dimension;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">
          {label}
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {block.groups_reported} / {block.group_count} 组
            {block.truncated ? '（按样本量截断）' : ''} · 主基准 {block.primary_benchmark}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-2 py-1">分组</th>
                <th className="px-2 py-1 text-right">样本量</th>
                <th className="px-2 py-1 text-right">相对其余（层内加权）</th>
                <th className="px-2 py-1 text-right">可信区间</th>
                <th className="px-2 py-1 text-right">层数 / 覆盖</th>
                <th className="px-2 py-1">置信度</th>
                <th className="px-2 py-1 text-right">校正后 p</th>
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row) => (
                <GroupRow key={row.label} row={row} />
              ))}
            </tbody>
          </table>
        </div>
        <DimensionNotes block={block} />
      </CardContent>
    </Card>
  );
}

function GroupRow({ row }: { row: EvaluationGroupRow }) {
  const stratified = row.vs_others;
  const primary = row.tests['t-test'];
  return (
    <tr className="border-b border-border/60">
      <td className="px-2 py-1">
        {row.label}
        {row.undersized ? <span className="ml-1 text-xs text-amber-600">样本不足</span> : null}
      </td>
      <td className="px-2 py-1 text-right font-mono">{row.sample_size}</td>
      <td className="px-2 py-1 text-right font-mono">{signed(stratified.difference)}</td>
      <td className="px-2 py-1 text-right font-mono">
        [{signed(row.ci[0])}, {signed(row.ci[1])}]
      </td>
      <td className="px-2 py-1 text-right font-mono">
        {stratified.strata_used} / {fmt(stratified.coverage * 100, 0, '%')}
        {stratified.stratified ? '' : '（未分层）'}
      </td>
      <td className="px-2 py-1">{CONFIDENCE_LABELS[stratified.confidence] ?? stratified.confidence}</td>
      <td className="px-2 py-1 text-right font-mono">{fmt(primary?.p_value_adjusted, 4)}</td>
    </tr>
  );
}

function DimensionNotes({ block }: { block: EvaluationDimensionBlock }) {
  const { stratification, highlights } = block;
  const alerts = [...(highlights.alerts ?? []), ...(stratification.alerts ?? [])];
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <div>
        控制维度：{stratification.dimensions.join(' / ')}；构成失衡（最差两两 TVD）：
        {stratification.dimensions
          .map((dim) => `${dim} ${fmt(stratification.imbalance[dim], 2)}`)
          .join('，')}
      </div>
      {highlights.best || highlights.worst ? (
        <div>
          最优 {highlights.best?.label ?? '—'}（{signed(highlights.best?.difference)}）；
          最差 {highlights.worst?.label ?? '—'}（{signed(highlights.worst?.difference)}）；
          可检测效应 ≈ {fmt(highlights.minimum_detectable_effect)}
        </div>
      ) : null}
      {alerts.length ? (
        <ul className="list-disc pl-5">
          {alerts.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function TrendPanel({ report }: { report: EvaluationReport }) {
  const trend = report.sections?.trend;
  if (!trend || !trend.series.length) {
    return null;
  }
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">
          时间趋势与稳定性
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {trend.granularity} · {trend.periods} 个期间
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="px-2 py-1">期间</th>
              <th className="px-2 py-1 text-right">样本量</th>
              <th className="px-2 py-1 text-right">均值</th>
              <th className="px-2 py-1 text-right">中位数</th>
              <th className="px-2 py-1 text-right">p95</th>
              <th className="px-2 py-1 text-right">CVaR</th>
              <th className="px-2 py-1 text-right">标准差</th>
            </tr>
          </thead>
          <tbody>
            {trend.series.map((point) => (
              <tr key={point.period} className="border-b border-border/60">
                <td className="px-2 py-1">{point.period}</td>
                <td className="px-2 py-1 text-right font-mono">{point.n}</td>
                <td className="px-2 py-1 text-right font-mono">{signed(point.mean)}</td>
                <td className="px-2 py-1 text-right font-mono">{signed(point.median)}</td>
                <td className="px-2 py-1 text-right font-mono">{signed(point.p95)}</td>
                <td className="px-2 py-1 text-right font-mono">{signed(point.cvar)}</td>
                <td className="px-2 py-1 text-right font-mono">{fmt(point.stddev)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function RiskAndMarketPanel({ report }: { report: EvaluationReport }) {
  const risk = report.sections?.risk ?? {};
  const market = report.sections?.market;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">风险与尾部（各基准并列）</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-2 py-1">基准</th>
                <th className="px-2 py-1 text-right">样本量</th>
                <th className="px-2 py-1 text-right">均值</th>
                <th className="px-2 py-1 text-right">p95</th>
                <th className="px-2 py-1 text-right">CVaR</th>
                <th className="px-2 py-1 text-right">尾部占比</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(risk).map(([name, stats]) => (
                <tr key={name} className="border-b border-border/60">
                  <td className="px-2 py-1">{name}</td>
                  <td className="px-2 py-1 text-right font-mono">{stats.n}</td>
                  <td className="px-2 py-1 text-right font-mono">{signed(stats.mean)}</td>
                  <td className="px-2 py-1 text-right font-mono">{signed(stats.p95)}</td>
                  <td className="px-2 py-1 text-right font-mono">{signed(stats.cvar)}</td>
                  <td className="px-2 py-1 text-right font-mono">
                    {fmt(stats.tail_share == null ? null : stats.tail_share * 100, 1, '%')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">
            市场维度
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {market?.rows.length ?? 0} 个市场 · 主基准 {market?.primary_benchmark ?? '—'}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="max-h-80 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-2 py-1">市场</th>
                <th className="px-2 py-1 text-right">样本量</th>
                <th className="px-2 py-1 text-right">均值</th>
                <th className="px-2 py-1 text-right">中位数</th>
                <th className="px-2 py-1 text-right">p95</th>
              </tr>
            </thead>
            <tbody>
              {(market?.rows ?? []).map((row) => (
                <tr key={row.exchange} className="border-b border-border/60">
                  <td className="px-2 py-1">{row.exchange}</td>
                  <td className="px-2 py-1 text-right font-mono">{row.sample_size}</td>
                  <td className="px-2 py-1 text-right font-mono">{signed(row.mean)}</td>
                  <td className="px-2 py-1 text-right font-mono">{signed(row.median)}</td>
                  <td className="px-2 py-1 text-right font-mono">{signed(row.p95)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

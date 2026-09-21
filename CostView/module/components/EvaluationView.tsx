import { useCallback, useState } from 'react';
import { AlertTriangle, RefreshCw, ShieldCheck, ShieldX } from 'lucide-react';
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
import { fetchEvaluationComparison } from '../services/api';
import { analysisFiltersToPayload } from '../lib/filters';
import type {
  CostViewFilterFormState,
  EvaluationBenchmark,
  EvaluationComparisonReport,
  EvaluationCorrection,
  EvaluationMethod,
  ScorecardCohort,
} from '../types';

/** 026 阶段三：评估层视图（可比性判定 / 统计检验 / 功效指引）。
 *
 *  三条约束都在**服务端**执行，本组件只做呈现、不承担约束责任：
 *  - 不可比时后端不返回比较数值，故此处渲染「不可比」判定而非空表；
 *  - 基准必填（D1 基准冻结，服务端无默认值）；
 *  - 未校正与校正后的 p 值**并列**展示，不掩盖多重比较代价。
 */

const COHORT_OPTIONS: Array<{ value: ScorecardCohort; label: string }> = [
  { value: 'broker', label: 'Broker' },
  { value: 'strategy', label: 'Strategy (algo)' },
  { value: 'broker_strategy', label: 'Broker × Strategy' },
  { value: 'asset_class', label: 'Asset class' },
  { value: 'time_of_day', label: 'Time of day' },
  { value: 'liquidity_adv20', label: 'Liquidity (ADV20)' },
  { value: 'volatility', label: 'Volatility' },
];

const BENCHMARK_OPTIONS: Array<{ value: EvaluationBenchmark; label: string }> = [
  { value: 'vwap', label: 'VWAP' },
  { value: 'arrival', label: 'Arrival' },
  { value: 'close', label: 'Close' },
  { value: 'is', label: 'Implementation shortfall' },
];

const METHOD_OPTIONS: Array<{ value: EvaluationMethod; label: string; hint: string }> = [
  { value: 't-test', label: 't 检验 (Welch)', hint: '比较均值，对尾部不敏感' },
  { value: 'ks', label: 'Kolmogorov-Smirnov', hint: '比较整条分布，不假设正态' },
  { value: 'chi2', label: 'χ²（分桶）', hint: '看分布形状迁移' },
];

const CORRECTION_OPTIONS: Array<{ value: EvaluationCorrection; label: string }> = [
  { value: 'bh', label: 'Benjamini-Hochberg（FDR）' },
  { value: 'bonferroni', label: 'Bonferroni（FWER）' },
];

/** 单次取数的路由上限（与后端 ``max_orders`` 默认值一致） */
const MAX_ORDERS = 2000;

interface EvaluationViewProps {
  analysisFilters: CostViewFilterFormState;
}

const fmt = (value: number | null | undefined, digits = 3): string =>
  value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);

export function EvaluationView({ analysisFilters }: EvaluationViewProps) {
  const [cohort, setCohort] = useState<ScorecardCohort>('broker');
  const [benchmark, setBenchmark] = useState<EvaluationBenchmark>('vwap');
  const [method, setMethod] = useState<EvaluationMethod>('t-test');
  const [correction, setCorrection] = useState<EvaluationCorrection>('bh');
  const [minGroupSample, setMinGroupSample] = useState(10);
  const [report, setReport] = useState<EvaluationComparisonReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runEvaluation = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const next = await fetchEvaluationComparison({
        cohort,
        benchmark,
        filters: analysisFiltersToPayload(analysisFilters),
        method,
        correction,
        min_group_sample: minGroupSample,
        max_orders: MAX_ORDERS,
      });
      setReport(next);
    } catch (cause) {
      setReport(null);
      setError(cause instanceof Error ? cause.message : '评估请求失败');
    } finally {
      setIsLoading(false);
    }
  }, [cohort, benchmark, method, correction, minGroupSample, analysisFilters]);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-xl border bg-card p-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">算法执行质量评估</h2>
          <p className="text-sm text-muted-foreground">
            可比性判定 + 统计检验 + 样本功效。推断在**服务端**执行：不满足可比性条件时后端
            不返回比较数值，因此页面不会出现「未经校验的均值排序」。
          </p>
        </div>
        <Button variant="outline" onClick={() => void runEvaluation()} disabled={isLoading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
          {report ? '重新评估' : '开始评估'}
        </Button>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>评估失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">评估设置</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-4">
          <div className="space-y-1">
            <Label className="text-xs">比较维度</Label>
            <Select value={cohort} onValueChange={(value) => setCohort(value as ScorecardCohort)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {COHORT_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">基准（必填）</Label>
            <Select
              value={benchmark}
              onValueChange={(value) => setBenchmark(value as EvaluationBenchmark)}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {BENCHMARK_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              基准冻结：服务端不设默认值，避免事后挑选最有利基准。
            </p>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">检验方法</Label>
            <Select value={method} onValueChange={(value) => setMethod(value as EvaluationMethod)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {METHOD_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {METHOD_OPTIONS.find((option) => option.value === method)?.hint}
            </p>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">多重比较校正</Label>
            <Select
              value={correction}
              onValueChange={(value) => setCorrection(value as EvaluationCorrection)}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {CORRECTION_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="pt-1">
              <Label className="text-xs">最小分组样本</Label>
              <Input
                type="number"
                min={2}
                max={1000}
                value={minGroupSample}
                onChange={(event) =>
                  setMinGroupSample(Math.max(2, Math.min(1000, Number(event.target.value) || 2)))
                }
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {report ? <EvaluationResult report={report} /> : null}
    </div>
  );
}

function EvaluationResult({ report }: { report: EvaluationComparisonReport }) {
  if (!report.enabled) {
    return (
      <Alert>
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>评估层未启用</AlertTitle>
        <AlertDescription>
          TCA_EVAL_ENABLED=0；comparisons 为空**不代表**无可比数据，
          且不提供未校验的均值比较作为回退。
        </AlertDescription>
      </Alert>
    );
  }

  const verdict = report.verdict;
  const comparable = Boolean(verdict?.comparable);

  return (
    <>
      {comparable ? (
        <Alert>
          <ShieldCheck className="h-4 w-4" />
          <AlertTitle>可比性判定通过</AlertTitle>
          <AlertDescription>
            共有分层 {verdict?.common_strata ?? 0} 个；分层分布失衡度均在阈值内，比较结论具备解释力。
          </AlertDescription>
        </Alert>
      ) : (
        <Alert variant="destructive">
          <ShieldX className="h-4 w-4" />
          <AlertTitle>样本不可比 —— 不输出比较结论</AlertTitle>
          <AlertDescription>
            <ul className="mt-1 list-disc pl-5">
              {(verdict?.reasons ?? ['原因未知']).map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            <p className="mt-2 text-xs">
              失衡维度：{(verdict?.unmet_dimensions ?? []).join('、') || '—'}；
              共有分层 {verdict?.common_strata ?? 0} 个。
              按 B3，跨经纪商 / 跨策略比较只有在执行环境足够相似时才具有解释力。
            </p>
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">分组样本量（{report.dimension}）</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-2 py-1">分组</th>
                <th className="px-2 py-1 text-right">样本量</th>
              </tr>
            </thead>
            <tbody>
              {report.groups.map((group) => (
                <tr key={group.label} className="border-b border-border/60">
                  <td className="px-2 py-1">{group.label}</td>
                  <td className="px-2 py-1 text-right font-mono">{group.sample_size}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {report.comparisons.length ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              两两比较（基准 {report.benchmark} · 指标 {report.benchmark_metric}）
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-2 py-1">组 A</th>
                  <th className="px-2 py-1">组 B</th>
                  <th className="px-2 py-1 text-right">n</th>
                  <th className="px-2 py-1 text-right">均值差</th>
                  <th className="px-2 py-1 text-right">区间</th>
                  <th className="px-2 py-1 text-right">p</th>
                  <th className="px-2 py-1 text-right">p（校正）</th>
                  <th className="px-2 py-1">结论</th>
                </tr>
              </thead>
              <tbody>
                {report.comparisons.map((pair) => (
                  <tr
                    key={`${pair.left}|${pair.right}`}
                    className="border-b border-border/60"
                  >
                    <td className="px-2 py-1">{pair.left}</td>
                    <td className="px-2 py-1">{pair.right}</td>
                    <td className="px-2 py-1 text-right font-mono">
                      {pair.n_left}/{pair.n_right}
                    </td>
                    <td className="px-2 py-1 text-right font-mono">{fmt(pair.difference)}</td>
                    <td className="px-2 py-1 text-right font-mono">
                      [{fmt(pair.ci_low)}, {fmt(pair.ci_high)}]
                    </td>
                    <td className="px-2 py-1 text-right font-mono">{fmt(pair.p_value, 4)}</td>
                    <td className="px-2 py-1 text-right font-mono">
                      {fmt(pair.p_value_adjusted, 4)}
                    </td>
                    <td className="px-2 py-1">
                      {pair.note
                        ? pair.note
                        : pair.significant
                          ? '差异显著'
                          : '未检出显著差异'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted-foreground">
              结论以**校正后** p 值为准；未校正值一并列出，以便看到多重比较的代价。
            </p>
          </CardContent>
        </Card>
      ) : null}

      {report.power ? (
        <p className="text-xs text-muted-foreground">
          样本功效：最小分组 {report.power.smallest_group_size} 条（门槛 {report.power.min_group_sample}，
          {report.power.sufficient ? '达标' : '未达标'}）；当前样本量下可检测的最小效应 ≈{' '}
          {fmt(report.power.minimum_detectable_effect)} —— 低于该幅度的差异即使真实存在也无法被检出。
        </p>
      ) : null}

      {report.total_routes_capped ? (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>样本已截断</AlertTitle>
          <AlertDescription>
            本次仅取前 {report.total_routes_considered ?? 0} 条路由参与评估，结论覆盖范围有限。
          </AlertDescription>
        </Alert>
      ) : null}
    </>
  );
}

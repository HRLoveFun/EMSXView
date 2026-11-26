import { useState } from 'react';
import { useAsyncData } from '@shared/hooks/use-async-data';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { FileText, Loader2, RefreshCw } from 'lucide-react';
import {
  fetchExecutionBrief,
  fetchTraderFilterOptions,
  type ExecutionBriefQuery,
} from '../../services/api';
import type { BriefPeriodPreset } from '../../types';
import { DateField } from '../DateField';
import { SearchableSelect } from '../SearchableSelect';
import { SegmentedField } from '../SegmentedField';
import { AnomalyPanel, CompletionBucketsTable, DataAvailabilityPanel, DimensionMixTable, SideSplitTable, TopOrdersTable } from './BriefTables';
import { BriefKpiCards } from './BriefKpiCards';

const PERIOD_OPTIONS: Array<{ value: BriefPeriodPreset; label: string; title: string }> = [
  { value: 'day', label: '每日', title: '最近一个有数据的交易日' },
  { value: 'week', label: '每周', title: '上周一至上周日（与 TCA 报告同一预设）' },
  { value: 'month', label: '每月', title: '上一个自然月' },
  { value: 'quarter', label: '每季', title: '上一个自然季度' },
  { value: 'year', label: '每年', title: '去年全年' },
  { value: 'custom', label: '自定义', title: '指定起始与截止日期' },
];

const SIDE_OPTIONS = [
  { value: 'BUY', label: '买入' },
  { value: 'SELL', label: '卖出' },
];

const TOP_N_OPTIONS = [
  { value: '5', label: 'Top 5' },
  { value: '10', label: 'Top 10' },
  { value: '20', label: 'Top 20' },
];

type OrderMetric = 'by_arrival' | 'by_unfilled' | 'by_opportunity';

interface BriefFilterForm {
  traders: string[];
  tickers: string[];
  exchanges: string[];
  sides: string[];
  strategyTypes: string[];
  algos: string[];
  brokers: string[];
}

const EMPTY_FILTERS: BriefFilterForm = {
  traders: [], tickers: [], exchanges: [], sides: [],
  strategyTypes: [], algos: [], brokers: [],
};

/** 执行简报主视图（230）：期间选择 + 订单级摘要 + 待处理订单 + 数据缺口。 */
export function ExecutionBriefView() {
  const [preset, setPreset] = useState<BriefPeriodPreset>('day');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [filters, setFilters] = useState<BriefFilterForm>(EMPTY_FILTERS);
  const [topN, setTopN] = useState(10);
  const [applied, setApplied] = useState<ExecutionBriefQuery>({ preset: 'day', topN: 10 });
  const [metric, setMetric] = useState<OrderMetric>('by_arrival');
  const [formError, setFormError] = useState<string | null>(null);

  const options = useAsyncData('brief-filter-options', () => fetchTraderFilterOptions());
  const queryKey = applied.preset === 'custom'
    && (!applied.startDate || !applied.endDate)
    ? null
    : JSON.stringify(applied);
  const brief = useAsyncData(queryKey, () => fetchExecutionBrief(applied));

  const patch = (update: Partial<BriefFilterForm>) =>
    setFilters((current) => ({ ...current, ...update }));

  const changePreset = (value: BriefPeriodPreset) => {
    setPreset(value);
    setFormError(null);
    if (value !== 'custom') {
      // 相对期间无需额外输入：直接生效，保持「选每日/每周即刷新」的直觉。
      setApplied((current) => ({
        ...current, preset: value, startDate: undefined, endDate: undefined,
      }));
    }
  };

  const generate = () => {
    if (preset === 'custom') {
      if (!startDate || !endDate) {
        setFormError('自定义区间需同时选择起始日期与截止日期。');
        return;
      }
      if (startDate > endDate) {
        setFormError('起始日期不能晚于截止日期。');
        return;
      }
    }
    setFormError(null);
    setApplied({
      preset,
      startDate: preset === 'custom' ? startDate : undefined,
      endDate: preset === 'custom' ? endDate : undefined,
      topN,
      ...filters,
    });
  };

  const data = brief.data;
  // 筛选下拉是可选增强：其加载不阻塞主查询（否则选项接口慢会卡住「生成简报」）
  const loading = brief.isLoading;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold">
                <FileText className="h-4 w-4" />
                执行简报
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                订单级执行摘要：概览、完成、成本、待处理订单与数据缺口。期间可选每日 / 每周 / 每月 / 每季 / 每年或自定义区间。
              </div>
            </div>
            <Button onClick={generate} disabled={loading}>
              <RefreshCw className={`mr-2 h-4 w-4 ${brief.isLoading ? 'animate-spin' : ''}`} />
              生成简报
            </Button>
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <SegmentedField
              label="期间"
              ariaLabel="执行简报期间"
              options={PERIOD_OPTIONS}
              value={preset}
              onChange={(value) => changePreset(value as BriefPeriodPreset)}
            />
            {preset === 'custom' && (
              <>
                <div className="space-y-1">
                  <span className="text-xs text-muted-foreground">起始日期</span>
                  <DateField label="起始日期" value={startDate} onChange={setStartDate} />
                </div>
                <div className="space-y-1">
                  <span className="text-xs text-muted-foreground">截止日期</span>
                  <DateField label="截止日期" value={endDate} onChange={setEndDate} />
                </div>
              </>
            )}
            <SegmentedField
              label="方向"
              ariaLabel="方向筛选"
              options={SIDE_OPTIONS}
              value={filters.sides}
              multiple
              onChange={(value) => patch({ sides: Array.isArray(value) ? value : [value] })}
            />
            <SegmentedField
              label="条数"
              ariaLabel="Top 订单条数"
              options={TOP_N_OPTIONS}
              value={String(topN)}
              onChange={(value) => setTopN(Number(value))}
            />
          </div>

          <div className="flex flex-wrap items-end gap-3 border-t border-muted pt-3">
            <SearchableSelect
              label="交易员"
              options={options.data?.traders ?? []}
              value={filters.traders}
              onChange={(values) => patch({ traders: values })}
              triggerClassName="w-44"
            />
            <SearchableSelect
              label="标的"
              options={options.data?.symbols ?? []}
              value={filters.tickers}
              onChange={(values) => patch({ tickers: values })}
              allowCustom
              triggerClassName="w-56"
            />
            <SearchableSelect
              label="市场"
              options={options.data?.exchanges ?? []}
              value={filters.exchanges}
              onChange={(values) => patch({ exchanges: values })}
              triggerClassName="w-40"
            />
            <SearchableSelect
              label="策略类型"
              options={options.data?.strategy_types ?? []}
              value={filters.strategyTypes}
              onChange={(values) => patch({ strategyTypes: values })}
              triggerClassName="w-44"
            />
            <SearchableSelect
              label="Algo"
              options={options.data?.algos ?? []}
              value={filters.algos}
              onChange={(values) => patch({ algos: values })}
              triggerClassName="w-44"
            />
            <SearchableSelect
              label="Broker"
              options={options.data?.brokers ?? []}
              value={filters.brokers}
              onChange={(values) => patch({ brokers: values })}
              triggerClassName="w-44"
            />
          </div>
        </CardContent>
      </Card>

      {formError && (
        <Alert variant="destructive">
          <AlertTitle>筛选条件不完整</AlertTitle>
          <AlertDescription>{formError}</AlertDescription>
        </Alert>
      )}

      {brief.error && (
        <Alert variant="destructive">
          <AlertTitle>执行简报加载失败</AlertTitle>
          <AlertDescription className="flex items-center justify-between gap-2">
            <span>{brief.error.message}</span>
            <Button variant="outline" size="sm" onClick={brief.reload}>重试</Button>
          </AlertDescription>
        </Alert>
      )}

      {loading && !data && (
        <div className="flex h-32 items-center justify-center gap-2 rounded-xl border border-dashed text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          正在生成执行简报…
        </div>
      )}

      {data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
            <div className="text-sm font-medium text-foreground">
              {data.period.label} · {data.period.start_date} ~ {data.period.end_date}
              {data.period.as_of_date && (
                <span className="ml-2 text-xs font-normal">数据截至 {data.period.as_of_date}</span>
              )}
            </div>
            <div>
              口径 v{data.spec_version} · 订单 {data.coverage.orders.toLocaleString()} · 标的 {data.coverage.symbols.toLocaleString()}
              {data.coverage.fx_missing_orders > 0 && (
                <span className="ml-2 text-amber-600">
                  · USD 未换算 {data.coverage.fx_missing_orders} 单
                </span>
              )}
            </div>
          </div>

          {data.data_source_warning && (
            <Alert>
              <AlertTitle>数据源提示</AlertTitle>
              <AlertDescription>{data.data_source_warning}</AlertDescription>
            </Alert>
          )}

          <BriefKpiCards brief={data} />

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <SideSplitTable sides={data.sides} total={data.overview} />
            <CompletionBucketsTable buckets={data.completion_buckets} />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <DimensionMixTable title="策略类型分布" rows={data.strategy_mix} />
            <DimensionMixTable title="算法分布" rows={data.algo_mix} />
            <DimensionMixTable title="交易员分布" rows={data.top_traders} />
            <DimensionMixTable title="券商分布" rows={data.broker_mix} />
          </div>

          <TopOrdersTable
            topOrders={data.top_orders}
            metric={metric}
            onMetricChange={setMetric}
          />

          <AnomalyPanel anomaly={data.anomaly} />
          <DataAvailabilityPanel items={data.data_availability} notes={data.notes} />
        </>
      )}
    </div>
  );
}

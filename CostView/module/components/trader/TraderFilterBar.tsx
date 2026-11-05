import { useState } from 'react';
import { ArrowDownAZ, ArrowUpAZ, ChevronDown, RefreshCw, SlidersHorizontal } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@shared/lib/utils';
import { FilterSummaryBar, type FilterSummaryChip } from '../FilterSummaryBar';
import { SavedViewBar } from '../SavedViewBar';
import { SearchableSelect } from '../SearchableSelect';
import { SegmentedField, type SegmentedOption } from '../SegmentedField';
import { deleteView, loadSavedViews, saveView, type SavedView } from '../../lib/saved-views';
import {
  INITIAL_TRADER_FILTERS,
  traderFilterSnapshot,
  type TraderViewSnapshot,
} from '../../lib/trader-filters';
import type {
  TraderCompletionBucket,
  TraderFilterOptions,
  TraderFilterState,
  TraderQualityFilter,
  TraderSortKey,
} from '../../types';

const TRADER_VIEW_SCOPE = 'trader';

const COMPLETION_OPTIONS: Array<SegmentedOption<'' | TraderCompletionBucket>> = [
  { value: '', label: '全部' },
  { value: 'lt50', label: '<50%' },
  { value: '50to80', label: '50–80%' },
  { value: '80to100', label: '80–100%' },
  { value: 'eq100', label: '=100%' },
  { value: 'gt100', label: '>100%', title: '超成交' },
];

const QUALITY_FILTERS: Array<SegmentedOption<TraderQualityFilter>> = [
  { value: 'all', label: '全部' },
  { value: 'clean', label: '干净' },
  { value: 'overfill', label: '超成交' },
  { value: 'cost_missing', label: '成本缺失', title: '成本字段缺失' },
  { value: 'par_suspect', label: '参与率存疑', title: '参与率疑似失真' },
  { value: 'single_fill', label: '单笔成交' },
];

const SORT_OPTIONS: Array<SegmentedOption<TraderSortKey>> = [
  { value: 'date', label: '日期' },
  { value: 'completion', label: '完成率' },
  { value: 'arrival_bps', label: 'arrival' },
  { value: 'opp_cost', label: '机会成本' },
  { value: 'notional', label: '金额' },
  { value: 'route_count', label: '路由数' },
];

const SIDE_OPTIONS: Array<SegmentedOption<string>> = [
  { value: '', label: '全部' },
  { value: 'BUY', label: 'BUY' },
  { value: 'SELL', label: 'SELL' },
];

const MAX_CHIP_NAMES = 2;

interface TraderFilterBarProps {
  state: TraderFilterState;
  options: TraderFilterOptions | null;
  isLoading?: boolean;
  onChange: (patch: Partial<TraderFilterState>) => void;
  onRefresh: () => void;
}

function summarize(values: string[], emptyLabel = '全部'): string {
  if (!values.length) return emptyLabel;
  const names = values.slice(0, MAX_CHIP_NAMES).join(', ');
  return values.length > MAX_CHIP_NAMES ? `${names} +${values.length - MAX_CHIP_NAMES}` : names;
}

/** 筛选栏（210 §3.4.1）：常用维度一屏可达，长尾维度收进「更多筛选」，变更即生效并回到第 1 页 */
export function TraderFilterBar({
  state, options, isLoading, onChange, onRefresh,
}: TraderFilterBarProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [views, setViews] = useState<SavedView<TraderViewSnapshot>[]>(
    () => loadSavedViews<TraderViewSnapshot>(TRADER_VIEW_SCOPE),
  );
  const [activeViewId, setActiveViewId] = useState<string | null>(null);

  /** 手动改筛选即脱离当前快捷视图 */
  const update = (patch: Partial<TraderFilterState>) => {
    setActiveViewId(null);
    onChange(patch);
  };

  const applyView = (view: SavedView<TraderViewSnapshot>) => {
    setActiveViewId(view.id);
    onChange({ ...INITIAL_TRADER_FILTERS, ...view.state, page: 0 });
  };

  const handleSaveView = (name: string) => {
    setViews(saveView(TRADER_VIEW_SCOPE, name, traderFilterSnapshot(state)));
  };

  const handleDeleteView = (id: string) => {
    setViews(deleteView(TRADER_VIEW_SCOPE, id));
    if (activeViewId === id) setActiveViewId(null);
  };

  const advancedCount = [
    state.strategyTypes.length > 0,
    state.algos.length > 0,
    state.brokers.length > 0,
    state.completionBucket !== '',
    state.quality !== 'all',
  ].filter(Boolean).length;

  const chips: FilterSummaryChip[] = [];
  if (state.startDate || state.endDate) {
    chips.push({
      key: 'date',
      label: `日期 ${state.startDate || '最近 5 日'}–${state.endDate || '今日'}`,
      onRemove: () => update({ startDate: '', endDate: '' }),
    });
  }
  const dimensionChips: Array<{
    key: keyof TraderFilterState;
    label: string;
    values: string[];
  }> = [
    { key: 'traders', label: '交易员', values: state.traders },
    { key: 'tickers', label: '标的', values: state.tickers },
    { key: 'sides', label: '方向', values: state.sides },
    { key: 'strategyTypes', label: '策略', values: state.strategyTypes },
    { key: 'algos', label: '算法', values: state.algos },
    { key: 'brokers', label: 'Broker', values: state.brokers },
  ];
  dimensionChips.forEach(({ key, label, values }) => {
    if (!values.length) return;
    chips.push({
      key,
      label: `${label}：${summarize(values)}`,
      onRemove: () => update({ [key]: [] } as Partial<TraderFilterState>),
    });
  });
  if (state.completionBucket) {
    const bucket = COMPLETION_OPTIONS.find((item) => item.value === state.completionBucket);
    chips.push({
      key: 'completionBucket',
      label: `完成率：${bucket?.title ?? bucket?.label ?? state.completionBucket}`,
      onRemove: () => update({ completionBucket: '' }),
    });
  }
  if (state.quality !== 'all') {
    const quality = QUALITY_FILTERS.find((item) => item.value === state.quality);
    chips.push({
      key: 'quality',
      label: `质量：${quality?.label ?? state.quality}`,
      onRemove: () => update({ quality: 'all' }),
    });
  }

  const clearAll = () => {
    setActiveViewId(null);
    onChange({
      startDate: '',
      endDate: '',
      traders: [],
      tickers: [],
      sides: [],
      strategyTypes: [],
      algos: [],
      brokers: [],
      completionBucket: '',
      quality: 'all',
    });
  };

  return (
    <div className="space-y-3 rounded-xl border bg-card p-4">
      <SavedViewBar
        views={views}
        activeId={activeViewId}
        onApply={applyView}
        onSave={handleSaveView}
        onDelete={handleDeleteView}
      />

      <div className="grid grid-cols-2 items-end gap-3 md:grid-cols-3 xl:grid-cols-6">
        <DateRangeInput
          key={`start-${state.startDate}`}
          label="开始日期（留空 = 最近 5 交易日）"
          value={state.startDate}
          onCommit={(value) => update({ startDate: value })}
        />
        <DateRangeInput
          key={`end-${state.endDate}`}
          label="结束日期"
          value={state.endDate}
          onCommit={(value) => update({ endDate: value })}
        />
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">交易员</Label>
          <SearchableSelect
            label="交易员"
            options={options?.traders ?? []}
            value={state.traders}
            onChange={(values) => update({ traders: values })}
            recentScope="trader.traders"
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">标的</Label>
          <SearchableSelect
            label="标的"
            options={options?.symbols ?? []}
            value={state.tickers}
            onChange={(values) => update({ tickers: values })}
            allowCustom
            recentScope="trader.tickers"
            placeholder="搜索或输入标的代码…"
            emptyLabel="全部标的"
          />
        </div>
        <SegmentedField
          label="方向"
          options={SIDE_OPTIONS}
          value={state.sides}
          onChange={(values) => update({ sides: values as string[] })}
          multiple
          clearValue=""
        />
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-9" onClick={onRefresh} disabled={isLoading}>
            <RefreshCw className={cn('mr-1 h-3.5 w-3.5', isLoading && 'animate-spin')} />
            刷新
          </Button>
          <Button
            variant={showAdvanced ? 'secondary' : 'outline'}
            size="sm"
            className="h-9"
            aria-expanded={showAdvanced}
            onClick={() => setShowAdvanced((current) => !current)}
          >
            <SlidersHorizontal className="mr-1 h-3.5 w-3.5" />
            更多筛选
            {advancedCount > 0 ? (
              <Badge variant="secondary" className="ml-1 h-4 min-w-4 justify-center px-1 text-[10px]">
                {advancedCount}
              </Badge>
            ) : null}
            <ChevronDown className={cn('ml-1 h-3.5 w-3.5 transition-transform', showAdvanced && 'rotate-180')} />
          </Button>
        </div>
      </div>

      {showAdvanced ? (
        <div className="space-y-3 rounded-lg border border-border/70 bg-muted/20 p-3">
          <div className="grid grid-cols-2 items-end gap-3 md:grid-cols-3">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">策略</Label>
              <SearchableSelect
                label="策略"
                options={options?.strategy_types ?? []}
                value={state.strategyTypes}
                onChange={(values) => update({ strategyTypes: values })}
                recentScope="trader.strategyTypes"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">算法</Label>
              <SearchableSelect
                label="算法"
                options={options?.algos ?? []}
                value={state.algos}
                onChange={(values) => update({ algos: values })}
                recentScope="trader.algos"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Broker</Label>
              <SearchableSelect
                label="Broker"
                options={options?.brokers ?? []}
                value={state.brokers}
                onChange={(values) => update({ brokers: values })}
                recentScope="trader.brokers"
                columns={2}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
            <SegmentedField
              label="完成率区间"
              options={COMPLETION_OPTIONS}
              value={state.completionBucket}
              onChange={(value) => update({ completionBucket: value as '' | TraderCompletionBucket })}
            />
            <SegmentedField
              label="质量筛选"
              options={QUALITY_FILTERS}
              value={state.quality}
              onChange={(value) => update({ quality: value as TraderQualityFilter })}
            />
            <div className="flex items-end gap-2">
              <SegmentedField
                label="排序"
                options={SORT_OPTIONS}
                value={state.sort}
                onChange={(value) => update({ sort: value as TraderSortKey })}
              />
              <Button
                variant="outline"
                size="sm"
                className="h-8 px-2"
                aria-label="切换排序方向"
                onClick={() => update({ sortDir: state.sortDir === 'asc' ? 'desc' : 'asc' })}
              >
                {state.sortDir === 'asc'
                  ? <ArrowUpAZ className="h-4 w-4" />
                  : <ArrowDownAZ className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <FilterSummaryBar
        chips={chips}
        onClearAll={chips.length ? clearAll : undefined}
        emptyLabel="未设置筛选（最近 5 个交易日全部订单）"
      />
    </div>
  );
}

/** 日期输入（YYYY-MM-DD 显示 → YYYYMMDD 提交；空 = 后端默认最近 5 交易日） */
function DateRangeInput({
  label, value, onCommit,
}: { label: string; value: string; onCommit: (value: string) => void }) {
  const [draft, setDraft] = useState(value ? toIsoDate(value) : '');
  return (
    <div className="space-y-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Input
        type="date"
        className="h-9 w-full text-xs"
        aria-label={label}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => onCommit(draft ? draft.replace(/-/g, '') : '')}
        onKeyDown={(event) => {
          if (event.key === 'Enter') onCommit(draft ? draft.replace(/-/g, '') : '');
        }}
      />
    </div>
  );
}

function toIsoDate(yyyymmdd: string): string {
  return `${yyyymmdd.slice(0, 4)}-${yyyymmdd.slice(4, 6)}-${yyyymmdd.slice(6, 8)}`;
}

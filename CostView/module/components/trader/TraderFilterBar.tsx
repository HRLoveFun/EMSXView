import { useState } from 'react';
import { ArrowDownAZ, ArrowUpAZ, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { MultiSelectFilter } from '../MultiSelectFilter';
import type {
  TraderCompletionBucket,
  TraderFilterOptions,
  TraderFilterState,
  TraderQualityFilter,
  TraderSortKey,
} from '../../types';

const COMPLETION_BUCKETS: Array<{ value: TraderCompletionBucket; label: string }> = [
  { value: 'lt50', label: '<50%' },
  { value: '50to80', label: '50–80%' },
  { value: '80to100', label: '80–100%' },
  { value: 'eq100', label: '=100%' },
  { value: 'gt100', label: '>100%（超成交）' },
];

const QUALITY_FILTERS: Array<{ value: TraderQualityFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'clean', label: '干净' },
  { value: 'overfill', label: '超成交' },
  { value: 'cost_missing', label: '成本字段缺失' },
  { value: 'par_suspect', label: '参与率疑似失真' },
  { value: 'single_fill', label: '单笔成交' },
];

const SORT_OPTIONS: Array<{ value: TraderSortKey; label: string }> = [
  { value: 'date', label: '日期' },
  { value: 'completion', label: '完成率' },
  { value: 'arrival_bps', label: 'arrival 成本' },
  { value: 'opp_cost', label: '机会成本' },
  { value: 'notional', label: '成交金额' },
  { value: 'route_count', label: '路由数' },
];

interface TraderFilterBarProps {
  state: TraderFilterState;
  options: TraderFilterOptions | null;
  isLoading?: boolean;
  onChange: (patch: Partial<TraderFilterState>) => void;
  onRefresh: () => void;
}

/** 筛选栏（210 §3.4.1）：多值维度走 MultiSelectFilter，变更即生效并回到第 1 页 */
export function TraderFilterBar({
  state, options, isLoading, onChange, onRefresh,
}: TraderFilterBarProps) {
  return (
    <div className="space-y-3 rounded-xl border bg-card p-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <DateRangeInput
          label="开始日期（留空 = 最近 5 交易日）"
          value={state.startDate}
          onCommit={(value) => onChange({ startDate: value })}
        />
        <DateRangeInput
          label="结束日期"
          value={state.endDate}
          onCommit={(value) => onChange({ endDate: value })}
        />
        <MultiSelectFilter
          label="交易员"
          options={options?.traders ?? []}
          selected={state.traders}
          onChange={(values) => onChange({ traders: values })}
        />
        <MultiSelectFilter
          label="方向"
          options={['BUY', 'SELL']}
          selected={state.sides}
          onChange={(values) => onChange({ sides: values })}
        />
        <MultiSelectFilter
          label="策略"
          options={options?.strategy_types ?? []}
          selected={state.strategyTypes}
          onChange={(values) => onChange({ strategyTypes: values })}
        />
        <MultiSelectFilter
          label="算法"
          options={options?.algos ?? []}
          selected={state.algos}
          onChange={(values) => onChange({ algos: values })}
        />
        <MultiSelectFilter
          label="Broker"
          options={options?.brokers ?? []}
          selected={state.brokers}
          onChange={(values) => onChange({ brokers: values })}
        />
      </div>
      <div className="grid grid-cols-2 items-end gap-3 md:grid-cols-4 xl:grid-cols-6">
        <TickerInput
          options={options?.symbols ?? []}
          value={state.tickers}
          onCommit={(values) => onChange({ tickers: values })}
        />
        <SelectField
          label="完成率区间"
          value={state.completionBucket || 'all'}
          items={[{ value: 'all', label: '全部' }, ...COMPLETION_BUCKETS]}
          onValueChange={(value) => onChange({
            completionBucket: value === 'all' ? '' : (value as TraderCompletionBucket),
          })}
        />
        <SelectField
          label="质量筛选"
          value={state.quality}
          items={QUALITY_FILTERS}
          onValueChange={(value) => onChange({ quality: value as TraderQualityFilter })}
        />
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">排序</Label>
          <div className="flex gap-2">
            <Select
              value={state.sort}
              onValueChange={(value) => onChange({ sort: value as TraderSortKey })}
            >
              <SelectTrigger className="h-9 w-28 text-xs" aria-label="排序字段">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SORT_OPTIONS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="sm"
              className="h-9 px-2"
              aria-label="切换排序方向"
              onClick={() => onChange({ sortDir: state.sortDir === 'asc' ? 'desc' : 'asc' })}
            >
              {state.sortDir === 'asc'
                ? <ArrowUpAZ className="h-4 w-4" />
                : <ArrowDownAZ className="h-4 w-4" />}
            </Button>
          </div>
        </div>
        <Button variant="outline" size="sm" className="h-9" onClick={onRefresh} disabled={isLoading}>
          <RefreshCw className={`mr-1 h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>
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
        className="h-9 w-40 text-xs"
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

/** ticker 多值输入（逗号分隔 → 数组；datalist 取 filter-options symbols） */
function TickerInput({
  options, value, onCommit,
}: { options: string[]; value: string[]; onCommit: (values: string[]) => void }) {
  const [draft, setDraft] = useState(value.join(','));
  const commit = () => {
    const values = draft.split(',').map((segment) => segment.trim()).filter(Boolean);
    onCommit(values);
  };
  return (
    <div className="space-y-1">
      <Label className="text-xs text-muted-foreground">标的（逗号分隔多值）</Label>
      <Input
        list="trader-ticker-options"
        className="h-9 text-xs"
        placeholder="如 5293154 关联标的…"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') commit();
        }}
      />
      <datalist id="trader-ticker-options">
        {options.slice(0, 100).map((symbol) => (
          <option key={symbol} value={symbol} />
        ))}
      </datalist>
    </div>
  );
}

interface SelectFieldProps {
  label: string;
  value: string;
  items: Array<{ value: string; label: string }>;
  onValueChange: (value: string) => void;
}

function SelectField({ label, value, items, onValueChange }: SelectFieldProps) {
  return (
    <div className="space-y-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger className="h-9 w-40 text-xs" aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function toIsoDate(yyyymmdd: string): string {
  return `${yyyymmdd.slice(0, 4)}-${yyyymmdd.slice(4, 6)}-${yyyymmdd.slice(6, 8)}`;
}

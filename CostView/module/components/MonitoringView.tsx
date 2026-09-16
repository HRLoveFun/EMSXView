import { useCallback, useEffect, useMemo, useState } from 'react';
import { DatabaseZap, RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { fetchBdibHealth, fetchMetricCoverage } from '../services/api';
import {
  loadCostViewMonitoringState,
  saveCostViewMonitoringState,
} from '../lib/storage';
import { ALL_TCA_METRICS, EXPECTED_NULL_METRICS, METRIC_LABELS } from '../lib/monitoring-metrics';
import { CoverageHeatmap } from './CoverageHeatmap';
import type {
  BdibHealthDateEntry,
  BdibHealthReport,
  BdibHealthStatus,
  LastPreset,
  MetricCoverageReport,
  MonitoringViewState,
} from '../types';

const PRESET_OPTIONS: Array<{ value: LastPreset; label: string }> = [
  { value: 'day', label: '最近交易日' },
  { value: 'week', label: '上周' },
  { value: 'month', label: '上月' },
  { value: 'quarter', label: '上季度' },
  { value: 'year', label: '去年' },
];

const STATUS_VARIANT: Record<BdibHealthStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  ok: 'default',
  partial: 'secondary',
  missing: 'destructive',
  unrecoverable: 'outline',
};

const STATUS_LABELS: Record<BdibHealthStatus, string> = {
  ok: '完整',
  partial: '部分缺失',
  missing: '缺失·可回补',
  unrecoverable: '缺失·不可回补',
};

/** 概览统计卡片 */
const SummaryCards = ({ health, coverage }: { health: BdibHealthReport; coverage: MetricCoverageReport | null }) => {
  const { summary } = health;
  const avgCoverage = coverage?.rows.length
    ? coverage.rows.reduce((acc, row) => {
        const values = Object.values(row.coverage).filter((v): v is number => v != null);
        return acc + values.reduce((a, b) => a + b, 0) / (values.length || 1);
      }, 0) / coverage.rows.length
    : null;
  const cards = [
    { label: '监控交易日', value: String(summary.total_dates) },
    { label: '缺口日（可回补）', value: String(summary.recoverable_gap_dates) },
    { label: '缺口日（不可回补）', value: String(summary.unrecoverable_dates) },
    { label: '整体覆盖率均值', value: avgCoverage == null ? '—' : `${avgCoverage.toFixed(1)}%` },
    { label: '最近缺口日期', value: summary.latest_gap_date ?? '无' },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">{card.label}</div>
            <div className="mt-1 text-xl font-semibold">{card.value}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
};

/** 指标勾选开关组（默认全选 18 个） */
const MetricTogglePanel = ({ state, onChange }: { state: MonitoringViewState; onChange: (s: MonitoringViewState) => void }) => {
  const toggle = (metric: string, checked: boolean) => {
    const selected = checked
      ? [...state.selectedMetrics, metric]
      : state.selectedMetrics.filter((m) => m !== metric);
    onChange({ ...state, selectedMetrics: selected });
  };
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-sm">
          <span>指标开关（{state.selectedMetrics.length}/{ALL_TCA_METRICS.length}）</span>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => onChange({ ...state, selectedMetrics: [...ALL_TCA_METRICS] })}>全选</Button>
            <Button variant="ghost" size="sm" onClick={() => onChange({ ...state, selectedMetrics: [] })}>清空</Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-3 gap-x-4 gap-y-2 md:grid-cols-6">
        {ALL_TCA_METRICS.map((metric) => {
          const expected = EXPECTED_NULL_METRICS.has(metric);
          return (
            <label key={metric} className="flex items-center gap-1.5 text-xs" title={METRIC_LABELS[metric]}>
              <Checkbox checked={state.selectedMetrics.includes(metric)} onCheckedChange={(checked) => toggle(metric, checked === true)} />
              <span className="truncate">{metric}</span>
              {expected && <span className="text-[9px] text-slate-500">期望内</span>}
            </label>
          );
        })}
      </CardContent>
    </Card>
  );
};

/** BDIB 健康日期表（点击行下钻） */
const BdibHealthTable = ({ dates, selectedDate, onSelect }: {
  dates: BdibHealthDateEntry[];
  selectedDate: string | null;
  onSelect: (date: string) => void;
}) => (
  <div className="max-h-72 overflow-y-auto">
    <table className="w-full text-xs">
      <thead className="sticky top-0 bg-card">
        <tr className="text-left text-muted-foreground">
          <th className="px-2 py-1.5">日期</th>
          <th className="px-2 py-1.5">状态</th>
          <th className="px-2 py-1.5 text-right">覆盖率</th>
          <th className="px-2 py-1.5 text-right">成交 ticker</th>
          <th className="px-2 py-1.5 text-right">缺口 ticker</th>
          <th className="px-2 py-1.5 text-right">SQLite 行数</th>
          <th className="px-2 py-1.5 text-right">Parquet 行数</th>
          <th className="px-2 py-1.5 text-right">窗口剩余(天)</th>
        </tr>
      </thead>
      <tbody>
        {dates.map((d) => (
          <tr
            key={d.date}
            className={`cursor-pointer border-t border-border/40 hover:bg-muted/40 ${selectedDate === d.date ? 'bg-muted/60' : ''}`}
            onClick={() => onSelect(d.date)}
          >
            <td className="px-2 py-1 font-mono">{d.date}</td>
            <td className="px-2 py-1"><Badge variant={STATUS_VARIANT[d.status]}>{STATUS_LABELS[d.status]}</Badge></td>
            <td className="px-2 py-1 text-right tabular-nums">{d.coverage_pct.toFixed(1)}%</td>
            <td className="px-2 py-1 text-right tabular-nums">{d.fill_tickers}</td>
            <td className="px-2 py-1 text-right tabular-nums">{d.missing_ticker_count}</td>
            <td className="px-2 py-1 text-right tabular-nums">{d.sqlite_rows.toLocaleString()}</td>
            <td className="px-2 py-1 text-right tabular-nums">{d.parquet_rows.toLocaleString()}</td>
            <td className="px-2 py-1 text-right tabular-nums">{d.retention_days_left}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

/** 选中日期缺口明细 */
const GapDetail = ({ entry }: { entry: BdibHealthDateEntry }) => (
  <div className="space-y-2 text-sm">
    <div className="flex items-center gap-2">
      <DatabaseZap className="h-4 w-4 text-muted-foreground" />
      <span className="font-mono">{entry.date}</span>
      <Badge variant={STATUS_VARIANT[entry.status]}>{STATUS_LABELS[entry.status]}</Badge>
      <span className="text-muted-foreground">缺失 {entry.missing_ticker_count} 个 ticker</span>
    </div>
    <div className="flex flex-wrap gap-1.5">
      {entry.missing_tickers.map((ticker) => (
        <Badge key={ticker} variant="outline" className="font-mono text-xs">{ticker}</Badge>
      ))}
      {entry.missing_ticker_count > entry.missing_tickers.length && (
        <span className="text-xs text-muted-foreground">…共 {entry.missing_ticker_count} 个</span>
      )}
    </div>
    {entry.status !== 'unrecoverable' && entry.missing_ticker_count > 0 && (
      <p className="text-xs text-muted-foreground">
        在保留窗口内，可运行 <code className="rounded bg-muted px-1">python scripts/ops/backfill_bdib_by_market.py</code> 回补。
      </p>
    )}
  </div>
);

export function MonitoringView() {
  const [viewState, setViewState] = useState<MonitoringViewState>(loadCostViewMonitoringState);
  const [health, setHealth] = useState<BdibHealthReport | null>(null);
  const [coverage, setCoverage] = useState<MetricCoverageReport | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    saveCostViewMonitoringState(viewState);
  }, [viewState]);

  const loadData = useCallback(async (state: MonitoringViewState) => {
    setIsLoading(true);
    setError(null);
    try {
      const [healthData, coverageData] = await Promise.all([
        fetchBdibHealth({ last: state.lastPreset }),
        fetchMetricCoverage({ last: state.lastPreset }, state.selectedMetrics),
      ]);
      setHealth(healthData);
      setCoverage(coverageData);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '监控数据加载失败');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData(viewState);
    // 仅在预设变化时重新拉取；指标勾选变化由热力图客户端过滤
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewState.lastPreset, loadData]);

  const bdibStatusByDate = useMemo(
    () => new Map((health?.dates ?? []).map((d) => [d.date, d.status])),
    [health],
  );
  const selectedEntry = health?.dates.find((d) => d.date === selectedDate) ?? null;
  const filteredCoverage = useMemo(() => {
    if (!coverage) return null;
    return { ...coverage, metrics: coverage.metrics.filter((m) => viewState.selectedMetrics.includes(m)) };
  }, [coverage, viewState.selectedMetrics]);

  return (
    <div className="space-y-4">
      {/* 控制栏 */}
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div className="space-y-1">
            <Label className="text-xs">监控范围</Label>
            <Select
              value={viewState.lastPreset}
              onValueChange={(v) => setViewState((prev) => ({ ...prev, lastPreset: v as LastPreset }))}
            >
              <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
              <SelectContent>
                {PRESET_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" onClick={() => void loadData(viewState)} disabled={isLoading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
        </CardContent>
      </Card>

      {error && (
        <Alert variant="destructive">
          <AlertTitle>监控数据加载失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {health && (
        <>
          <SummaryCards health={health} coverage={filteredCoverage} />
          <MetricTogglePanel state={viewState} onChange={setViewState} />
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">指标覆盖率热力图</CardTitle>
            </CardHeader>
            <CardContent>
              <CoverageHeatmap
                rows={filteredCoverage?.rows ?? []}
                metrics={filteredCoverage?.metrics ?? []}
                bdibStatusByDate={bdibStatusByDate}
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">BDIB 健康明细（点击行查看缺口 ticker）</CardTitle>
            </CardHeader>
            <CardContent>
              <BdibHealthTable dates={health.dates} selectedDate={selectedDate} onSelect={setSelectedDate} />
              {selectedEntry && (
                <div className="mt-4 rounded-lg border border-border p-3">
                  <GapDetail entry={selectedEntry} />
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

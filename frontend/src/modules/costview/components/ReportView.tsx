import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FileBarChart, FileDown, RefreshCw } from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
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
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { fetchExportHtml, fetchTcaReportSummary, type ExportHtmlThresholdPayload } from '../services/api';
import { loadCostViewConfig } from '../lib/storage';
import { MultiSelectFilter } from './MultiSelectFilter';
import { SymbolSearchInput } from './SymbolSearchInput';
import type {
  LastPreset,
  TcaRankingRow,
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

interface ReportFormState {
  preset: LastPreset | 'custom';
  startDate: string;
  endDate: string;
  brokers: string[];
  algos: string[];
  symbols: string[];
  markets: string[];
}

const DEFAULT_FORM: ReportFormState = {
  preset: 'day',
  startDate: '',
  endDate: '',
  brokers: [],
  algos: [],
  symbols: [],
  markets: [],
};

/** 初始表单：Report 默认交易所来自 Configure 配置（reportExchanges，空数组 = 全部市场） */
function buildInitialReportForm(): ReportFormState {
  const config = loadCostViewConfig();
  return { ...DEFAULT_FORM, markets: config.reportExchanges ?? [] };
}

const formatNum = (value: number | null, digits = 2): string =>
  value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: digits });

const formatMoney = (value: number | null): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(1)}K`;
  return `$${value.toFixed(0)}`;
};

const formatShares = (value: number): string => {
  if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(0);
};

/** 报告区间格式化：YYYYMMDD → YYYY-MM-DD */
const formatReportDate = (value: string): string => {
  const match = /^(\d{4})(\d{2})(\d{2})$/.exec(value);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : value || '—';
};

/** 总成交金额卡片副标题：fx_rate 覆盖率提示 */
const fxCoverageSub = (coverage: number | null): string => {
  if (coverage == null) return 'USD 换算 · 无 fx_rate';
  const pct = coverage * 100;
  if (pct >= 99) return 'USD 换算 · fx_rate 全覆盖';
  return `USD 换算 · fx_rate 覆盖率 ${pct.toFixed(0)}%`;
};

/** KPI 卡片区 */
const KpiCards = ({ kpi }: { kpi: TcaReportSummary['kpi'] }) => {
  if (!kpi) return null;
  const cards = [
    { label: 'Route 总数', value: kpi.route_count.toLocaleString(), sub: '' },
    { label: '总成交股数', value: formatShares(kpi.total_route_shares), sub: 'RouteShares 合计' },
    { label: '总成交金额（美元）', value: formatMoney(kpi.notional_usd), sub: fxCoverageSub(kpi.fx_coverage) },
    { label: '加权 pnl_vwap', value: formatNum(kpi.weighted_pnl_vwap), sub: '成交额加权 · VWAP 基准' },
    { label: '平均 par_rate', value: formatNum(kpi.avg_par_rate), sub: '参与率均值' },
    { label: '平均 RPM', value: formatNum(kpi.avg_rpm), sub: '' },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">{card.label}</div>
            <div className="mt-1 text-2xl font-semibold">{card.value}</div>
            {card.sub && <div className="mt-0.5 text-[10px] text-muted-foreground">{card.sub}</div>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
};

/** 008: 按市场的成交金额（美元）排名（竖向条形，USD 降序，市场名在 X 轴） */
const MarketNotionalRankingChart = ({ rows = [] }: { rows?: TcaReportSummary['market_notional_ranking'] }) => {
  const shown = rows.filter((r) => r.notional_usd != null);
  return (
    <ChartPanel title="按市场的成交金额（美元）排名" empty={!shown.length}>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={shown} margin={{ top: 4, right: 8, bottom: 24 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis dataKey="name" type="category" fontSize={11} interval={0} height={28} />
          <YAxis type="number" fontSize={11} tickFormatter={(v: number) => formatMoney(v)} />
          <Tooltip formatter={(value: number) => [formatMoney(value), '成交金额（美元）']} />
          <Bar dataKey="notional_usd" fill="#4fc3f7" radius={[2, 2, 0, 0]}>
            {shown.map((row) => (
              <Cell key={row.exchange} fill="#4fc3f7" />
            ))}
            <LabelList dataKey="notional_usd" position="top" fontSize={10} formatter={(v: number) => `${Math.round(v / 1e6)}M`} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
};

/** 008: 按市场的成交金额（美元）每日趋势（Top 10 市场多折线） */
const TOP_TREND_MARKETS = 10;

const MarketNotionalTrendChart = ({ rows = [] }: { rows?: TcaReportSummary['market_notional_trend'] }) => {
  // 取累计成交额最大的 TOP_TREND_MARKETS 个市场（保持可读性）
  const topMarkets = useMemo(() => {
    const total = new Map<string, number>();
    for (const point of rows) {
      total.set(point.exchange, (total.get(point.exchange) ?? 0) + (point.notional_usd ?? 0));
    }
    return Array.from(total.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, TOP_TREND_MARKETS)
      .map(([exchange]) => exchange);
  }, [rows]);

  // 数据透视：date → { date, [exchange]: notional_usd }
  const series = useMemo(() => {
    const byDate = new Map<string, Record<string, number | null>>();
    const order: string[] = [];
    for (const point of rows) {
      if (!topMarkets.includes(point.exchange)) continue;
      const bucket = byDate.get(point.date) ?? {};
      bucket[point.exchange] = point.notional_usd;
      byDate.set(point.date, bucket);
      if (!order.includes(point.date)) order.push(point.date);
    }
    order.sort();
    return {
      points: order.map((date) => ({ date, ...byDate.get(date)! })),
      markets: topMarkets,
    };
  }, [rows, topMarkets]);

  const palette = ['#4fc3f7', '#ffb74d', '#26a69a', '#ab47bc', '#ef5350', '#ffca28', '#66bb6a', '#5c6bc0', '#ec407a', '#8d6e63'];
  return (
    <ChartPanel title={`按市场的成交金额（美元）每日趋势（Top ${TOP_TREND_MARKETS}）`} empty={!series.points.length}>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={series.points}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis dataKey="date" fontSize={11} />
          <YAxis fontSize={11} tickFormatter={(v: number) => formatMoney(v)} />
          <Tooltip formatter={(value: number, name: string) => [formatMoney(value), name]} />
          <Legend />
          {series.markets.map((exchange, i) => (
            <Line
              key={exchange}
              type="monotone"
              dataKey={exchange}
              name={exchange}
              stroke={palette[i % palette.length]}
              // 每个数据点高亮标注：与线同色实心点 + 深色描边（面板背景），
              // 悬停时放大并加粗描边（activeDot）
              dot={(dotProps) => {
                const { cx, cy, stroke, index } = dotProps as {
                  cx?: number; cy?: number; stroke?: string; index?: number;
                };
                if (cx == null || cy == null) return <g key={`dot-${index}`} />;
                return (
                  <circle
                    key={`dot-${index}`}
                    cx={cx}
                    cy={cy}
                    r={3}
                    fill={stroke}
                    stroke="#0f1419"
                    strokeWidth={1.2}
                  />
                );
              }}
              activeDot={{ r: 5.5, stroke: '#0f1419', strokeWidth: 2 }}
              strokeWidth={1.8}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
};

/** pnl_vwap 分布直方图 */
const PnlHistogram = ({ data }: { data: TcaReportSummary['pnl_vwap_histogram'] }) => (
  <ChartPanel title="pnl_vwap 分布" empty={!data.length}>
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
        <XAxis dataKey="lower" tickFormatter={(v: number) => v.toFixed(1)} fontSize={11} />
        <YAxis fontSize={11} />
        <Tooltip
          formatter={(value: number) => [value, 'routes']}
          labelFormatter={(v: number, payload) => {
            const bucket = payload?.[0]?.payload as { lower: number; upper: number } | undefined;
            return bucket ? `[${bucket.lower.toFixed(2)}, ${bucket.upper.toFixed(2)})` : String(v);
          }}
        />
        <Bar dataKey="count" fill="#4fc3f7" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  </ChartPanel>
);

/** 按日加权 pnl_vwap / 平均 par_rate 双折线（双 y 轴） */
const DailyTrendChart = ({ data }: { data: TcaReportSummary['daily_series'] }) => (
  <ChartPanel title="按日走势" empty={!data.length}>
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
        <XAxis dataKey="date" fontSize={11} />
        <YAxis yAxisId="pnl" fontSize={11} />
        <YAxis yAxisId="par" orientation="right" fontSize={11} />
        <Tooltip />
        <Legend />
        <Line yAxisId="pnl" type="monotone" dataKey="weighted_pnl_vwap" name="加权 pnl_vwap" stroke="#4fc3f7" dot={false} strokeWidth={1.8} connectNulls />
        <Line yAxisId="par" type="monotone" dataKey="avg_par_rate" name="平均 par_rate" stroke="#ffb74d" dot={false} strokeWidth={1.8} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  </ChartPanel>
);

/** broker/algo 排行横向条形（正红负绿） */
const RankingBarChart = ({ title, rows }: { title: string; rows: TcaRankingRow[] }) => {
  const shown = rows.slice(0, 10);
  return (
    <ChartPanel title={title} empty={!shown.length}>
      <ResponsiveContainer width="100%" height={Math.max(200, shown.length * 32)}>
        <BarChart data={shown} layout="vertical" margin={{ left: 60 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis type="number" fontSize={11} />
          <YAxis type="category" dataKey="name" fontSize={11} width={80} />
          <Tooltip formatter={(value: number) => [formatNum(value), '加权 pnl_vwap']} />
          <Bar dataKey="weighted_pnl_vwap" radius={[0, 2, 2, 0]}>
            {shown.map((row) => (
              <Cell key={row.name} fill={(row.weighted_pnl_vwap ?? 0) >= 0 ? '#ef5350' : '#26a69a'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
};

/** PWP 五档位均值曲线 */
const PwpCurveChart = ({ data }: { data: TcaReportSummary['pwp_curve'] }) => (
  <ChartPanel title="PWP 分档均值" empty={!data.some((p) => p.avg_pwp != null)}>
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
        <XAxis dataKey="rate" tickFormatter={(v: number) => `${v}%`} fontSize={11} />
        <YAxis fontSize={11} domain={['auto', 'auto']} />
        <Tooltip formatter={(value: number) => [formatNum(value), 'avg PWP']} labelFormatter={(v: number) => `POV ${v}%`} />
        <Line type="monotone" dataKey="avg_pwp" stroke="#4fc3f7" strokeWidth={2} dot={{ r: 4 }} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  </ChartPanel>
);

/** 图表面板容器（空态统一处理） */
const ChartPanel = ({ title, empty, children }: { title: string; empty: boolean; children: React.ReactNode }) => (
  <Card>
    <CardHeader className="pb-2">
      <CardTitle className="text-sm">{title}</CardTitle>
    </CardHeader>
    <CardContent>
      {empty ? (
        <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">无数据</div>
      ) : children}
    </CardContent>
  </Card>
);

export function ReportView() {
  // 初始表单在挂载时构建一次（读取 Configure 中的默认交易所范围）
  const initialFormRef = useRef<ReportFormState | null>(null);
  if (initialFormRef.current === null) {
    initialFormRef.current = buildInitialReportForm();
  }
  const [form, setForm] = useState<ReportFormState>(initialFormRef.current);
  const [report, setReport] = useState<TcaReportSummary | null>(null);
  const [options, setOptions] = useState<TcaReportSummary['filter_options']>({ brokers: [], algos: [], symbols: [], exchanges: [] });
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  // 分市场标签页：'' 表示全部，其余为 Exchange 代码
  const [activeMarket, setActiveMarket] = useState<string>('');

  // 构建查询参数（多选 → 逗号分隔；custom → 显式日期区间）
  const buildQuery = useCallback((current: ReportFormState, market: string = '') => {
    const base: Parameters<typeof fetchTcaReportSummary>[0] = {
      broker: current.brokers,
      algo: current.algos,
      symbol: current.symbols,
    };
    const marketsFilter = [...current.markets];
    if (market) marketsFilter.push(market);
    if (marketsFilter.length) base.exchange = marketsFilter;
    if (current.preset === 'custom' && current.startDate && current.endDate) {
      base.startDate = current.startDate.replace(/-/g, '');
      base.endDate = current.endDate.replace(/-/g, '');
    } else if (current.preset !== 'custom') {
      base.last = current.preset;
    }
    return base;
  }, []);

  // 筛选选项：持久化维度列表（时间无关，daily_update 每日刷新）
  const loadMeta = useCallback(async (current: ReportFormState) => {
    try {
      const query = buildQuery(current, '');
      delete (query as { exchange?: string | string[] }).exchange;
      const data = await fetchTcaReportSummary(query);
      const next = data.filter_options ?? { brokers: [], algos: [], symbols: [], exchanges: [] };
      setOptions({ ...next, exchanges: next.exchanges ?? (data.markets ?? []).map((m) => m.exchange) });
    } catch {
      // 元数据加载失败不阻断报告主体，保持上次清单
    }
  }, [buildQuery]);

  const loadReport = useCallback(async (current: ReportFormState, market: string = '') => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchTcaReportSummary(buildQuery(current, market));
      setReport(data);
      // 预设模式下回填解析后的实际日期区间（如"上周"→ 周一~周日），
      // 使日期填充框常驻展示；custom 模式下保留用户手输日期不覆盖。
      if (current.preset !== 'custom') {
        setForm((prev) => ({
          ...prev,
          startDate: formatReportDate(data.filters.start_date),
          endDate: formatReportDate(data.filters.end_date),
        }));
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '报告加载失败');
      setReport(null);
    } finally {
      setIsLoading(false);
    }
  }, [buildQuery]);

  useEffect(() => {
    const initial = initialFormRef.current!;
    void loadReport(initial);
    void loadMeta(initial);
  }, [loadReport, loadMeta]);

  const updatePreset = (value: string) =>
    setForm((prev) => ({ ...prev, preset: value as ReportFormState['preset'] }));

  // 编辑日期框视为自定义范围：自动切换为"指定日期/范围"预设
  const updateField = (key: 'startDate' | 'endDate') => (event: React.ChangeEvent<HTMLInputElement>) =>
    setForm((prev) => ({ ...prev, preset: 'custom', [key]: event.target.value }));

  // 生成报告：重新加载筛选选项（随 broker/algo/symbol 变化）与当前市场报告
  const handleGenerate = useCallback(() => {
    void loadMeta(form);
    void loadReport(form, activeMarket);
  }, [form, activeMarket, loadMeta, loadReport]);

  // 分市场标签页：切换市场 → 按该 Exchange 重新加载报告（市场清单保持不变）
  const handleMarketChange = useCallback((market: string) => {
    setActiveMarket(market);
    void loadReport(form, market);
  }, [form, loadReport]);

  // 市场标签列表（含全部，选项来自持久化 exchanges 列表，时间无关）
  const marketTabs = useMemo(() => {
    const exchanges = options.exchanges ?? [];
    return [{ exchange: '', label: '全部' }, ...exchanges.map((exchange) => ({ exchange, label: exchange }))];
  }, [options.exchanges]);

  // 006: 本地阈值规则 → 导出端点 thresholds 参数（与后端 DEFAULT_THRESHOLDS 契约对齐）
  const handleExportHtml = useCallback(async () => {
    setIsExporting(true);
    setError(null);
    try {
      const config = loadCostViewConfig();
      const thresholds: Record<string, ExportHtmlThresholdPayload> = {};
      for (const rule of Object.values(config.rules)) {
        thresholds[rule.key] = {
          mode: rule.mode,
          warning: rule.warningThreshold,
          critical: rule.criticalThreshold,
          enabled: rule.enabled,
        };
      }
      await fetchExportHtml({ ...buildQuery(form, activeMarket), thresholds });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'HTML 报告导出失败');
    } finally {
      setIsExporting(false);
    }
  }, [form, activeMarket, buildQuery]);

  return (
    <div className="space-y-4">
      {/* 过滤栏 */}
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div className="space-y-1">
            <Label className="text-xs">时间范围</Label>
            <Select value={form.preset} onValueChange={updatePreset}>
              <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
              <SelectContent>
                {PRESET_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {/* 日期填充框常驻：预设模式下显示解析后的实际区间，编辑后切换为自定义 */}
          <div className="space-y-1">
            <Label className="text-xs">起始日期</Label>
            <Input type="date" className="w-40" value={form.startDate} onChange={updateField('startDate')} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">截止日期</Label>
            <Input type="date" className="w-40" value={form.endDate} onChange={updateField('endDate')} />
          </div>
          <MultiSelectFilter
            label="市场"
            options={options.exchanges ?? []}
            selected={form.markets}
            onChange={(values) => setForm((prev) => ({ ...prev, markets: values }))}
            columns={3}
          />
          <MultiSelectFilter
            label="Broker"
            options={options.brokers}
            selected={form.brokers}
            onChange={(values) => setForm((prev) => ({ ...prev, brokers: values }))}
            columns={3}
          />
          <MultiSelectFilter
            label="Algo"
            options={options.algos}
            selected={form.algos}
            onChange={(values) => setForm((prev) => ({ ...prev, algos: values }))}
          />
          <SymbolSearchInput
            label="Symbol"
            options={options.symbols}
            selected={form.symbols}
            onChange={(values) => setForm((prev) => ({ ...prev, symbols: values }))}
          />
          {/* 操作按钮另起一行：占满整行，与上方筛选控件分隔 */}
          <div className="flex w-full items-center gap-3 border-t border-muted pt-3">
            <Button onClick={() => void handleGenerate()} disabled={isLoading}>
              <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
              生成报告
            </Button>
            <Button variant="outline" onClick={() => void handleExportHtml()} disabled={isExporting}>
              <FileDown className="mr-2 h-4 w-4" />
              {isExporting ? '导出中…' : '导出 HTML 报告'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 分市场标签页：全部 + 各市场（后端 markets 清单驱动） */}
      {marketTabs.length > 1 && (
        <Card>
          <CardContent className="p-3">
            <Tabs value={activeMarket} onValueChange={handleMarketChange}>
              <TabsList className="h-auto w-full flex-wrap justify-start gap-1 bg-muted/60 p-1">
                {marketTabs.map((tab) => (
                  <TabsTrigger key={tab.exchange} value={tab.exchange} className="data-[state=active]:bg-background">
                    {tab.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </CardContent>
        </Card>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertTitle>报告加载失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
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
          {/* 报告头：显示具体日期区间与当前筛选条件 */}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/30 px-4 py-3">
            <div className="text-sm font-medium">
              报告区间：{formatReportDate(report.filters.start_date)} ~ {formatReportDate(report.filters.end_date)}
            </div>
            <div className="text-xs text-muted-foreground">
              市场：{activeMarket || '全部'}
              {form.brokers.length > 0 && ` · Broker：${form.brokers.join(', ')}`}
              {form.algos.length > 0 && ` · Algo：${form.algos.join(', ')}`}
              {form.symbols.length > 0 && ` · Symbol：${form.symbols.join(', ')}`}
            </div>
          </div>
          <KpiCards kpi={report.kpi} />
          {/* 008: 市场成交金额（美元）排名 + 每日趋势（单栏纵向排列，置于最前） */}
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

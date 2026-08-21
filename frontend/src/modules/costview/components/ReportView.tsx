import { useCallback, useEffect, useState } from 'react';
import { FileBarChart, FileDown, RefreshCw } from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
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
import { fetchExportHtml, fetchTcaReportSummary, type ExportHtmlThresholdPayload } from '../services/api';
import { loadCostViewConfig } from '../lib/storage';
import type {
  LastPreset,
  TcaRankingRow,
  TcaReportSummary,
} from '../types';

/** 时间范围预设选项（与后端 --last 一致） */
const PRESET_OPTIONS: Array<{ value: LastPreset; label: string }> = [
  { value: 'day', label: '最近交易日' },
  { value: 'week', label: '上周' },
  { value: 'month', label: '上月' },
  { value: 'quarter', label: '上季度' },
  { value: 'year', label: '去年' },
];

interface ReportFormState {
  preset: LastPreset;
  broker: string;
  algo: string;
  symbol: string;
  exchange: string;
}

const DEFAULT_FORM: ReportFormState = {
  preset: 'day',
  broker: '',
  algo: '',
  symbol: '',
  exchange: '',
};

const formatNum = (value: number | null, digits = 2): string =>
  value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: digits });

const formatShares = (value: number): string => {
  if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(0);
};

/** KPI 卡片区 */
const KpiCards = ({ kpi }: { kpi: TcaReportSummary['kpi'] }) => {
  if (!kpi) return null;
  const cards = [
    { label: 'Route 总数', value: kpi.route_count.toLocaleString() },
    { label: '总成交股数', value: formatShares(kpi.total_route_shares) },
    { label: '加权 pnl_vwap', value: formatNum(kpi.weighted_pnl_vwap) },
    { label: '平均 par_rate', value: formatNum(kpi.avg_par_rate) },
    { label: '平均 RPM', value: formatNum(kpi.avg_rpm) },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">{card.label}</div>
            <div className="mt-1 text-2xl font-semibold">{card.value}</div>
          </CardContent>
        </Card>
      ))}
    </div>
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
  const [form, setForm] = useState<ReportFormState>(DEFAULT_FORM);
  const [report, setReport] = useState<TcaReportSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);

  const loadReport = useCallback(async (current: ReportFormState) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchTcaReportSummary({
        last: current.preset,
        broker: current.broker.trim() || undefined,
        algo: current.algo.trim() || undefined,
        symbol: current.symbol.trim() || undefined,
        exchange: current.exchange.trim() || undefined,
      });
      setReport(data);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '报告加载失败');
      setReport(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadReport(DEFAULT_FORM);
  }, [loadReport]);

  const updateField = (key: keyof ReportFormState) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setForm((prev) => ({ ...prev, [key]: event.target.value }));

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
      await fetchExportHtml({
        last: form.preset,
        broker: form.broker.trim() || undefined,
        algo: form.algo.trim() || undefined,
        symbol: form.symbol.trim() || undefined,
        exchange: form.exchange.trim() || undefined,
        thresholds,
      });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'HTML 报告导出失败');
    } finally {
      setIsExporting(false);
    }
  }, [form]);

  return (
    <div className="space-y-4">
      {/* 过滤栏 */}
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div className="space-y-1">
            <Label className="text-xs">时间范围</Label>
            <Select value={form.preset} onValueChange={(v) => setForm((prev) => ({ ...prev, preset: v as LastPreset }))}>
              <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
              <SelectContent>
                {PRESET_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {(['broker', 'algo', 'symbol', 'exchange'] as const).map((key) => (
            <div key={key} className="space-y-1">
              <Label className="text-xs capitalize">{key}</Label>
              <Input className="w-32" value={form[key]} onChange={updateField(key)} placeholder="全部" />
            </div>
          ))}
          <Button onClick={() => void loadReport(form)} disabled={isLoading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
            生成报告
          </Button>
          <Button variant="outline" onClick={() => void handleExportHtml()} disabled={isExporting}>
            <FileDown className="mr-2 h-4 w-4" />
            {isExporting ? '导出中…' : '导出 HTML 报告'}
          </Button>
        </CardContent>
      </Card>

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
          <KpiCards kpi={report.kpi} />
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

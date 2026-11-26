/** ReportView chart panels (A14/229). Extracted verbatim from ReportView.tsx. */

import { useMemo } from 'react';
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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatMoney, formatNum } from '../../lib/report-format';
import type { TcaRankingRow, TcaReportSummary } from '../../types';

/** 图表面板容器（空态统一处理） */
export const ChartPanel = ({ title, empty, children }: { title: string; empty: boolean; children: React.ReactNode }) => (
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

/** 008: 按市场的成交金额（美元）排名（竖向条形，USD 降序，市场名在 X 轴） */
export const MarketNotionalRankingChart = ({ rows = [] }: { rows?: TcaReportSummary['market_notional_ranking'] }) => {
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

export const MarketNotionalTrendChart = ({ rows = [] }: { rows?: TcaReportSummary['market_notional_trend'] }) => {
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
              // 连接线：0.5 透明度虚线（数据点保持同色实心高亮，不受线样式影响）
              strokeDasharray="4 4"
              strokeOpacity={0.5}
              strokeWidth={1.8}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
};

/** pnl_vwap 分布直方图（附样本量披露：分布仅覆盖 pnl_vwap 非 NULL 的路由） */
export const PnlHistogram = ({ data }: { data: TcaReportSummary['pnl_vwap_histogram'] }) => {
  const buckets = data?.buckets ?? [];
  const samplePct = data?.n_total ? (data.n_used / data.n_total) * 100 : null;
  return (
    <ChartPanel
      title={
        samplePct == null
          ? 'pnl_vwap 分布'
          : `pnl_vwap 分布（样本 ${data.n_used.toLocaleString()}/${data.n_total.toLocaleString()}，${samplePct.toFixed(0)}%）`
      }
      empty={!buckets.length}
    >
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={buckets}>
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
};

/** 按日加权 pnl_vwap / 平均 par_rate 双折线（双 y 轴）。
 *  014: 走势仅含「有数据交易日」（不补零 —— 补 0 会把无数据伪装成零成本），
 *  标题标注实际天数，缺失定位见覆盖率表与 BDIB 缺口附录。 */
export const DailyTrendChart = ({ data }: { data: TcaReportSummary['daily_series'] }) => (
  <ChartPanel
    title={data.length ? `按日走势（${data.length} 个有数据交易日）` : '按日走势'}
    empty={!data.length}
  >
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
export const RankingBarChart = ({ title, rows }: { title: string; rows: TcaRankingRow[] }) => {
  const shown = rows.slice(0, 10);
  return (
    <ChartPanel title={title} empty={!shown.length}>
      <ResponsiveContainer width="100%" height={Math.max(200, shown.length * 32)}>
        <BarChart data={shown} layout="vertical" margin={{ left: 60 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis type="number" fontSize={11} />
          <YAxis type="category" dataKey="name" fontSize={11} width={80} />
          <Tooltip
            formatter={(value: number, _name: unknown, item: unknown) => {
              const row = (item as { payload?: TcaRankingRow } | undefined)?.payload;
              const suffix = row?.n_used != null && row.route_count
                ? `（n=${row.n_used}/${row.route_count}）`
                : '';
              return [`${formatNum(value)}${suffix}`, '加权 pnl_vwap'];
            }}
          />
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
export const PwpCurveChart = ({ data }: { data: TcaReportSummary['pwp_curve'] }) => (
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

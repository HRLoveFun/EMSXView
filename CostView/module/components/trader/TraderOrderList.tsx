import type { KeyboardEvent } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  formatBps,
  formatInt,
  formatNum,
  formatPct,
  formatShares,
} from '../../lib/report-format';
import { TRADER_PAGE_SIZE } from '../../lib/trader-filters';
import { traderRowKey } from '../../lib/trader-rows';
import type { TraderOrderRow, TraderQuality } from '../../types';

const QUALITY_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  bad: 'destructive',
  warn: 'secondary',
  info: 'outline',
  clean: 'default',
};
const QUALITY_LABELS: Record<string, string> = {
  bad: '严重', warn: '警告', info: '提示', clean: '正常',
};
const FLAG_LABELS: Record<string, string> = {
  overfill: '超成交',
  amount_qty_mismatch: '委托股数矛盾',
  cost_missing: '成本缺失',
  par_suspect: '参与率失真',
  single_fill: '单笔成交',
  liquidity_unknown: '流动性未识别',
  latency_anomaly: '延迟异常',
  scheduled_close: '收盘竞价',
};

interface TraderOrderListProps {
  orders: TraderOrderRow[];
  totalOrders: number;
  offset: number;
  onPageChange: (page: number) => void;
  /** 选中订单 → 详情卡（PR-4）；缺省时列表只读 */
  onSelect?: (row: TraderOrderRow) => void;
  /** 当前选中行（order_id + 日期复合键；同日多单不同 ticker 也唯一） */
  selectedKey?: string | null;
}

/** 订单列表（210 §3.4.1）：质量徽章 + mixed 标记；成本列 tooltip 注明「负 = 成本不利」 */
export function TraderOrderList({
  orders,
  totalOrders,
  offset,
  onPageChange,
  onSelect,
  selectedKey,
}: TraderOrderListProps) {
  const page = Math.floor(offset / TRADER_PAGE_SIZE);
  const from = totalOrders === 0 ? 0 : offset + 1;
  const to = Math.min(offset + TRADER_PAGE_SIZE, totalOrders);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          订单明细（{totalOrders.toLocaleString()} 条）
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 z-10 bg-card">
              <tr className="text-muted-foreground">
                {[
                  '日期', '订单', '交易员', '标的', '市场', '方向', '策略', '算法', 'Broker',
                  '路由', '笔数', '委托股数', '成交股数', '完成率', 'VWAP',
                  'arrival (bps)', '机会成本', '跨度', '速度/分钟', '被动占比', '质量',
                ].map((header) => (
                  <th key={header} className="whitespace-nowrap py-1 pr-2 text-left font-medium">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {orders.map((row) => (
                <OrderRowView
                  key={traderRowKey(row)}
                  row={row}
                  selected={selectedKey === traderRowKey(row)}
                  onSelect={onSelect}
                />
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>第 {from.toLocaleString()}–{to.toLocaleString()} 条 / 共 {totalOrders.toLocaleString()} 条</span>
          <div className="flex gap-2">
            <Button
              variant="outline" size="sm" disabled={page === 0}
              onClick={() => onPageChange(page - 1)}
            >
              上一页
            </Button>
            <Button
              variant="outline" size="sm" disabled={to >= totalOrders}
              onClick={() => onPageChange(page + 1)}
            >
              下一页
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function OrderRowView({
  row,
  selected,
  onSelect,
}: {
  row: TraderOrderRow;
  selected: boolean;
  onSelect?: (row: TraderOrderRow) => void;
}) {
  /** 行选择：点击或 Enter/Space（键盘可达，选中态用 aria-selected 表达） */
  const selectProps = onSelect
    ? {
        onClick: () => onSelect(row),
        onKeyDown: (event: KeyboardEvent<HTMLTableRowElement>) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            onSelect(row);
          }
        },
        tabIndex: 0,
        role: 'button',
        'aria-selected': selected,
      }
    : {};
  return (
    <tr
      className={`border-t border-muted ${onSelect ? 'cursor-pointer hover:bg-muted/50' : ''} ${
        selected ? 'bg-primary/10' : ''
      }`}
      {...selectProps}
    >
      <td className="py-0.5 pr-2">{row.order_as_of_date}</td>
      <td className="py-0.5 pr-2 font-mono">{row.order_id}</td>
      <td className="py-0.5 pr-2">{row.trader_name ?? '—'}</td>
      <td className="py-0.5 pr-2">{row.equ_ticker ?? '—'}</td>
      <td className="py-0.5 pr-2 text-muted-foreground">{row.exchange ?? '—'}</td>
      <td className="py-0.5 pr-2">{row.side ?? '—'}</td>
      <td className="py-0.5 pr-2">{row.strategy_type ?? '—'}</td>
      <td className="py-0.5 pr-2">{row.algo ?? '—'}</td>
      <td className="py-0.5 pr-2">{row.broker ?? '—'}</td>
      <td className="py-0.5 pr-2 text-right">
        {formatInt(row.route_count)}
        {row.mixed && <span className="ml-1 text-[10px] text-amber-500">mixed</span>}
      </td>
      <td className="py-0.5 pr-2 text-right">{formatInt(row.fill_count)}</td>
      <td className="py-0.5 pr-2 text-right">{formatShares(row.route_shares)}</td>
      <td className="py-0.5 pr-2 text-right">{formatShares(row.fill)}</td>
      <td className="py-0.5 pr-2 text-right">{formatPct(row.completion)}</td>
      <td className="py-0.5 pr-2 text-right">{formatNum(row.vwap)}</td>
      <td className="py-0.5 pr-2 text-right" title="负 = 成本不利（跑输基准）">
        {formatBps(row.arrival_cost_bps)}
      </td>
      <td className="py-0.5 pr-2 text-right" title="负 = 机会成本不利">
        {formatNum(row.opportunity_cost)}
      </td>
      <td className="py-0.5 pr-2 text-right">
        {row.fill_span_sec == null ? 'N/A' : `${Math.round(row.fill_span_sec / 60)}m`}
      </td>
      <td className="py-0.5 pr-2 text-right">
        {row.speed_shares_per_min == null ? 'N/A' : formatShares(row.speed_shares_per_min)}
      </td>
      <td className="py-0.5 pr-2 text-right" title="当前页逐笔（FIX 851 严格映射）">
        {formatPct(row.passive_ratio)}
      </td>
      <td className="py-0.5 pr-2">
        <QualityBadge quality={row.quality} />
      </td>
    </tr>
  );
}

function QualityBadge({ quality }: { quality: TraderQuality }) {
  if (quality.level === 'clean' && quality.flags.length === 0) {
    return <span className="text-muted-foreground">正常</span>;
  }
  const title = quality.flags.map((flag) => FLAG_LABELS[flag] ?? flag).join('、');
  return (
    <Badge variant={QUALITY_VARIANT[quality.level] ?? 'default'} title={title}>
      {QUALITY_LABELS[quality.level] ?? quality.level}
      {quality.flags.length > 0 && ` · ${quality.flags.length}`}
    </Badge>
  );
}

/** 空态卡（200 + total_orders=0 不是错误） */
export function TraderEmptyState({ message }: { message: string }) {
  return (
    <Card>
      <CardContent className="flex h-40 items-center justify-center text-sm text-muted-foreground">
        {message}
      </CardContent>
    </Card>
  );
}

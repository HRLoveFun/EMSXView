import { useMemo, useState } from 'react';
import { useAsyncData } from '@shared/hooks/use-async-data';
import { AlertCircle, Download, Loader2 } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  exportTraderCsv,
  fetchTraderFilterOptions,
  fetchTraderOrderDetail,
  fetchTraderOrders,
  fetchTraderPeerStats,
  type TraderExportKind,
  type TraderListQuery,
} from '../../services/api';
import { traderRowKey } from '../../lib/trader-rows';
import type { CostViewModuleTab, TraderFilterState, TraderOrderRow } from '../../types';
import { AnomalySummary } from './AnomalySummary';
import { CredibilityBanner } from './CredibilityBanner';
import { OrderReviewCard } from './OrderReviewCard';
import { TraderFilterBar } from './TraderFilterBar';
import { TraderKpiStrip } from './TraderKpiStrip';
import { TRADER_PAGE_SIZE, TraderEmptyState, TraderOrderList } from './TraderOrderList';

/** 选中订单的最小身份（可能来自列表或异常摘要 Top5，后者不在当前页） */
type SelectedOrder = Pick<TraderOrderRow, 'order_id' | 'order_as_of_date'>;

interface TraderReviewViewProps {
  /** 宿主 tab 切换（「查看全部」跳 Report）；缺省时该按钮禁用 */
  onNavigateTab?: (tab: CostViewModuleTab) => void;
}

/** 初始筛选态：日期留空 = 后端默认最近 5 个交易日（210 §3.4.1） */
const INITIAL_FILTERS: TraderFilterState = {
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
  sort: 'date',
  sortDir: 'desc',
  page: 0,
};

/** 筛选态 → 查询参数（空日期/空数组不发送，由后端取默认） */
function toQuery(state: TraderFilterState): TraderListQuery {
  return {
    startDate: state.startDate || undefined,
    endDate: state.endDate || undefined,
    trader: state.traders.length ? state.traders : undefined,
    ticker: state.tickers.length ? state.tickers : undefined,
    side: state.sides.length ? state.sides : undefined,
    strategyType: state.strategyTypes.length ? state.strategyTypes : undefined,
    algo: state.algos.length ? state.algos : undefined,
    broker: state.brokers.length ? state.brokers : undefined,
    completionBucket: state.completionBucket || undefined,
    quality: state.quality,
    sort: state.sort,
    sortDir: state.sortDir,
    limit: TRADER_PAGE_SIZE,
    offset: state.page * TRADER_PAGE_SIZE,
  };
}

/** 交易员复盘台（210 PR-3/4/5）：筛选 + KPI + 可信度横幅 + 异常摘要 + 列表 + 详情卡 */
export function TraderReviewView({ onNavigateTab }: TraderReviewViewProps = {}) {
  const [filters, setFilters] = useState<TraderFilterState>(INITIAL_FILTERS);
  const [selected, setSelected] = useState<SelectedOrder | null>(null);
  const [bucketMin, setBucketMin] = useState(5);
  const [exporting, setExporting] = useState<TraderExportKind | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const options = useAsyncData(
    'trader-filter-options',
    () => fetchTraderFilterOptions(),
  );
  const queryKey = useMemo(() => JSON.stringify(toQuery(filters)), [filters]);
  const orders = useAsyncData(
    queryKey,
    () => fetchTraderOrders(toQuery(filters)),
  );
  // 详情按「订单 + 日期 + 桶宽」取数；未选中时 key=null → 不请求
  const detailKey = selected
    ? `${traderRowKey(selected)}|${bucketMin}`
    : null;
  const detail = useAsyncData(detailKey, () =>
    fetchTraderOrderDetail({
      orderId: selected?.order_id ?? '',
      orderAsOfDate: selected?.order_as_of_date,
      bucketMin,
    }),
  );
  // peer 与详情分开懒加载：同类样本聚合不阻塞详情首屏，失败也不影响其余面板
  const peerKey = selected ? `trader-peer:${traderRowKey(selected)}` : null;
  const peer = useAsyncData(peerKey, () => fetchTraderPeerStats({
    orderId: selected?.order_id ?? '',
    orderAsOfDate: selected?.order_as_of_date,
  }));

  /** 非翻页的筛选变更回到第 1 页（避免停留在越界页） */
  const patch = (update: Partial<TraderFilterState>) => {
    setFilters((current) => ({
      ...current,
      ...update,
      page: 'page' in update ? (update.page ?? 0) : 0,
    }));
  };
  /** 210 §3.4.4：导出使用当前筛选（不含分页）；422 上限错误原样展示并提示缩小范围 */
  const onExport = async (kind: TraderExportKind) => {
    setExporting(kind);
    setExportError(null);
    try {
      await exportTraderCsv(kind, toQuery(filters));
    } catch (error) {
      setExportError(error instanceof Error ? error.message : String(error));
    } finally {
      setExporting(null);
    }
  };
  const payload = orders.data;

  return (
    <div className="space-y-4">
      <TraderFilterBar
        state={filters}
        options={options.data ?? null}
        isLoading={orders.isLoading}
        onChange={patch}
        onRefresh={() => orders.reload()}
      />

      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => void onExport('orders')}
          disabled={!payload || exporting !== null}
        >
          {exporting === 'orders'
            ? <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            : <Download className="mr-1 h-4 w-4" />}
          Export orders CSV
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void onExport('fills')}
          disabled={!payload || exporting !== null}
        >
          {exporting === 'fills'
            ? <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            : <Download className="mr-1 h-4 w-4" />}
          Export fills CSV
        </Button>
      </div>

      {exportError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Export failed</AlertTitle>
          <AlertDescription>
            {exportError} Try again, or narrow the date range if the export is too large.
          </AlertDescription>
        </Alert>
      )}

      {orders.error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>订单查询失败</AlertTitle>
          <AlertDescription className="flex items-center justify-between gap-2">
            <span>{orders.error.message}</span>
            <Button variant="outline" size="sm" onClick={() => orders.reload()}>重试</Button>
          </AlertDescription>
        </Alert>
      )}

      {orders.isLoading && !payload && (
        <div className="flex h-32 items-center justify-center gap-2 rounded-xl border border-dashed text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          正在加载订单列表…
        </div>
      )}

      {payload && (
        <>
          <TraderKpiStrip kpi={payload.kpi} />
          <CredibilityBanner checks={payload.probes.checks} />
          {payload.anomaly_summary && (
            <AnomalySummary
              summary={payload.anomaly_summary}
              onSelectOrder={(orderId, orderAsOfDate) => setSelected({
                order_id: orderId, order_as_of_date: orderAsOfDate,
              })}
              onOpenReport={onNavigateTab ? () => onNavigateTab('report') : undefined}
            />
          )}
          {payload.orders.length === 0 ? (
            <TraderEmptyState message={`当前筛选无订单（${payload.total_orders} 条命中）`} />
          ) : (
            <TraderOrderList
              orders={payload.orders}
              totalOrders={payload.total_orders}
              offset={payload.offset}
              onPageChange={(page) => patch({ page })}
              onSelect={(row) => setSelected((current) =>
                current && traderRowKey(current) === traderRowKey(row)
                  ? null
                  : { order_id: row.order_id, order_as_of_date: row.order_as_of_date })}
              selectedKey={selected ? traderRowKey(selected) : null}
            />
          )}
          {selected && (
            <OrderReviewCard
              detail={detail.data ?? null}
              isLoading={detail.isLoading}
              error={detail.error}
              bucketMin={bucketMin}
              onBucketMinChange={setBucketMin}
              onClose={() => setSelected(null)}
              onRetry={() => detail.reload()}
              peer={peer.data ?? null}
              peerLoading={peer.isLoading}
              peerError={peer.error}
            />
          )}
        </>
      )}
    </div>
  );
}

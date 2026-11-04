import { useMemo, useState } from 'react';
import { useAsyncData } from '@shared/hooks/use-async-data';
import { AlertCircle, Loader2 } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  fetchTraderFilterOptions,
  fetchTraderOrderDetail,
  fetchTraderOrders,
  type TraderListQuery,
} from '../../services/api';
import { traderRowKey } from '../../lib/trader-rows';
import type { TraderFilterState, TraderOrderRow } from '../../types';
import { OrderReviewCard } from './OrderReviewCard';
import { TraderFilterBar } from './TraderFilterBar';
import { TraderKpiStrip, TraderProbesBanner } from './TraderKpiStrip';
import { TRADER_PAGE_SIZE, TraderEmptyState, TraderOrderList } from './TraderOrderList';

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

/** 交易员复盘台（210 PR-3/PR-4）：筛选 + KPI + 可信度横幅 + 订单列表 + 订单详情卡 */
export function TraderReviewView() {
  const [filters, setFilters] = useState<TraderFilterState>(INITIAL_FILTERS);
  const [selected, setSelected] = useState<TraderOrderRow | null>(null);
  const [bucketMin, setBucketMin] = useState(5);
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

  /** 非翻页的筛选变更回到第 1 页（避免停留在越界页） */
  const patch = (update: Partial<TraderFilterState>) => {
    setFilters((current) => ({
      ...current,
      ...update,
      page: 'page' in update ? (update.page ?? 0) : 0,
    }));
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
          <TraderProbesBanner probes={payload.probes.checks} />
          {payload.orders.length === 0 ? (
            <TraderEmptyState message={`当前筛选无订单（${payload.total_orders} 条命中）`} />
          ) : (
            <TraderOrderList
              orders={payload.orders}
              totalOrders={payload.total_orders}
              offset={payload.offset}
              onPageChange={(page) => patch({ page })}
              onSelect={(row) => setSelected((current) =>
                current && traderRowKey(current) === traderRowKey(row) ? null : row)}
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
            />
          )}
        </>
      )}
    </div>
  );
}

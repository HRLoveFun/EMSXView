import type { TraderFilterState } from '../types';
import type { TraderListQuery } from '../services/api';

export const TRADER_PAGE_SIZE = 50;

/** 初始筛选态：日期留空 = 后端默认最近 5 个交易日（210 §3.4.1） */
export const INITIAL_TRADER_FILTERS: TraderFilterState = {
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
export function traderFiltersToQuery(state: TraderFilterState): TraderListQuery {
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

/** Saved View 快照：页码不属于筛选口径，切换视图时固定回第 1 页 */
export type TraderViewSnapshot = Omit<TraderFilterState, 'page'>;

export function traderFilterSnapshot(state: TraderFilterState): TraderViewSnapshot {
  const { page: _page, ...snapshot } = state;
  void _page;
  return snapshot;
}

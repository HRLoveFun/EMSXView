/**
 * 057 DL-29：固定筛选池池板——量价指标 + 执行难度分位 + 预期成本参考值同屏。
 *
 * 仅覆盖现有 4 个固定筛选池；不含当日意图池/观察名单，也不读执行侧运营库。
 * 成本为「100 万美元名义额 → qty ÷ ADV20 参与率」的参考值，不是订单级预测（K3）。
 * 实时 Bid/Ask/Last 来自 core 的 mktdata 订阅（DL-15 + DL-29 池内标的扩展）。
 */

import { useEffect, useMemo } from 'react';

import { useAsyncData } from '@shared/hooks/use-async-data';

import type { MarketStateTickerState, PoolBoardRow } from '../types';
import {
  fetchMarketStateSnapshot,
  fetchPoolBoard,
  subscribeMarketState,
} from '../services/api';
import { fmtCompact, fmtNumber, fmtPercent } from '../marketview-utils';

const LIVE_REFRESH_MS = 5000;

interface PoolBoardPanelProps {
  poolId: string;
  tradeDate?: string | null;
  limit?: number;
}

const GAP_LABELS: Record<string, string> = {
  baseline: '基线缺失',
  cost_model: '成本模型缺失',
  cost_domain: '成本域外',
  adv20: 'ADV20 缺失',
};

const formatGaps = (gaps: string[]): string =>
  gaps.length ? gaps.map((gap) => GAP_LABELS[gap] ?? gap).join(' / ') : '—';

const liveNum = (value: number | null | undefined): string =>
  value != null ? fmtNumber(value, 2) : 'n/a';

const Row = ({ row, live }: { row: PoolBoardRow; live?: MarketStateTickerState }) => (
  <tr className="border-t border-border/60">
    <td className="px-3 py-2 font-medium text-foreground">{row.equ_ticker}</td>
    <td className="px-3 py-2 text-right font-mono text-emerald-500">{liveNum(live?.bid)}</td>
    <td className="px-3 py-2 text-right font-mono text-rose-500">{liveNum(live?.ask)}</td>
    <td className="px-3 py-2 text-right font-mono">{liveNum(live?.last)}</td>
    <td className="px-3 py-2 text-right">{fmtNumber(row.daily_close, 2)}</td>
    <td className="px-3 py-2 text-right">{fmtCompact(row.total_volume)}</td>
    <td className="px-3 py-2 text-right">{fmtPercent(row.volume_vs_adv20_pct, 1)}</td>
    <td className="px-3 py-2 text-right">{fmtPercent(row.daily_volatility, 1)}</td>
    <td className="px-3 py-2 text-right">{fmtNumber(row.log_volume_z, 2)}</td>
    <td className="px-3 py-2 text-right">{fmtPercent(row.vol_percentile, 1)}</td>
    <td className="px-3 py-2 text-right">{fmtNumber(row.adv5_adv60_ratio, 2)}</td>
    <td className="px-3 py-2 text-right font-medium">
      {row.expected_cost_bps != null ? row.expected_cost_bps.toFixed(1) : '—'}
    </td>
    <td className="px-3 py-2 text-right text-muted-foreground">
      {row.timing_risk_bps != null ? row.timing_risk_bps.toFixed(1) : '—'}
    </td>
    <td className={`px-3 py-2 text-xs ${row.data_gaps.length ? 'text-amber-600' : 'text-muted-foreground'}`}>
      {formatGaps(row.data_gaps)}
    </td>
  </tr>
);

export const PoolBoardPanel = ({ poolId, tradeDate, limit = 40 }: PoolBoardPanelProps) => {
  const key = `${poolId}|${tradeDate ?? ''}|${limit}`;
  const { data, isLoading, error, reload } = useAsyncData(key, () =>
    fetchPoolBoard(poolId, tradeDate ?? undefined, limit),
  );
  const { data: live, reload: reloadLive } = useAsyncData('market-state', fetchMarketStateSnapshot);

  // 057 DL-29 增强：把池内标的注册到 core 的 mktdata 订阅（实时价）
  useEffect(() => {
    if (!data?.rows.length) return;
    void subscribeMarketState(data.rows.map((row) => row.equ_ticker)).catch(() => undefined);
  }, [data]);

  // 实时快照轮询
  useEffect(() => {
    const timer = setInterval(() => reloadLive(), LIVE_REFRESH_MS);
    return () => clearInterval(timer);
  }, [reloadLive]);

  const liveByTicker = useMemo(
    () => new Map<string, MarketStateTickerState>(
      (live?.enabled ? live.tickers : []).map((state) => [state.equ_ticker, state]),
    ),
    [live],
  );
  const liveCount = live?.enabled ? live.tickers.length : 0;

  return (
    <div className="overflow-hidden rounded-xl border border-border">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 bg-muted/20 px-4 py-3">
        <div>
          <p className="text-sm font-medium text-foreground">Pool Board · 量价 / 难度 / 成本</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {data?.assumptions.note ?? '固定筛选池只读汇总；成本为参考值，不是订单级预测。'}
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="rounded-full border border-border px-3 py-1">{poolId}</span>
          <span className="rounded-full border border-border px-3 py-1">{data?.row_count ?? 0} rows</span>
          <span className={`rounded-full border px-3 py-1 ${live?.enabled ? 'border-emerald-500/40 text-emerald-600' : 'border-border'}`}>
            {live?.enabled ? `${liveCount} live` : 'live off'}
          </span>
          {data?.assumptions.model_calibrated === false ? (
            <span className="rounded-full border border-amber-500/40 px-3 py-1 text-amber-600">
              模型未校准
            </span>
          ) : null}
          <button
            type="button"
            className="rounded-full border border-border px-3 py-1 transition hover:text-foreground"
            onClick={() => {
              reload();
              reloadLive();
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="p-6 text-sm text-muted-foreground">Loading pool board…</div>
      ) : error ? (
        <div className="p-6 text-sm text-red-700">{error.message}</div>
      ) : data && data.rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1320px] text-sm">
            <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-3 text-left font-medium">Ticker</th>
                <th className="px-3 py-3 text-right font-medium">Bid</th>
                <th className="px-3 py-3 text-right font-medium">Ask</th>
                <th className="px-3 py-3 text-right font-medium">Last</th>
                <th className="px-3 py-3 text-right font-medium">Close</th>
                <th className="px-3 py-3 text-right font-medium">Total Vol</th>
                <th className="px-3 py-3 text-right font-medium">Vol / ADV20</th>
                <th className="px-3 py-3 text-right font-medium">Daily Vol</th>
                <th className="px-3 py-3 text-right font-medium">Log Vol Z</th>
                <th className="px-3 py-3 text-right font-medium">Vol %ile</th>
                <th className="px-3 py-3 text-right font-medium">ADV5/60</th>
                <th className="px-3 py-3 text-right font-medium">Cost bps</th>
                <th className="px-3 py-3 text-right font-medium">Timing bps</th>
                <th className="px-3 py-3 text-left font-medium">Gaps</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <Row key={row.equ_ticker} row={row} live={liveByTicker.get(row.equ_ticker)} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="p-6 text-sm text-muted-foreground">
          No rows for pool “{poolId}” on {data?.trade_date ?? 'the latest trade date'}.
        </div>
      )}
    </div>
  );
};

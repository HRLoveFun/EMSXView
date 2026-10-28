/**
 * 057 DL-29：固定筛选池池板——量价指标 + 执行难度分位 + 预期成本参考值同屏。
 *
 * 仅覆盖现有 4 个固定筛选池；不含当日意图池/观察名单，也不读执行侧运营库。
 * 成本为「100 万美元名义额 → qty ÷ ADV20 参与率」的参考值，不是订单级预测（K3）。
 *
 * 实时列（Last / Chg% / Bid / Ask / Spread / Vol·ADV5）由上层
 * `useMarketStateStream` 提供：core 后端 mktdata 订阅 → `/ws/market-state` 推送，
 * WS 不可用时自动回落 5 秒 REST 轮询；MarketView 不直连 Bloomberg。
 */

import { useEffect } from 'react';

import { useAsyncData } from '@shared/hooks/use-async-data';

import type { LiveQuotes, MarketStateTickerState, PoolBoardRow } from '../types';
import { fetchPoolBoard } from '../services/api';
import {
  fmtCompact,
  fmtNumber,
  fmtPercent,
  isLiveTrading,
  renderMarketStatusBadge,
  renderSecurityName,
} from '../marketview-utils';
import { fmtSignedPercent, liveVolumeVsAdvPct, pctToneClass } from '../lib/workspace';

interface PoolBoardPanelProps {
  poolId: string;
  tradeDate?: string | null;
  limit?: number;
  /** 实时行情索引与来源状态（由 MARKETVIEW 模块统一持有，单条 WS 连接共享）。 */
  live: LiveQuotes;
  /** 中文简称（core refdata 解析结果；缺失显示破折号） */
  names: Map<string, string>;
  /** 把池板标的登记给上层订阅集合（池板无告警筛选，通常是快照的超集）。 */
  onUniverseChange?: (tickers: string[]) => void;
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

const liveCountLabel = (live: LiveQuotes, count: number): string => {
  if (!live.enabled) return 'live off';
  if (live.status === 'live') return `${count} live`;
  if (live.status === 'polling') return `${count} live · REST`;
  return `${count} live · 连接中`;
};

// 实时告警徽标（服务端阈值判定，如 SPREAD_VS_BASELINE_WIDE）
const LiveFlags = ({ state }: { state?: MarketStateTickerState }) => {
  if (!state?.flags.length) return null;
  const evidence = state.flags.map((flag) => `${flag.code}: ${flag.evidence}`).join('\n');
  return (
    <span
      className="ml-1 rounded-full border border-amber-500/40 px-1.5 py-0.5 text-[10px] text-amber-600"
      title={evidence}
    >
      {state.flags.length}
    </span>
  );
};

const Row = ({
  row,
  live,
  name,
}: {
  row: PoolBoardRow;
  live?: MarketStateTickerState;
  name?: string;
}) => {
  // 盘中参与率：实时成交量 ÷ 日度 ADV20（ADV 来自日度快照，见 liveVolumeVsAdvPct）
  const liveVolPct = liveVolumeVsAdvPct(live?.volume, row.adv_20d);
  // 盘前/收市：mktdata 给的是上一交易日镜像，实时列统一置灰（不隐藏，保留可核对）
  const liveMuted = !isLiveTrading(row.market_status);
  const muted = liveMuted ? 'text-muted-foreground' : '';
  return (
    <tr className="border-t border-border/60">
      <td className="px-3 py-2 font-medium text-foreground">
        {row.equ_ticker}
        <LiveFlags state={live} />
      </td>
      <td className="px-3 py-2 text-xs">{renderSecurityName(name)}</td>
      <td className="px-3 py-2">{renderMarketStatusBadge(row.market_status, row.market_time)}</td>
      <td className={`px-3 py-2 text-right font-mono ${muted}`}>{liveNum(live?.last)}</td>
      <td className={`px-3 py-2 text-right font-mono ${liveMuted ? muted : pctToneClass(live?.pct_change_1d)}`}>
        {fmtSignedPercent(live?.pct_change_1d)}
      </td>
      <td className={`px-3 py-2 text-right font-mono ${liveMuted ? muted : 'text-emerald-500'}`}>{liveNum(live?.bid)}</td>
      <td className={`px-3 py-2 text-right font-mono ${liveMuted ? muted : 'text-rose-500'}`}>{liveNum(live?.ask)}</td>
      <td className={`px-3 py-2 text-right font-mono ${muted}`}>{liveNum(live?.spread_bps)}</td>
      <td className={`px-3 py-2 text-right font-mono ${muted}`}>{fmtCompact(live?.volume)}</td>
      <td className={`px-3 py-2 text-right font-mono ${muted}`}>{fmtPercent(liveVolPct, 1)}</td>
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
};

export const PoolBoardPanel = ({
  poolId,
  tradeDate,
  limit = 40,
  live,
  names,
  onUniverseChange,
}: PoolBoardPanelProps) => {
  const key = `${poolId}|${tradeDate ?? ''}|${limit}`;
  const { data, isLoading, error, reload } = useAsyncData(key, () =>
    fetchPoolBoard(poolId, tradeDate ?? undefined, limit),
  );

  useEffect(() => {
    if (!data?.rows.length) return;
    onUniverseChange?.(data.rows.map((row) => row.equ_ticker));
  }, [data, onUniverseChange]);

  const liveCount = live.byTicker.size;

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
          <span
            className={`rounded-full border px-3 py-1 ${live.status === 'live' ? 'border-emerald-500/40 text-emerald-600' : 'border-border'}`}
            title={live.asOf ? `行情时间 ${live.asOf}` : '尚无实时行情'}
          >
            {liveCountLabel(live, liveCount)}
          </span>
          {data?.assumptions.model_calibrated === false ? (
            <span className="rounded-full border border-amber-500/40 px-3 py-1 text-amber-600">
              模型未校准
            </span>
          ) : null}
          <button
            type="button"
            className="rounded-full border border-border px-3 py-1 transition hover:text-foreground"
            onClick={() => reload()}
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
          <table className="w-full min-w-[1800px] text-sm">
            <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-3 text-left font-medium">Ticker</th>
                <th className="px-3 py-3 text-left font-medium">Name</th>
                <th className="px-3 py-3 text-left font-medium">Status</th>
                <th className="px-3 py-3 text-right font-medium">Last</th>
                <th className="px-3 py-3 text-right font-medium">Chg %</th>
                <th className="px-3 py-3 text-right font-medium">Bid</th>
                <th className="px-3 py-3 text-right font-medium">Ask</th>
                <th className="px-3 py-3 text-right font-medium">Sprd bps</th>
                <th className="px-3 py-3 text-right font-medium">Live Vol</th>
                <th className="px-3 py-3 text-right font-medium">Live Vol / ADV20</th>
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
                <Row
                  key={row.equ_ticker}
                  row={row}
                  live={live.byTicker.get(row.equ_ticker)}
                  name={names.get(row.equ_ticker)}
                />
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

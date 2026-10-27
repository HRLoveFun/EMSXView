import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { Activity, Layers, RefreshCw } from 'lucide-react';

import { useAsyncData } from '@shared/hooks/use-async-data';
import { fetchMarketStateSnapshot, fetchPreTradeBoard } from '../services/api';
import type { FreshnessEntry, MarketStateTickerState, PreTradeBoardItem } from '../types';
import { fmtCompact, getIntentLabel, getIntentTone } from '../marketview-utils';

// 实时列刷新间隔：盘中行情由后端订阅提供，此处只做低频拉取（不新增订阅）
const LIVE_REFRESH_MS = 30_000;
// 盘前单刷新间隔：跟随管道盘中作业 J1 的约 5 分钟轮次（意图/订单状态/路由参数）
const BOARD_REFRESH_MS = 5 * 60_000;

const fmtNum = (value: number | null | undefined, digits = 1): string =>
  value == null ? 'n/a' : value.toFixed(digits);

// 新鲜度滞后：-1 表示 as_of 不可解析（显式未知，不显示 0）
const lagText = (entry: FreshnessEntry): string => {
  if (entry.lag_minutes < 0) return 'unknown';
  if (entry.lag_minutes < 60) return `${entry.lag_minutes.toFixed(0)}m`;
  return `${(entry.lag_minutes / 60).toFixed(1)}h`;
};

const lagTone = (entry: FreshnessEntry): string =>
  entry.lag_minutes < 0 || entry.lag_minutes > 30
    ? 'border-amber-500/30 bg-amber-500/10 text-amber-700'
    : 'border-border bg-muted/30 text-muted-foreground';

const Chip = ({ children, tone }: { children: ReactNode; tone?: string }) => (
  <span
    className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 ${
      tone ?? 'border-border text-muted-foreground'
    }`}
  >
    {children}
  </span>
);

// 市场状态徽标（liq × vol；thin/high 为关注态）
const RegimeBadge = ({ item }: { item: PreTradeBoardItem }) => {
  if (!item.liq_regime && !item.vol_regime) {
    return <span className="text-xs text-muted-foreground">n/a</span>;
  }
  const concern = item.liq_regime === 'thin' || item.vol_regime === 'high';
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-1 text-[11px] font-medium ${
        concern ? 'border-amber-500/30 bg-amber-500/10 text-amber-700' : 'border-border bg-muted/30'
      }`}
      title={`market=${item.market_code ?? 'n/a'}`}
    >
      {item.liq_regime ?? '?'} / {item.vol_regime ?? '?'}
    </span>
  );
};

// 预期成本徽标：模型未达标（DL-13 v1 校准）恒定标注，tooltip 说明口径
const CostBadge = ({ item }: { item: PreTradeBoardItem }) => {
  if (item.expected_cost_bps == null) {
    return <span className="text-xs text-muted-foreground">n/a</span>;
  }
  return (
    <span
      className="inline-flex rounded-full border border-border bg-muted/30 px-2 py-1 text-[11px] font-medium"
      title={
        item.model_calibrated
          ? 'model calibrated'
          : 'v1 model not calibrated (systematic underestimation, see calibration report) — internal reference only'
      }
    >
      {item.expected_cost_bps.toFixed(1)} bps
      {item.model_calibrated ? '' : ' *'}
    </span>
  );
};

// 数据缺口徽标：缺失产物可见（不静默填 0）
const GapsBadge = ({ item }: { item: PreTradeBoardItem }) => {
  if (!item.data_gaps.length) {
    return null;
  }
  return (
    <span className="inline-flex rounded-full border border-red-500/30 bg-red-500/10 px-2 py-1 text-[11px] text-red-700">
      gaps: {item.data_gaps.join(', ')}
    </span>
  );
};

// 实时列单元格：快照关闭或该票缺失一律 n/a（不猜）
const LiveCell = ({
  state,
  field,
}: {
  state?: MarketStateTickerState;
  field: 'last' | 'spread' | 'vol_ratio';
}) => {
  if (!state) return <span className="text-xs text-muted-foreground">n/a</span>;
  if (field === 'last') return <span>{fmtNum(state.last, 2)}</span>;
  if (field === 'spread') return <span>{fmtNum(state.spread_bps)}</span>;
  return (
    <span>
      {state.cumulative_volume_ratio == null ? 'n/a' : `${state.cumulative_volume_ratio.toFixed(2)}x`}
    </span>
  );
};

// 057 DL-14/DL-07：盘前单装配面板（四路产物 + 意图覆盖 + 实时列）。
// 列分三组：静态订单要素 / 日度基线 / 实时盘中 / 预期成本估算——分界线清晰。
// 呈现效果按原则 10 与用户反复沟通打磨确定——v2 先交付可讨论版本。
export const PreTradeBoardPanel = () => {
  const { data, error, isLoading, reload } = useAsyncData('pretrade-board', fetchPreTradeBoard);
  const { data: live, reload: reloadLive } = useAsyncData(
    'market-state-snapshot',
    fetchMarketStateSnapshot,
  );

  // 盘中随作业刷新：意图与订单状态跟随 J1 轮次，实时列跟随行情快照
  useEffect(() => {
    const boardTimer = setInterval(() => reload(), BOARD_REFRESH_MS);
    const liveTimer = setInterval(() => reloadLive(), LIVE_REFRESH_MS);
    return () => {
      clearInterval(boardTimer);
      clearInterval(liveTimer);
    };
  }, [reload, reloadLive]);

  const liveByTicker = new Map<string, MarketStateTickerState>(
    (live?.enabled ? live.tickers : []).map((state) => [state.equ_ticker, state]),
  );
  const withCost = data?.items.filter((item) => item.expected_cost_bps != null).length ?? 0;

  return (
    <section className="space-y-4 rounded-2xl border bg-card p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-foreground">Pre-trade board (assembled)</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Order intents (DL-07 intraday store, export fallback) + daily baseline (DL-10) + market
            regime (DL-11) + expected cost (DL-13, v1 not calibrated — marked with *). Live columns
            come from the intraday quote subscription and refresh every 30s; missing products stay
            visible as gaps, never zero-filled.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            reload();
            reloadLive();
          }}
          className="inline-flex items-center gap-1 rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-muted/40"
          title="Refresh board and live snapshot"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          refresh
        </button>
      </div>

      {isLoading ? (
        <div className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
          Loading pre-trade board...
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-6 text-sm text-red-700">
          {error.message}
        </div>
      ) : data && data.items.length > 0 ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Chip>
              <Layers className="h-3.5 w-3.5" />
              schema {data.schema_version}
            </Chip>
            <Chip>{data.items.length} order(s)</Chip>
            <Chip>{withCost} with cost</Chip>
            <Chip
              tone={
                data.intent_coverage_pct >= 100
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700'
                  : 'border-amber-500/30 bg-amber-500/10 text-amber-700'
              }
            >
              intent {data.intent_source} · {data.intent_coverage_pct.toFixed(0)}%
            </Chip>
            <Chip>snapshot {data.snapshot_source}</Chip>
            <Chip>
              <Activity className="h-3.5 w-3.5" />
              {live?.enabled ? `${live.tickers.length} live` : 'live off'}
            </Chip>
          </div>

          {data.freshness.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-[11px]">
              <span className="uppercase tracking-wide text-muted-foreground">freshness</span>
              {data.freshness.map((entry) => (
                <span
                  key={entry.dataset}
                  className={`inline-flex rounded-full border px-2 py-1 ${lagTone(entry)}`}
                  title={`as_of=${entry.as_of || 'n/a'}`}
                >
                  {entry.dataset} · {lagText(entry)}
                </span>
              ))}
            </div>
          )}

          {data.unmatched.length > 0 && (
            <details className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3">
              <summary className="cursor-pointer text-xs font-medium text-amber-800">
                {data.unmatched.length} unmatched intent(s)
              </summary>
              <table className="mt-2 w-full text-xs">
                <thead className="text-left uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="py-1 pr-3 font-medium">Code</th>
                    <th className="py-1 pr-3 font-medium">Order key</th>
                    <th className="py-1 pr-3 font-medium">PM note</th>
                    <th className="py-1 font-medium">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {data.unmatched.map((entry, index) => (
                    <tr key={`${entry.order_key}-${index}`} className="border-t border-amber-500/20">
                      <td className="py-1 pr-3">{entry.equ_ticker || 'n/a'}</td>
                      <td className="py-1 pr-3 font-mono">{entry.order_key || '—'}</td>
                      <td className="py-1 pr-3 font-mono">{entry.pm_note || '—'}</td>
                      <td className="py-1 text-amber-800">{entry.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}

          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full min-w-[1240px] text-sm">
              <thead className="bg-muted/50">
                <tr className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th colSpan={3} className="px-3 pb-1 pt-3 text-left font-semibold">
                    Order (static)
                  </th>
                  <th
                    colSpan={4}
                    className="border-l border-border/60 px-3 pb-1 pt-3 text-left font-semibold"
                  >
                    Daily baseline
                  </th>
                  <th
                    colSpan={3}
                    className="border-l border-border/60 px-3 pb-1 pt-3 text-left font-semibold"
                  >
                    Live intraday
                  </th>
                  <th
                    colSpan={2}
                    className="border-l border-border/60 px-3 pb-1 pt-3 text-left font-semibold"
                  >
                    Estimate
                  </th>
                </tr>
                <tr className="text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 pb-3 text-left font-medium">Code</th>
                  <th className="px-3 pb-3 text-left font-medium">Intent</th>
                  <th className="px-3 pb-3 text-right font-medium">Qty</th>
                  <th className="border-l border-border/60 px-3 pb-3 text-right font-medium">
                    Log vol z
                  </th>
                  <th className="px-3 pb-3 text-right font-medium">Vol pct</th>
                  <th className="px-3 pb-3 text-right font-medium">ADV5/60</th>
                  <th className="px-3 pb-3 text-left font-medium">Regime</th>
                  <th className="border-l border-border/60 px-3 pb-3 text-right font-medium">Last</th>
                  <th className="px-3 pb-3 text-right font-medium">Spread bps</th>
                  <th className="px-3 pb-3 text-right font-medium">Vol vs base</th>
                  <th className="border-l border-border/60 px-3 pb-3 text-left font-medium">Cost</th>
                  <th className="px-3 pb-3 text-left font-medium">Gaps</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => {
                  const state = liveByTicker.get(item.equ_ticker);
                  return (
                    <tr
                      key={`${item.equ_ticker}-${item.order_key}`}
                      className="border-t border-border/60"
                    >
                      <td className="px-3 py-2 font-medium text-foreground">{item.equ_ticker}</td>
                      <td className="px-3 py-2">
                        <span
                          className={`inline-flex rounded-full border px-2 py-1 text-[11px] font-medium ${getIntentTone(item.benchmark)}`}
                          title={item.order_key}
                        >
                          {getIntentLabel(item.benchmark, item.close_pct)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">{fmtCompact(item.qty)}</td>
                      <td className="border-l border-border/40 px-3 py-2 text-right">
                        {item.log_volume_z?.toFixed(2) ?? 'n/a'}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {item.vol_percentile?.toFixed(0) ?? 'n/a'}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {item.adv5_adv60_ratio?.toFixed(2) ?? 'n/a'}
                      </td>
                      <td className="px-3 py-2">
                        <RegimeBadge item={item} />
                      </td>
                      <td className="border-l border-border/40 px-3 py-2 text-right">
                        <LiveCell state={state} field="last" />
                      </td>
                      <td className="px-3 py-2 text-right">
                        <LiveCell state={state} field="spread" />
                      </td>
                      <td className="px-3 py-2 text-right">
                        <LiveCell state={state} field="vol_ratio" />
                      </td>
                      <td className="border-l border-border/40 px-3 py-2">
                        <CostBadge item={item} />
                      </td>
                      <td className="px-3 py-2">
                        <GapsBadge item={item} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground">
            * Expected cost uses the v1 impact model, which is not yet calibrated (systematic
            underestimation; see docs/report-cost-model-calibration.md). Treat as internal
            reference until the model improvement round.
          </p>
        </>
      ) : (
        <div className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
          No pre-trade board available. Configure <code>EMSXVIEW_EXPORT_INBOX_DIR</code> on the
          MarketView service to populate this panel.
        </div>
      )}
    </section>
  );
};

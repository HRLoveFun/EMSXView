import { Layers } from 'lucide-react';

import { useAsyncData } from '@shared/hooks/use-async-data';
import { fetchPreTradeBoard } from '../services/api';
import type { PreTradeBoardItem } from '../types';
import { fmtCompact, getIntentLabel, getIntentTone } from '../marketview-utils';

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

// 057 DL-14：盘前单装配面板（1a–1c 四路产物按单汇总）。
// 呈现效果按原则 10 与用户反复沟通打磨确定——v1 先交付可讨论版本。
export const PreTradeBoardPanel = () => {
  const { data, error, isLoading } = useAsyncData('pretrade-board', fetchPreTradeBoard);

  return (
    <section className="space-y-4 rounded-2xl border bg-card p-6 shadow-sm">
      <div>
        <p className="text-sm font-medium text-foreground">Pre-trade board (assembled)</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Order intents (DL-01) + daily baseline (DL-10) + market regime (DL-11) + expected cost
          (DL-13, v1 not calibrated — marked with *). Missing products are shown as gaps, never
          zero-filled.
        </p>
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
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <div className="inline-flex items-center gap-1 rounded-full border border-border px-3 py-1">
              <Layers className="h-3.5 w-3.5" />
              schema {data.schema_version}
            </div>
            <div className="rounded-full border border-border px-3 py-1">{data.items.length} order(s)</div>
            <div className="rounded-full border border-border px-3 py-1">
              {data.items.filter((i) => i.expected_cost_bps != null).length} with cost
            </div>
          </div>
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full min-w-[1080px] text-sm">
              <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-3 text-left font-medium">Code</th>
                  <th className="px-3 py-3 text-left font-medium">Intent</th>
                  <th className="px-3 py-3 text-right font-medium">Qty</th>
                  <th className="px-3 py-3 text-right font-medium">Log vol z</th>
                  <th className="px-3 py-3 text-right font-medium">Vol pct</th>
                  <th className="px-3 py-3 text-right font-medium">ADV5/60</th>
                  <th className="px-3 py-3 text-left font-medium">Regime</th>
                  <th className="px-3 py-3 text-left font-medium">Cost</th>
                  <th className="px-3 py-3 text-left font-medium">Gaps</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={`${item.equ_ticker}-${item.order_key}`} className="border-t border-border/60">
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
                    <td className="px-3 py-2 text-right">{item.log_volume_z?.toFixed(2) ?? 'n/a'}</td>
                    <td className="px-3 py-2 text-right">{item.vol_percentile?.toFixed(0) ?? 'n/a'}</td>
                    <td className="px-3 py-2 text-right">{item.adv5_adv60_ratio?.toFixed(2) ?? 'n/a'}</td>
                    <td className="px-3 py-2">
                      <RegimeBadge item={item} />
                    </td>
                    <td className="px-3 py-2">
                      <CostBadge item={item} />
                    </td>
                    <td className="px-3 py-2">
                      <GapsBadge item={item} />
                    </td>
                  </tr>
                ))}
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

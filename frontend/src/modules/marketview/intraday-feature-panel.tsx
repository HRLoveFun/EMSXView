import type {
  IntradayBucketMinutes,
  IntradayFeatureSnapshot,
  IntradayTickerFeatures,
} from './types';
import { fmtNumber, fmtCompact, fmtPercent } from './marketview-utils';

const INTRADAY_BUCKET_CHOICES: readonly IntradayBucketMinutes[] = [5, 10, 15, 30, 60];

interface IntradayFeaturePanelProps {
  ticker: string;
  bucketMinutes: IntradayBucketMinutes;
  onBucketMinutesChange: (value: IntradayBucketMinutes) => void;
  snapshot: IntradayFeatureSnapshot | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

export function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border/70 bg-background px-4 py-3">
      <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold text-foreground">{value}</div>
    </div>
  );
}

export function IntradayFeaturePanel({
  ticker, bucketMinutes, onBucketMinutesChange, snapshot, loading, error, onClose,
}: IntradayFeaturePanelProps) {
  const tickerFeatures: IntradayTickerFeatures | undefined = snapshot?.tickers.find(
    (entry) => entry.equ_ticker === ticker,
  );
  const isMissing = snapshot?.missing_tickers.includes(ticker);

  return (
    <div className="rounded-2xl border border-border/70 bg-background/70 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Intraday feature drill-down</div>
          <h3 className="mt-1 text-lg font-semibold text-foreground">{ticker}</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Exchange-local time-window features from raw BDIB; not a real-time data stream, for pre-market review only.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">
            Bucket (min)
            <select
              className="ml-2 rounded-xl border border-border bg-background px-2 py-1 text-sm text-foreground"
              value={bucketMinutes}
              onChange={(event) => onBucketMinutesChange(Number(event.target.value) as IntradayBucketMinutes)}
            >
              {INTRADAY_BUCKET_CHOICES.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition hover:text-foreground"
          >
            Close
          </button>
        </div>
      </div>

      {loading ? (
        <div className="mt-4 rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">Loading intraday features...</div>
      ) : error ? (
        <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/5 p-5 text-sm text-red-700">{error}</div>
      ) : isMissing || !tickerFeatures ? (
        <div className="mt-4 rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">
          No intraday bars available for {ticker} on {snapshot?.trade_date ?? 'the selected date'}.
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-4">
            <SummaryCard label="Bars" value={String(tickerFeatures.bar_count)} />
            <SummaryCard label="Session" value={`${tickerFeatures.first_bar_time ?? '—'} → ${tickerFeatures.last_bar_time ?? '—'}`} />
            <SummaryCard label="Day VWAP" value={fmtNumber(tickerFeatures.daily_vwap, 2)} />
            <SummaryCard label="Day Close" value={fmtNumber(tickerFeatures.daily_close, 2)} />
            <SummaryCard label="Total Volume" value={fmtCompact(tickerFeatures.total_volume)} />
            <SummaryCard label="ADV 20D" value={fmtCompact(tickerFeatures.adv_20d)} />
            <SummaryCard label="Vol / ADV20" value={fmtPercent(tickerFeatures.volume_vs_adv20_pct, 1)} />
            <SummaryCard label="Intraday Vol" value={fmtPercent(tickerFeatures.intraday_volatility, 1)} />
            <SummaryCard label="Open 10m share" value={`${fmtCompact(tickerFeatures.open_window_volume)} · ${fmtPercent(tickerFeatures.open_window_share_pct, 1)}`} />
            <SummaryCard label="Open 10m VWAP" value={fmtNumber(tickerFeatures.open_window_vwap, 2)} />
            <SummaryCard label="Close 10m share" value={`${fmtCompact(tickerFeatures.close_window_volume)} · ${fmtPercent(tickerFeatures.close_window_share_pct, 1)}`} />
            <SummaryCard label="Close 10m VWAP" value={fmtNumber(tickerFeatures.close_window_vwap, 2)} />
          </div>

          <div className="overflow-hidden rounded-xl border border-border">
            <div className="border-b border-border/70 bg-muted/20 px-4 py-3 text-sm text-muted-foreground">
              Volume curve · {bucketMinutes}-minute buckets ({tickerFeatures.buckets.length} rows)
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[960px] text-sm">
                <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Window</th>
                    <th className="px-3 py-2 text-right font-medium">Bars</th>
                    <th className="px-3 py-2 text-right font-medium">Volume</th>
                    <th className="px-3 py-2 text-right font-medium">Cum %</th>
                    <th className="px-3 py-2 text-right font-medium">Vol/ADV20</th>
                    <th className="px-3 py-2 text-right font-medium">VWAP</th>
                    <th className="px-3 py-2 text-right font-medium">Close</th>
                    <th className="px-3 py-2 text-right font-medium">Realized Vol</th>
                  </tr>
                </thead>
                <tbody>
                  {tickerFeatures.buckets.map((bucket) => (
                    <tr key={`${bucket.bucket_start}-${bucket.bucket_end}`} className="border-t border-border/60">
                      <td className="px-3 py-2 font-medium text-foreground">{bucket.bucket_start} – {bucket.bucket_end}</td>
                      <td className="px-3 py-2 text-right">{bucket.bar_count}</td>
                      <td className="px-3 py-2 text-right">{fmtCompact(bucket.volume)}</td>
                      <td className="px-3 py-2 text-right">{fmtPercent(bucket.cumulative_volume_pct, 1)}</td>
                      <td className="px-3 py-2 text-right">{fmtPercent(bucket.volume_vs_adv20_pct, 1)}</td>
                      <td className="px-3 py-2 text-right">{fmtNumber(bucket.vwap, 2)}</td>
                      <td className="px-3 py-2 text-right">{fmtNumber(bucket.close, 2)}</td>
                      <td className="px-3 py-2 text-right">{fmtPercent(bucket.realized_vol_annualized, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

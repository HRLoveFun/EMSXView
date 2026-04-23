import { useEffect, useState } from 'react';
import { Activity, BarChart3, Gauge } from 'lucide-react';
import { fetchMarketSnapshot } from './services/api';
import type { MarketSnapshotPayload } from './types';

const capabilityCards = [
  {
    title: 'Market Snapshot',
    description: '读取 Stage 7 生成的日级市场快照，优先给盘前模块提供收盘价、ADV 和波动率边界。',
    icon: Activity,
  },
  {
    title: 'Liquidity Checks',
    description: '下一步把候选交易标的与 ADV/日成交量边界连接起来，形成盘前流动性快速筛查。',
    icon: Gauge,
  },
  {
    title: 'Execution Hand-Off',
    description: '后续在这里把盘前筛查结果通过共享契约传给 Execution，而不是页面间硬编码传值。',
    icon: BarChart3,
  },
];

function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value == null) return '—';
  return value.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function fmtCompact(value: number | null | undefined): string {
  if (value == null) return '—';
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}

export default function MarketViewModule() {
  const [snapshot, setSnapshot] = useState<MarketSnapshotPayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadSnapshot() {
      setIsLoading(true);
      setError(null);
      try {
        const nextSnapshot = await fetchMarketSnapshot(12);
        if (!cancelled) {
          setSnapshot(nextSnapshot);
        }
      } catch (nextError) {
        if (!cancelled) {
          setError(nextError instanceof Error ? nextError.message : 'Failed to load market snapshot');
          setSnapshot(null);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadSnapshot();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="space-y-6 rounded-2xl border bg-card p-6 shadow-sm">
      <div className="space-y-3">
        <div className="inline-flex items-center rounded-full border border-border bg-background px-3 py-1 text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
          MarketView
        </div>
        <div className="space-y-2">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">Pre-trade workspace</h2>
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
            这里已经接上第一批真实数据边界：来自统一逻辑数据域中的市场参考数据快照。当前模块先提供盘前收盘价、波动率和 ADV 视图，后续再叠加候选订单和风险检查。
          </p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {capabilityCards.map((card) => (
          <article key={card.title} className="rounded-2xl border border-border/70 bg-background/80 p-5">
            <card.icon className="h-5 w-5 text-primary" />
            <h3 className="mt-4 text-base font-semibold text-foreground">{card.title}</h3>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">{card.description}</p>
          </article>
        ))}
      </div>

      <div className="rounded-2xl border border-border/70 bg-background/70 p-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-foreground">Latest market snapshot</p>
            <p className="mt-1 text-sm text-muted-foreground">
              数据源是 `bdib_daily_summary` 的最新交易日快照，通过 `platform_data` 适配层暴露给 MarketView。
            </p>
          </div>
          <div className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground">
            {snapshot?.trade_date ? `Trade Date ${snapshot.trade_date}` : 'No snapshot date'}
          </div>
        </div>

        {isLoading ? (
          <div className="mt-4 rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
            Loading market snapshot...
          </div>
        ) : error ? (
          <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/5 p-6 text-sm text-red-700">
            {error}
          </div>
        ) : snapshot && snapshot.rows.length ? (
          <div className="mt-4 overflow-hidden rounded-xl border border-border">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-sm">
                <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-3 py-3 text-left font-medium">Ticker</th>
                    <th className="px-3 py-3 text-right font-medium">Close</th>
                    <th className="px-3 py-3 text-right font-medium">Daily Vol</th>
                    <th className="px-3 py-3 text-right font-medium">Intraday Vol</th>
                    <th className="px-3 py-3 text-right font-medium">Total Vol</th>
                    <th className="px-3 py-3 text-right font-medium">ADV 5D</th>
                    <th className="px-3 py-3 text-right font-medium">ADV 20D</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.rows.map((row) => (
                    <tr key={`${row.equ_ticker}-${row.trade_date}`} className="border-t border-border/60">
                      <td className="px-3 py-3 font-medium text-foreground">{row.equ_ticker}</td>
                      <td className="px-3 py-3 text-right">{fmtNumber(row.daily_close, 2)}</td>
                      <td className="px-3 py-3 text-right">{fmtNumber(row.daily_volatility, 2)}%</td>
                      <td className="px-3 py-3 text-right">{fmtNumber(row.intraday_volatility, 2)}%</td>
                      <td className="px-3 py-3 text-right">{fmtCompact(row.total_volume)}</td>
                      <td className="px-3 py-3 text-right">{fmtCompact(row.adv_5d)}</td>
                      <td className="px-3 py-3 text-right">{fmtCompact(row.adv_20d)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
            No market snapshot data available yet. Run the CostView pipeline through Stage 7 to populate `bdib_daily_summary`.
          </div>
        )}
      </div>
    </section>
  );
}
/**
 * Legacy prototype page.
 *
 * TCAPage — main TCA analysis page.
 *
 * Layout:
 *   FilterPanel → OrderTable (paginated) → Chart panel (shown when order selected)
 *
 * Data flow:
 *   FilterPanel.onSearch → analyzeTca() → TcaReport → TcaOrderTable
 *   TcaOrderTable.onSelectOrder → selected order → PriceDynamicChart + VolumeDynamicChart
 */

import { useState, useCallback } from 'react';
import { TcaFilterPanel } from '@/components/tca/TcaFilterPanel';
import { TcaOrderTable } from '@/components/tca/TcaOrderTable';
import { PriceDynamicChart } from '@/components/tca/PriceDynamicChart';
import { VolumeDynamicChart } from '@/components/tca/VolumeDynamicChart';
import { analyzeTca } from '@/services/tca-api';
import type { TcaFilterPayload, TcaReport, TcaOrderSummary } from '@/services/tca-api';

export function TCAPage() {
  const [report, setReport] = useState<TcaReport | null>(null);
  const [selectedOrder, setSelectedOrder] = useState<TcaOrderSummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Holds the last filter + limit used, so pagination can re-use them
  const [lastFilters, setLastFilters] = useState<TcaFilterPayload>({});
  const [lastLimit, setLastLimit] = useState(50);

  const fetchReport = useCallback(
    async (filters: TcaFilterPayload, limit: number, offset: number) => {
      setIsLoading(true);
      setError(null);
      try {
        const r = await analyzeTca({ filters, limit, offset });
        setReport(r);
        setSelectedOrder(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setReport(null);
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  function handleSearch(filters: TcaFilterPayload, limit: number) {
    setLastFilters(filters);
    setLastLimit(limit);
    fetchReport(filters, limit, 0);
  }

  function handlePageChange(offset: number) {
    fetchReport(lastFilters, lastLimit, offset);
  }

  return (
    <div className="space-y-4">
      <TcaFilterPanel onSearch={handleSearch} isLoading={isLoading} />

      {error && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-lg px-4 py-3 text-sm text-destructive">
          <strong>Error:</strong> {error}
          {error.toLowerCase().includes('fill_bdib') && (
            <span className="block mt-1 text-xs text-muted-foreground">
              The BDIB integration pipeline has not run yet. Run the data pipeline first
              (Settings → Trigger Update, or run daily_update.py).
            </span>
          )}
        </div>
      )}

      {report && (
        <div className="space-y-4">
          {/* Summary bar */}
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {report.total_orders} order{report.total_orders !== 1 ? 's' : ''} matched
              {report.filters.start_date &&
                ` · ${report.filters.start_date}–${report.filters.end_date}`}
              {report.filters.algo && ` · ${report.filters.algo}`}
            </span>
            <span>Generated {new Date(report.generated_at).toLocaleTimeString()}</span>
          </div>

          <TcaOrderTable
            report={report}
            onPageChange={handlePageChange}
            onSelectOrder={setSelectedOrder}
            selectedOrderId={selectedOrder?.order_id ?? null}
          />

          {/* Chart panel — shown only when an order is selected */}
          {selectedOrder && (
            <div className="bg-card border border-border rounded-lg p-4 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">
                  {selectedOrder.equ_ticker ?? selectedOrder.order_id} —{' '}
                  {selectedOrder.algo ?? 'N/A'} · {selectedOrder.order_as_of_date}
                </h3>
                <button
                  onClick={() => setSelectedOrder(null)}
                  className="text-muted-foreground hover:text-foreground text-lg leading-none"
                  aria-label="Close chart"
                >
                  ×
                </button>
              </div>

              {/* Key metrics row */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <MetricCard
                  label="Fill %"
                  value={selectedOrder.fill_pct != null ? `${selectedOrder.fill_pct.toFixed(1)}%` : '—'}
                />
                <MetricCard
                  label="Tracking Error"
                  value={
                    selectedOrder.tracking_error_bps != null
                      ? `${selectedOrder.tracking_error_bps > 0 ? '+' : ''}${selectedOrder.tracking_error_bps.toFixed(1)} bps`
                      : '—'
                  }
                  highlight={
                    selectedOrder.tracking_error_bps != null
                      ? selectedOrder.tracking_error_bps < -10
                        ? 'positive'
                        : selectedOrder.tracking_error_bps > 10
                        ? 'negative'
                        : 'neutral'
                      : 'neutral'
                  }
                />
                <MetricCard
                  label="Vol % ADV20"
                  value={
                    selectedOrder.volume_pct_adv20 != null
                      ? `${selectedOrder.volume_pct_adv20.toFixed(2)}%`
                      : '—'
                  }
                />
                <MetricCard
                  label="Intraday Volatility"
                  value={
                    selectedOrder.intraday_volatility != null
                      ? `${selectedOrder.intraday_volatility.toFixed(2)}%`
                      : '—'
                  }
                />
              </div>

              <PriceDynamicChart
                routes={selectedOrder.routes}
                orderId={selectedOrder.order_id}
              />
              <VolumeDynamicChart
                routes={selectedOrder.routes}
                orderId={selectedOrder.order_id}
              />
            </div>
          )}
        </div>
      )}

      {!report && !isLoading && !error && (
        <div className="text-center text-muted-foreground text-sm py-12">
          Apply filters above and click <strong>Analyze</strong> to view TCA results.
          <br />
          <span className="text-xs mt-1 block">
            By default, the last trading day is shown when no date is specified.
          </span>
        </div>
      )}
    </div>
  );
}

// ── Helper component ──────────────────────────────────────────────────────────

interface MetricCardProps {
  label: string;
  value: string;
  highlight?: 'positive' | 'negative' | 'neutral';
}

function MetricCard({ label, value, highlight = 'neutral' }: MetricCardProps) {
  const valueColor =
    highlight === 'positive'
      ? 'text-green-500'
      : highlight === 'negative'
      ? 'text-red-500'
      : 'text-foreground';

  return (
    <div className="bg-muted/40 rounded-lg px-3 py-2">
      <div className="text-xs text-muted-foreground mb-0.5">{label}</div>
      <div className={`text-sm font-semibold tabular-nums ${valueColor}`}>{value}</div>
    </div>
  );
}

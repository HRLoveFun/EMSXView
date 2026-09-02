import { useEffect, useState } from 'react';

import { ModuleIntro } from './components/module-intro';
import { SummaryCards } from './components/summary-cards';
import { FilterBar } from './components/filter-bar';
import { SnapshotTable } from './components/snapshot-table';
import { HandoffPanel } from './components/handoff-panel';
import { buildMarketCandidatePayload, countRowsWithSeverity } from './lib/workspace';
import { fetchIntradayFeatures, fetchMarketSnapshot } from './services/api';
import { useHandoffContracts } from '@shared/hooks/use-handoff-contracts';
import { IntradayFeaturePanel } from './intraday-feature-panel';
import type {
  IntradayBucketMinutes,
  IntradayFeatureSnapshot,
  MarketSnapshotPayload,
  MarketSnapshotRequest,
} from './types';

const DEFAULT_QUERY: MarketSnapshotRequest = {
  limit: 40,
  pool_id: 'all',
  liquidity_alert: 'all',
  volatility_alert: 'all',
  sort_by: 'total_volume',
  sort_direction: 'desc',
};

// 日内钻取面板：根据 ticker 与交易日加载日内特征
const useIntradayDrill = (
  drillTicker: string | null,
  tradeDate: string | null | undefined,
  bucketMinutes: IntradayBucketMinutes,
) => {
  const [drillSnapshot, setDrillSnapshot] = useState<IntradayFeatureSnapshot | null>(null);
  const [drillLoading, setDrillLoading] = useState(false);
  const [drillError, setDrillError] = useState<string | null>(null);

  useEffect(() => {
    if (!drillTicker || !tradeDate) {
      return;
    }

    let cancelled = false;
    const loadFeatures = async (): Promise<void> => {
      setDrillLoading(true);
      setDrillError(null);
      try {
        const result = await fetchIntradayFeatures({
          tickers: [drillTicker],
          trade_date: tradeDate,
          bucket_minutes: bucketMinutes,
        });
        if (!cancelled) setDrillSnapshot(result);
      } catch (err) {
        if (!cancelled) {
          setDrillError(err instanceof Error ? err.message : 'Failed to load intraday features');
          setDrillSnapshot(null);
        }
      } finally {
        if (!cancelled) setDrillLoading(false);
      }
    };

    void loadFeatures();
    return () => {
      cancelled = true;
    };
  }, [drillTicker, bucketMinutes, tradeDate]);

  return { drillSnapshot, drillLoading, drillError };
};

// MarketView 盘前工作台：状态编排层，展示逻辑委托给 components/ 子组件
export default function MarketViewModule() {
  const [query, setQuery] = useState<MarketSnapshotRequest>(DEFAULT_QUERY);
  const [snapshot, setSnapshot] = useState<MarketSnapshotPayload | null>(null);
  const [selectedTickers, setSelectedTickers] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drillTicker, setDrillTicker] = useState<string | null>(null);
  const [drillBucketMinutes, setDrillBucketMinutes] = useState<IntradayBucketMinutes>(30);
  const { publishMarketCandidatesAction, activeCandidateHandoff } = useHandoffContracts();
  const [publishStatus, setPublishStatus] = useState<string | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);

  // 加载每日快照（query 变化即重新拉取）
  useEffect(() => {
    let cancelled = false;

    const loadSnapshot = async (): Promise<void> => {
      setIsLoading(true);
      setError(null);
      try {
        const nextSnapshot = await fetchMarketSnapshot(query);
        if (!cancelled) setSnapshot(nextSnapshot);
      } catch (nextError) {
        if (!cancelled) {
          setError(nextError instanceof Error ? nextError.message : 'Failed to load MarketView workstation');
          setSnapshot(null);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    void loadSnapshot();
    return () => {
      cancelled = true;
    };
  }, [query]);

  // 快照刷新后修剪已不存在的选中项
  useEffect(() => {
    if (!snapshot) {
      setSelectedTickers([]);
      return;
    }

    setSelectedTickers((current) =>
      current.filter((ticker) => snapshot.rows.some((row) => row.equ_ticker === ticker)),
    );
  }, [snapshot]);

  const { drillSnapshot, drillLoading, drillError } = useIntradayDrill(
    drillTicker,
    snapshot?.trade_date,
    drillBucketMinutes,
  );

  const updateQuery = <K extends keyof MarketSnapshotRequest>(key: K, value: MarketSnapshotRequest[K]): void => {
    setQuery((current) => ({ ...current, [key]: value }));
  };

  // 切换股票池时应用该池的默认排序
  const handlePoolChange = (poolId: string): void => {
    const nextPool = snapshot?.available_pools.find((pool) => pool.pool_id === poolId);
    setQuery((current) => ({
      ...current,
      pool_id: poolId,
      sort_by: nextPool?.default_sort_by ?? current.sort_by ?? 'total_volume',
      sort_direction: nextPool?.default_sort_direction ?? current.sort_direction ?? 'desc',
    }));
  };

  const toggleTicker = (ticker: string): void => {
    setSelectedTickers((current) =>
      current.includes(ticker)
        ? current.filter((item) => item !== ticker)
        : [...current, ticker],
    );
  };

  // 将当前候选负载发布到 ExecutionView
  const handlePublish = async (): Promise<void> => {
    if (!handoffPayload) return;
    setIsPublishing(true);
    setPublishStatus(null);
    try {
      const result = await publishMarketCandidatesAction({
        pool_id: handoffPayload.pool_id,
        tickers: selectedTickers.length ? selectedTickers : undefined,
      });
      setPublishStatus(
        `Delivered to ExecutionView: ${result.candidate_payload.row_count} symbols (trace_id=${result.metadata.trace_id.slice(0, 12)}…)`,
      );
    } catch (err) {
      setPublishStatus(err instanceof Error ? `Send failed: ${err.message}` : 'Send failed');
    } finally {
      setIsPublishing(false);
    }
  };

  const rows = snapshot?.rows ?? [];
  const criticalCount = countRowsWithSeverity(rows, 'critical');
  const warningCount = countRowsWithSeverity(rows, 'warning');
  const handoffPayload = snapshot ? buildMarketCandidatePayload(snapshot, selectedTickers) : null;
  const activePool = snapshot?.available_pools.find((pool) => pool.pool_id === snapshot.active_pool_id) ?? null;

  return (
    <section className="space-y-6 rounded-2xl border bg-card p-6 shadow-sm">
      <ModuleIntro />

      <SummaryCards
        rowCount={snapshot?.row_count ?? 0}
        criticalCount={criticalCount}
        warningCount={warningCount}
        handoffRowCount={handoffPayload?.row_count ?? 0}
        hasExplicitSelection={selectedTickers.length > 0}
        isPublishing={isPublishing}
        canPublish={Boolean(handoffPayload) && (handoffPayload?.row_count ?? 0) > 0}
        publishStatus={publishStatus}
        lastHandoff={
          activeCandidateHandoff
            ? {
                rowCount: activeCandidateHandoff.candidate_payload.row_count,
                generatedAt: activeCandidateHandoff.metadata.generated_at,
              }
            : null
        }
        onPublish={() => void handlePublish()}
      />

      <div className="rounded-2xl border border-border/70 bg-background/70 p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-sm font-medium text-foreground">Stock-pool workstation</p>
            <p className="mt-1 text-sm text-muted-foreground">
              The data source is still the latest trading day snapshot from `bdib_daily_summary`, exposed to MarketView through the `platform_data` adapter layer. All filtering and alerts here are based on daily data and do not represent real-time market conditions.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <div className="rounded-full border border-border px-3 py-1">
              {snapshot?.trade_date ? `Trade Date ${snapshot.trade_date}` : 'No snapshot date'}
            </div>
            <div className="rounded-full border border-border px-3 py-1">{activePool?.label ?? 'Stock pool'}</div>
            <div className="rounded-full border border-border px-3 py-1">{rows.length} rows</div>
          </div>
        </div>

        <FilterBar
          query={query}
          pools={snapshot?.available_pools ?? []}
          activePoolDescription={activePool?.description ?? null}
          onPoolChange={handlePoolChange}
          onQueryChange={updateQuery}
          onReset={() => setQuery(DEFAULT_QUERY)}
        />

        {isLoading ? (
          <div className="mt-4 rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
            Loading MarketView workstation...
          </div>
        ) : error ? (
          <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/5 p-6 text-sm text-red-700">
            {error}
          </div>
        ) : snapshot && snapshot.rows.length ? (
          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.95fr)]">
            <SnapshotTable
              rows={rows}
              selectedTickers={selectedTickers}
              drillTicker={drillTicker}
              onToggleTicker={toggleTicker}
              onSelectAll={() => setSelectedTickers(rows.map((row) => row.equ_ticker))}
              onClearSelection={() => setSelectedTickers([])}
              onDrillToggle={(ticker) =>
                setDrillTicker((current) => (current === ticker ? null : ticker))
              }
            />
            <HandoffPanel payload={handoffPayload} />
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
            No market snapshot data available yet. Run the CostView pipeline through Stage 7 to populate `bdib_daily_summary`.
          </div>
        )}
      </div>

      {drillTicker ? (
        <IntradayFeaturePanel
          ticker={drillTicker}
          bucketMinutes={drillBucketMinutes}
          onBucketMinutesChange={setDrillBucketMinutes}
          snapshot={drillSnapshot}
          loading={drillLoading}
          error={drillError}
          onClose={() => setDrillTicker(null)}
        />
      ) : null}
    </section>
  );
}

/**
 * Shared React context for WBS-08 cross-module handoff contracts.
 *
 * Wraps the three contract API calls and exposes:
 *   - activeCandidateHandoff    MarketView → ExecutionView (single latest slot)
 *   - recommendations           CostView  → ExecutionView (latest pinned list)
 *   - publishMarketCandidates   MarketView produces candidate payload
 *   - publishPostTrade          ExecutionView sends post-trade context to CostView
 *   - pinRecommendation         CostView pins a cohort conclusion
 *   - refreshCandidate, refreshRecommendations
 *
 * The provider lightly polls (30s) both read endpoints so every module sees
 * the same shared state without bespoke coordination.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  fetchActiveCandidateHandoff,
  fetchBrokerRecommendations,
  pinBrokerRecommendation,
  publishMarketCandidates,
  publishPostTradeHandoff,
  type BrokerRecommendation,
  type MarketToExecutionHandoff,
  type PinRecommendationRequest,
  type PublishMarketCandidatesRequest,
  type PublishPostTradeRequest,
} from '@shared/services/handoff-api';

const POLL_INTERVAL_MS = 30_000;

interface HandoffContextValue {
  activeCandidateHandoff: MarketToExecutionHandoff | null;
  recommendations: BrokerRecommendation[];
  isLoading: boolean;
  lastError: string | null;
  refreshCandidate: () => Promise<void>;
  refreshRecommendations: () => Promise<void>;
  publishMarketCandidatesAction: (
    req: PublishMarketCandidatesRequest,
  ) => Promise<MarketToExecutionHandoff>;
  publishPostTradeAction: (req: PublishPostTradeRequest) => Promise<void>;
  pinRecommendationAction: (req: PinRecommendationRequest) => Promise<void>;
}

const HandoffContext = createContext<HandoffContextValue | null>(null);

export function HandoffContractsProvider({ children }: { children: ReactNode }) {
  const [activeCandidateHandoff, setActive] = useState<MarketToExecutionHandoff | null>(null);
  const [recommendations, setRecommendations] = useState<BrokerRecommendation[]>([]);
  // 初始加载态为 true，首次 effect 加载完成后置 false，避免 effect 内同步 setIsLoading(true)
  const [isLoading, setIsLoading] = useState(true);
  const [lastError, setLastError] = useState<string | null>(null);

  const refreshCandidate = useCallback(async () => {
    try {
      const next = await fetchActiveCandidateHandoff();
      setActive(next);
    } catch (err) {
      setLastError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const refreshRecommendations = useCallback(async () => {
    try {
      const list = await fetchBrokerRecommendations({ limit: 25 });
      setRecommendations(list);
    } catch (err) {
      setLastError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    // 在微任务中触发加载，避免 effect 同步路径调用含 setState 的函数
    queueMicrotask(() => {
      void Promise.all([refreshCandidate(), refreshRecommendations()]).finally(() => setIsLoading(false));
    });
    const id = window.setInterval(() => {
      refreshCandidate();
      refreshRecommendations();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [refreshCandidate, refreshRecommendations]);

  const publishMarketCandidatesAction = useCallback(
    async (req: PublishMarketCandidatesRequest) => {
      const result = await publishMarketCandidates(req);
      setActive(result);
      return result;
    },
    [],
  );

  const publishPostTradeAction = useCallback(async (req: PublishPostTradeRequest) => {
    await publishPostTradeHandoff(req);
  }, []);

  const pinRecommendationAction = useCallback(
    async (req: PinRecommendationRequest) => {
      await pinBrokerRecommendation(req);
      await refreshRecommendations();
    },
    [refreshRecommendations],
  );

  const value = useMemo<HandoffContextValue>(
    () => ({
      activeCandidateHandoff,
      recommendations,
      isLoading,
      lastError,
      refreshCandidate,
      refreshRecommendations,
      publishMarketCandidatesAction,
      publishPostTradeAction,
      pinRecommendationAction,
    }),
    [
      activeCandidateHandoff,
      recommendations,
      isLoading,
      lastError,
      refreshCandidate,
      refreshRecommendations,
      publishMarketCandidatesAction,
      publishPostTradeAction,
      pinRecommendationAction,
    ],
  );

  return <HandoffContext.Provider value={value}>{children}</HandoffContext.Provider>;
}

// 与 Provider 组件同文件导出 hook 会牺牲 fast refresh，属可接受取舍
// eslint-disable-next-line react-refresh/only-export-components
export function useHandoffContracts(): HandoffContextValue {
  const ctx = useContext(HandoffContext);
  if (!ctx) {
    throw new Error('useHandoffContracts must be used within HandoffContractsProvider');
  }
  return ctx;
}
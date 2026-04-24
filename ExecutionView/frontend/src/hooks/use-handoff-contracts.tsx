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
} from '../services/handoff-api';

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
  const [isLoading, setIsLoading] = useState(false);
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
    setIsLoading(true);
    Promise.all([refreshCandidate(), refreshRecommendations()]).finally(() => setIsLoading(false));
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

export function useHandoffContracts(): HandoffContextValue {
  const ctx = useContext(HandoffContext);
  if (!ctx) {
    throw new Error('useHandoffContracts must be used within HandoffContractsProvider');
  }
  return ctx;
}

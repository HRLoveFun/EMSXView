/**
 * Route Plan and RouteEngine types.
 *
 * P3-SRP: Extracted from types/index.ts.
 */

export type ActivationMode = 'AUTO' | 'MANUAL';
export type SubmissionMode = 'MANUAL_CONFIRM' | 'AUTO_SUBMIT';
export type SplitType = 'BROKER_SPLIT' | 'TIME_SCHEDULE' | 'HYBRID';
export type AllocationType = 'PERCENTAGE' | 'FIXED';
export type ProposalStatus = 'PENDING_CONFIRM' | 'CONFIRMED' | 'SUBMITTED' | 'REJECTED' | 'CANCELLED';
export type MatchSide = 'BUY' | 'SELL' | 'BOTH';

export interface RoutePlanAllocation {
  broker: string;
  allocationType: AllocationType;
  allocationValue: number;
  orderType?: string | null;
  limitPriceOffset?: number | null;
  strategyParams?: Record<string, unknown> | null;
  sortOrder: number;
}

export interface RoutePlan {
  id: number;
  name: string;
  description?: string | null;
  matchMarket: string;
  matchSymbol?: string | null;
  matchSide: MatchSide;
  matchPortfolio?: string | null;
  matchTrader?: string | null;
  matchExchange?: string | null;
  matchCurrency?: string | null;
  activationMode: ActivationMode;
  submissionMode: SubmissionMode;
  splitType: SplitType;
  scheduleType?: string | null;
  numSlices?: number | null;
  defaultStartOffsetMin?: number | null;
  defaultEndTimeLocal?: string | null;
  participationRate?: number | null;
  defaultBroker?: string | null;
  defaultOrderType?: string | null;
  defaultTif?: string | null;
  defaultStrategyParams?: Record<string, unknown> | null;
  enabled: boolean;
  priority: number;
  allocations: RoutePlanAllocation[];
  createdAt: string;
  updatedAt: string;
}

export interface CreateRoutePlanRequest {
  name: string;
  description?: string | null;
  matchMarket: string;
  matchSymbol?: string | null;
  matchSide?: MatchSide;
  matchPortfolio?: string | null;
  matchTrader?: string | null;
  matchExchange?: string | null;
  matchCurrency?: string | null;
  activationMode?: ActivationMode;
  submissionMode?: SubmissionMode;
  splitType?: SplitType;
  scheduleType?: string | null;
  numSlices?: number | null;
  defaultStartOffsetMin?: number | null;
  defaultEndTimeLocal?: string | null;
  participationRate?: number | null;
  defaultBroker?: string | null;
  defaultOrderType?: string | null;
  defaultTif?: string | null;
  defaultStrategyParams?: Record<string, unknown> | null;
  enabled?: boolean;
  priority?: number;
  allocations?: RoutePlanAllocation[];
}

export interface UpdateRoutePlanRequest {
  name?: string;
  description?: string | null;
  matchMarket?: string;
  matchSymbol?: string | null;
  matchSide?: MatchSide;
  matchPortfolio?: string | null;
  matchTrader?: string | null;
  matchExchange?: string | null;
  matchCurrency?: string | null;
  activationMode?: ActivationMode;
  submissionMode?: SubmissionMode;
  splitType?: SplitType;
  scheduleType?: string | null;
  numSlices?: number | null;
  defaultStartOffsetMin?: number | null;
  defaultEndTimeLocal?: string | null;
  participationRate?: number | null;
  defaultBroker?: string | null;
  defaultOrderType?: string | null;
  defaultTif?: string | null;
  defaultStrategyParams?: Record<string, unknown> | null;
  enabled?: boolean;
  priority?: number;
  allocations?: RoutePlanAllocation[];
}

export interface SubOrderProposal {
  id: number;
  routePlanId?: number | null;
  parentOrderId: string;
  routeId?: number | null;
  broker: string;
  quantity: number;
  orderType?: string | null;
  limitPrice?: number | null;
  tif?: string | null;
  strategyParams?: Record<string, unknown> | null;
  sliceIndex?: number | null;
  scheduledStart?: string | null;
  scheduledEnd?: string | null;
  parentSymbol?: string | null;
  parentSide?: string | null;
  parentTrader?: string | null;
  parentPortfolio?: string | null;
  status: ProposalStatus;
  confirmedAt?: string | null;
  submittedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface BatchConfirmRequest {
  proposalIds: number[];
  dryRun?: boolean;
}

export interface TestMatchResponse {
  planId: number;
  planName: string;
  matchedOrders: string[];
  matchCount: number;
}

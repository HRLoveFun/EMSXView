// Order types
export type OrderSide = 'BUY' | 'SELL';
export type OrderStatus = 'NEW' | 'ASSIGN' | 'WORKING' | 'PARTIAL' | 'FILLED' | 'CANCELLED' | 'COMPLETED' | 'QUEUED' | 'SUSPENDED' | 'PENDING_CANCEL' | 'REJECTED' | 'SENT';
export type OrderType = 'LIMIT' | 'MARKET' | 'STOP' | 'STOP_LIMIT';
export type TimeInForce = 'DAY' | 'GTC' | 'IOC' | 'FOK';

export type RouteStatus =
  | 'SENT' | 'WORKING' | 'PARTFILLED' | 'FILLED' | 'CANCEL'
  | 'CXLREQ' | 'CXLREJ' | 'CXLREP' | 'CXLRPRQ' | 'CXLRPRJ'
  | 'REJECTED' | 'DONE' | 'QUEUED' | 'HOLD' | 'BUST'
  | 'CORRECTED' | 'REPPEN' | 'ROUTE-ERR' | 'OMS-PEND'
  | 'A-SENT' | 'ALLOCATED' | 'OA-SENT';

export interface Order {
  id: string;
  symbol: string;
  side: OrderSide;
  status: OrderStatus;
  orderType: OrderType;
  quantity: number;
  filledQuantity: number;
  remainingQuantity: number;
  price: number | null;
  stopPrice?: number;
  timeInForce: TimeInForce;
  account: string;
  portfolio: string;
  trader: string;
  createdAt: string;
  updatedAt: string;
  notes?: string;
  exchange: string;
  currency: string;
  customNote1: string;
  customNote2: string;
  customNote3: string;
  customNote4: string;
  customNote5: string;
  traderNotes: string;
  execInstruction: string;
  avgPrice: number | null;
  percentRemain: number | null;
  percentFilled: number;
  pctChange: number | null;
  strategyType: string;
  strategyPartRate: number | null;
  strategyStyle: string;
  strategyStartTime: string;
  strategyEndTime: string;
  broker: string;
  adv5d: number | null;
  dollarValueUsd: number | null;
  fxRate: number | null;
  arrivalPrice: number | null;
  lastPrice: number | null;
  dayAvgPrice: number | null;
  mktVwap: number | null;
  isOddLot?: boolean | null;  // JP market only: true if quantity not multiple of round lot size
  roundLotSize?: number | null;  // PX_ROUND_LOT_SIZE refdata; fallback to 100 for JP markets when missing
  // Parent-child execution context (populated when an algorithmic parent exists)
  parentExecutionId?: number | null;
  scheduleType?: ScheduleType | null;
  scheduleStatus?: ExecutionStatus | null;
  childRouteCount?: number | null;
}

export interface Route {
  id: string;               // "{sequence}.{routeId}"
  routeId: number;
  sequence: number;          // parent order EMSX_SEQUENCE
  status: string;
  broker: string;
  amount: number;
  filled: number;
  working: number;
  remainBalance: number;
  avgPrice: number | null;
  limitPrice: number | null;
  stopPrice: number | null;
  lastPrice: number | null;
  lastShares: number | null;
  dayAvgPrice: number | null;
  dayFill: number;
  orderType: string;
  tif: string;
  handInstruction: string;
  execInstruction: string;
  notes: string;
  strategyType: string;
  strategyStyle: string;
  strategyPartRate1: number | null;
  strategyPartRate2: number | null;
  strategyStartTime: string;
  strategyEndTime: string;
  exchangeDestination: string;
  executeBroker: string;
  isManualRoute: number;
  routeRefId: string;
  currencyPair: string;
  urgencyLevel: string;
  routeCreateDate: string;
  routeCreateTime: string;
  lastFillDate: string;
  lastFillTime: string;
  timeStamp: string;
  routeLastUpdateTime: string;
  fillId: number;
  percentRemain: number | null;
  reasonCode: string;
  reasonDesc: string;
  brokerStatus: string;
  settleAmount: number | null;
  settleDate: string;
  commRate: number | null;
  brokerComm: number | null;
  userCommRate: number | null;
  userFees: number | null;
  miscFees: number | null;
  userNetMoney: number | null;
  principal: number | null;
  routePrice: number | null;
  // Enriched from parent order
  ticker: string;
  side: string;
  portfolio: string;
  trader: string;
  traderUuid: number;
  currency: string;
  exchange: string;
  // Parent-child execution context (populated when route is part of an algorithmic parent)
  parentExecutionId?: number | null;
  sliceIndex?: number | null;
  sliceStatus?: SliceStatus | null;
  scheduledStart?: string | null;
  scheduledEnd?: string | null;
}

// Filter types
export interface OrderFilters {
  symbol?: string;
  side?: OrderSide | '';
  status?: OrderStatus | '';
  statusMulti?: OrderStatus[];
  orderType?: OrderType | '';
  orderTypeMulti?: OrderType[];
  portfolio?: string;
  trader?: string;
  traderMulti?: string[];
  exchange?: string;
  currency?: string;
  oddLot?: boolean;  // Filter for odd lot orders (JP market only: quantity not multiple of PX_ROUND_LOT_SIZE)
}

// Route modification types
export interface CancelRouteRequest {
  sequence: number;
  routeId: number;
}

export interface ModifyRouteRequest {
  sequence: number;
  routeId: number;
  amount?: number;
  orderType?: string;
  limitPrice?: number | null;
  stopPrice?: number | null;
  tif?: string;
  broker?: string;
  exchangeDestination?: string;
  notes?: string;
  strategyParams?: {
    strategyName: string;
    fields: { value: string; disabled: boolean }[];
  };
}

export interface ModifyOrderRequest {
  orderId: string;
  orderType?: OrderType;
  price?: number | null;
  quantity?: number;
  timeInForce?: TimeInForce;
  stopPrice?: number | null;
}

export interface RouteOrderRequest {
  orderId: string;
  broker: string;
  strategy?: string;
  quantity: number;
  orderType: OrderType;
  price?: number | null;
  stopPrice?: number | null;
  timeInForce: TimeInForce;
  exchangeDestination?: string;
  notes?: string;
  strategyParams?: {
    strategyName: string;
    fields: { value: string; disabled: boolean }[];
  };
}

// Trader identity
export interface TraderInfo {
  traderName: string;
}

// Broker strategy types
export interface BrokerStrategyField {
  fieldName: string;
  disable: string;
  stringValue: string;
}

export interface BrokerStrategiesResponse {
  broker: string;
  assetClass: string;
  strategies: string[];
}

export interface BrokerStrategyInfoResponse {
  broker: string;
  strategy: string;
  assetClass: string;
  fields: BrokerStrategyField[];
}

// Broker Algorithm Configuration types
export interface StrategyParameter {
  fieldName: string;
  stringValue: string;
  disable: string;
  order?: number;
  dataType: 'string' | 'number' | 'boolean';
  description: string;
}

export interface StrategyConfig {
  name: string;
  parameters: StrategyParameter[];
}

export interface BrokerAlgorithmConfig {
  broker: string;
  assetClass?: string;
  strategies: StrategyConfig[];
}

// Batch update types
export type UpdateableField = 'price' | 'quantity' | 'timeInForce' | 'status';

export interface BatchUpdateRequest {
  orderIds: string[];
  field: UpdateableField;
  value: string | number;
}

export interface BatchUpdateResponse {
  success: boolean;
  updatedCount: number;
  failedOrders?: { orderId: string; reason: string }[];
  message?: string;
}

// API Response types
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

// Connection status
export type ConnectionStatus = 'connected' | 'disconnected' | 'pending';
export type BloombergConnectionState = 'connected' | 'disconnected' | 'connecting' | 'error';
export type StartupPhase = 'backend_starting' | 'bloomberg_connecting' | 'subscriptions_warming' | 'ready' | 'error';

export interface BackendStartupSnapshot {
  httpReady: boolean;
  startedAt?: string | null;
  uptime?: number | null;
}

export interface BloombergStartupSnapshot {
  status: BloombergConnectionState;
  message?: string;
  lastConnected?: string | null;
  uptime?: number | null;
}

export interface SubscriptionStartupSnapshot {
  ordersInitPaintDone: boolean;
  routesInitPaintDone: boolean;
  subscriptionFailed: boolean;
  marketDataConnected: boolean;
  orderCount: number;
  routeCount: number;
  ready: boolean;
}

export interface StartupStatusSnapshot {
  phase: StartupPhase;
  ready: boolean;
  message?: string;
  backend: BackendStartupSnapshot;
  bloomberg: BloombergStartupSnapshot;
  subscriptions: SubscriptionStartupSnapshot;
}

// Parent-child execution types
export type ScheduleType = 'TWAP' | 'VWAP' | 'POV' | 'IS' | 'MANUAL';
export type ExecutionStatus = 'PENDING' | 'ACTIVE' | 'PAUSED' | 'COMPLETED' | 'CANCELLED' | 'FAILED';
export type SliceStatus = 'PENDING' | 'SENT' | 'WORKING' | 'FILLED' | 'CANCELLED' | 'FAILED';

export interface ParentExecution {
  id: number;
  sequence: number;
  orderId: string;
  trader: string;
  scheduleType: ScheduleType;
  targetQuantity: number;
  filledQuantity: number;
  startTime: string | null;
  endTime: string | null;
  participationRate: number | null;
  urgency: string | null;
  benchmarkPrice: number | null;
  broker: string | null;
  strategyParams: Record<string, unknown> | null;
  status: ExecutionStatus;
  createdAt: string;
  updatedAt: string;
  slices: ChildSlice[];
}

export interface ChildSlice {
  id: number;
  parentId: number;
  sequence: number;
  routeId: number | null;
  sliceIndex: number;
  plannedQuantity: number;
  filledQuantity: number;
  scheduledStart: string | null;
  scheduledEnd: string | null;
  limitPrice: number | null;
  strategyParams: Record<string, unknown> | null;
  status: SliceStatus;
  createdAt: string;
  updatedAt: string;
}

// Toast notification
export interface Toast {
  id: string;
  type: 'success' | 'error' | 'info';
  message: string;
  duration?: number;
}

// Benchmark execution control types
export type SchedulerCommand = 'PAUSE' | 'RESUME' | 'CANCEL';

export interface CreateParentExecutionRequest {
  orderId: string;
  scheduleType: ScheduleType;
  targetQuantity: number;
  numSlices: number;
  startTime: string;
  endTime: string;
  participationRate?: number | null;
  volumeProfile?: number[] | null;
  broker?: string;
  urgency?: string;
  strategyParams?: Record<string, unknown>;
}

export interface ParentExecutionCommandRequest {
  command: SchedulerCommand;
}

export interface SchedulerStateResponse {
  parentId: number;
  status: ExecutionStatus;
  isRunning: boolean;
  currentSliceIndex: number;
  totalSlices: number;
  slicesSent: number;
  slicesFilled: number;
  slicesCancelled: number;
  targetQuantity: number;
  filledQuantity: number;
  createdAt: string;
  updatedAt: string;
}

export interface ActiveExecutionSummary {
  parentId: number;
  orderId: string;
  scheduleType: ScheduleType;
  targetQuantity: number;
  status: ExecutionStatus;
  trader: string;
}


// ============================================================================
// Pre-trade Compliance & Batch Operations
// ============================================================================

export type ViolationCode =
  | 'NOTIONAL_TOO_SMALL'
  | 'NOTIONAL_TOO_LARGE'
  | 'JP_ODD_LOT'
  | 'NOTIONAL_UNKNOWN';

export interface Violation {
  code: ViolationCode;
  message: string;
  severity: 'BLOCK' | 'WARN';
  details?: Record<string, unknown> | null;
}

export interface BatchRouteOrderItem {
  orderId: string;
  /** Stable client-side key when one orderId yields multiple destinations
   *  (multi-broker split). Echoed back as the result key. */
  clientKey?: string;
  override?: Partial<Omit<RouteOrderRequest, 'orderId'>>;
}

export interface BatchRouteOrderRequest {
  template: Partial<Omit<RouteOrderRequest, 'orderId'>>;
  items: BatchRouteOrderItem[];
  dryRun?: boolean;
}

export interface BatchModifyRouteItem {
  sequence: number;
  routeId: number;
  /** Stable client-side key. Defaults to `${sequence}.${routeId}`. */
  clientKey?: string;
  override?: Partial<Omit<ModifyRouteRequest, 'sequence' | 'routeId'>>;
}

export interface BatchModifyRouteRequest {
  template: Partial<Omit<ModifyRouteRequest, 'sequence' | 'routeId'>>;
  items: BatchModifyRouteItem[];
  dryRun?: boolean;
}

export type BatchOperationItemStatus = 'SUCCESS' | 'BLOCKED' | 'FAILED';

export interface BatchOperationItemResult {
  key: string;
  status: BatchOperationItemStatus;
  message: string;
  violations: Violation[];
  routeId?: number | null;
}

export interface BatchOperationResult {
  total: number;
  succeeded: number;
  blocked: number;
  failed: number;
  items: BatchOperationItemResult[];
}

// ============================================================================
// Route Plan & RouteEngine Types
// ============================================================================

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

/**
 * Core order and route domain types.
 *
 * P3-SRP: Extracted from types/index.ts (formerly 550 lines) to establish
 * clear domain boundaries within the Execution module.
 */

// ── Order types ───────────────────────────────────────────────────────────

export type OrderSide = 'BUY' | 'SELL';
export type OrderStatus =
  | 'NEW' | 'ASSIGN' | 'WORKING' | 'PARTIAL' | 'FILLED'
  | 'CANCELLED' | 'COMPLETED' | 'QUEUED' | 'SUSPENDED'
  | 'PENDING_CANCEL' | 'REJECTED' | 'SENT';
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
  isOddLot?: boolean | null;
  roundLotSize?: number | null;
  parentExecutionId?: number | null;
  scheduleType?: import('./parent-execution').ScheduleType | null;
  scheduleStatus?: import('./parent-execution').ExecutionStatus | null;
  childRouteCount?: number | null;
}

export interface Route {
  id: string;
  routeId: number;
  sequence: number;
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
  ticker: string;
  side: string;
  portfolio: string;
  trader: string;
  traderUuid: number;
  currency: string;
  exchange: string;
  parentExecutionId?: number | null;
  sliceIndex?: number | null;
  sliceStatus?: import('./parent-execution').SliceStatus | null;
  scheduledStart?: string | null;
  scheduledEnd?: string | null;
}

// ── Filter types ─────────────────────────────────────────────────────────

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
  oddLot?: boolean;
}

// ── Route modification types ─────────────────────────────────────────────

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
  releaseTime?: number | null;
}

// ── Trader identity ──────────────────────────────────────────────────────

export interface TraderInfo {
  traderName: string;
}

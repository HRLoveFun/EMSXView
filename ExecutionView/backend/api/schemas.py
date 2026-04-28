"""
Data models for the EMSX Trading API.

Extracted from main.py to enable modular imports without circular dependencies.
"""

from __future__ import annotations

import os
import enum
from datetime import datetime
from typing import List, Optional, Dict, Any, Literal, Union

from pydantic import BaseModel, Field, field_validator, ValidationInfo, ConfigDict


# ============================================================================
# Data Models
# ============================================================================

class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(str, enum.Enum):
    NEW = "NEW"
    ASSIGN = "ASSIGN"
    WORKING = "WORKING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    PENDING_CANCEL = "PENDING_CANCEL"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    QUEUED = "QUEUED"
    SENT = "SENT"
    SUSPENDED = "SUSPENDED"

class OrderType(str, enum.Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"

class TimeInForce(str, enum.Enum):
    DAY = "DAY"
    GTC = "GTC"  # Good Till Cancelled
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill
    GTX = "GTX"  # Good Till Crossing
    GTD = "GTD"  # Good Till Date

class Order(BaseModel):
    """Order model matching frontend expectations"""
    model_config = ConfigDict(use_enum_values=True)

    id: str
    symbol: str
    side: OrderSide
    status: OrderStatus
    orderType: OrderType
    quantity: int
    filledQuantity: int = 0
    remainingQuantity: int
    price: Optional[float] = None
    stopPrice: Optional[float] = None
    timeInForce: TimeInForce
    account: str
    portfolio: str = ""
    trader: str
    createdAt: str
    updatedAt: str
    notes: Optional[str] = None
    avgPrice: Optional[float] = None
    currency: str = ""
    exchange: str = ""  # Changed from Optional[str] = None to ensure consistent string type
    customNote1: str = ""
    customNote2: str = ""
    customNote3: str = ""
    customNote4: str = ""
    customNote5: str = ""
    traderNotes: str = ""
    execInstruction: str = ""
    percentRemain: Optional[float] = None
    percentFilled: float = 0.0
    pctChange: Optional[float] = None
    strategyType: str = ""
    strategyPartRate: Optional[float] = None
    strategyStyle: str = ""
    strategyStartTime: str = ""
    strategyEndTime: str = ""
    broker: str = ""
    traderUuid: int = 0
    adv5d: Optional[float] = None
    dollarValueUsd: Optional[float] = None
    fxRate: Optional[float] = None
    arrivalPrice: Optional[float] = None
    lastPrice: Optional[float] = None
    dayAvgPrice: Optional[float] = None
    mktVwap: Optional[float] = None
    isOddLot: Optional[bool] = None  # True if JP market and quantity not multiple of round lot size
    roundLotSize: Optional[int] = None  # PX_ROUND_LOT_SIZE refdata; fallback to 100 for JP markets when missing


class RouteStatus(str, enum.Enum):
    SENT = "SENT"
    WORKING = "WORKING"
    PARTFILLED = "PARTFILLED"
    FILLED = "FILLED"
    CANCEL = "CANCEL"
    CXLREQ = "CXLREQ"
    CXLREJ = "CXLREJ"
    CXLREP = "CXLREP"
    CXLRPRQ = "CXLRPRQ"
    CXLRPRJ = "CXLRPRJ"
    REJECTED = "REJECTED"
    DONE = "DONE"
    QUEUED = "QUEUED"
    HOLD = "HOLD"
    BUST = "BUST"
    CORRECTED = "CORRECTED"
    REPPEN = "REPPEN"
    ROUTE_ERR = "ROUTE-ERR"
    OMS_PEND = "OMS-PEND"
    A_SENT = "A-SENT"
    ALLOCATED = "ALLOCATED"
    OA_SENT = "OA-SENT"


class Route(BaseModel):
    """Route model for route-level execution data"""
    model_config = ConfigDict(use_enum_values=True)

    # Key identifiers
    routeId: int  # EMSX_ROUTE_ID
    sequence: int  # EMSX_SEQUENCE (parent order)
    # Composite key for display
    id: str  # "{sequence}.{routeId}"

    # Execution
    status: str
    broker: str = ""
    amount: int = 0
    filled: int = 0
    working: int = 0
    remainBalance: int = 0
    avgPrice: Optional[float] = None
    limitPrice: Optional[float] = None
    stopPrice: Optional[float] = None
    lastPrice: Optional[float] = None
    lastShares: Optional[int] = None
    dayAvgPrice: Optional[float] = None
    dayFill: int = 0
    bseAvgPrice: Optional[float] = None
    bseFilled: int = 0
    nseAvgPrice: Optional[float] = None
    nseFilled: int = 0

    # Order info
    orderType: str = ""
    tif: str = ""
    handInstruction: str = ""
    execInstruction: str = ""
    notes: str = ""

    # Strategy
    strategyType: str = ""
    strategyStyle: str = ""
    strategyPartRate1: Optional[float] = None
    strategyPartRate2: Optional[float] = None
    strategyStartTime: str = ""
    strategyEndTime: str = ""

    # Routing details
    exchangeDestination: str = ""
    executeBroker: str = ""
    isManualRoute: int = 0
    routeRefId: str = ""
    currencyPair: str = ""
    urgencyLevel: str = ""

    # Timestamps
    routeCreateDate: str = ""
    routeCreateTime: str = ""
    lastFillDate: str = ""
    lastFillTime: str = ""
    timeStamp: str = ""
    routeLastUpdateTime: str = ""

    # Fill details
    fillId: int = 0
    percentRemain: Optional[float] = None

    # Reason / rejection
    reasonCode: str = ""
    reasonDesc: str = ""
    brokerStatus: str = ""

    # Settle
    settleAmount: Optional[float] = None
    settleDate: str = ""

    # Commission
    commRate: Optional[float] = None
    brokerComm: Optional[float] = None
    userCommRate: Optional[float] = None
    userCommAmount: Optional[float] = None
    userFees: Optional[float] = None
    miscFees: Optional[float] = None
    userNetMoney: Optional[float] = None
    principal: Optional[float] = None
    routePrice: Optional[float] = None

    # Enriched fields from parent order (stored here for persistence)
    ticker: str = ""  # Parent order's symbol (EMSX_TICKER)
    side: str = ""    # Parent order's side
    portfolio: str = ""  # Parent order's portfolio
    trader: str = ""     # Parent order's trader
    traderUuid: int = 0  # Parent order's trader UUID
    currency: str = ""   # Parent order's currency
    exchange: str = ""   # Parent order's exchange (EMSX_EXCHANGE)


class OrderFilters(BaseModel):
    """Order filter parameters"""
    symbol: Optional[str] = None
    side: Optional[OrderSide] = None
    status: Optional[OrderStatus] = None
    orderType: Optional[OrderType] = None
    portfolio: Optional[str] = None
    trader: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    oddLot: Optional[bool] = None  # Filter for odd lot orders (JP market only: quantity not multiple of PX_ROUND_LOT_SIZE)


# Use env var directly instead of settings to avoid circular import
_MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "100"))

class BatchUpdateRequest(BaseModel):
    """Batch update request"""
    orderIds: List[str] = Field(..., min_length=1)
    field: Literal["price", "quantity", "timeInForce", "status"]
    value: Union[str, float]

    @field_validator('orderIds')
    @classmethod
    def validate_order_count(cls, v: List[str]) -> List[str]:
        if len(v) > _MAX_BATCH_SIZE:
            raise ValueError(f"Batch size {len(v)} exceeds maximum of {_MAX_BATCH_SIZE}")
        return v

    @field_validator('value', mode='before')
    @classmethod
    def validate_value(cls, v: Any, info: ValidationInfo) -> Any:
        field_name = (info.data or {}).get('field')
        if field_name in ['price', 'quantity']:
            try:
                float_v = float(v)
                if float_v <= 0:
                    raise ValueError(f"{field_name} must be positive")
                return float_v
            except (ValueError, TypeError):
                raise ValueError(f"Invalid numeric value for {field_name}")
        return v

class BatchUpdateResponse(BaseModel):
    """Batch update response"""
    success: bool
    updatedCount: int
    failedOrders: Optional[List[Dict[str, str]]] = None
    message: str

class CancelRouteRequest(BaseModel):
    """Cancel route request"""
    sequence: int = Field(..., description="EMSX_SEQUENCE (parent order ID)")
    routeId: int = Field(..., description="EMSX_ROUTE_ID")

class ModifyRouteRequest(BaseModel):
    """Modify route request"""
    sequence: int = Field(..., description="EMSX_SEQUENCE (parent order ID)")
    routeId: int = Field(..., description="EMSX_ROUTE_ID")
    amount: Optional[int] = Field(None, description="New quantity")
    orderType: Optional[str] = Field(None, description="MKT, LMT, STP, STOP_LIMIT")
    limitPrice: Optional[float] = Field(None, description="Limit price (0=ignore, -99999=reset)")
    stopPrice: Optional[float] = Field(None, description="Stop price (-1=clear)")
    tif: Optional[str] = Field(None, description="DAY, GTC, IOC, FOK, GTD")
    broker: Optional[str] = Field(None, description="New broker")
    exchangeDestination: Optional[str] = Field(None, description="Exchange destination")
    notes: Optional[str] = Field(None, description="Route notes")
    strategyParams: Optional[Dict[str, Any]] = Field(None, description="Strategy parameters")

class ModifyOrderRequest(BaseModel):
    """Modify order request"""
    orderId: str = Field(..., description="EMSX_SEQUENCE (order ID)")
    orderType: Optional[str] = Field(None, description="LIMIT, MARKET, STOP, STOP_LIMIT")
    price: Optional[float] = Field(None, description="Limit price")
    quantity: Optional[int] = Field(None, description="New quantity")
    timeInForce: Optional[str] = Field(None, description="DAY, GTC, IOC, FOK")
    stopPrice: Optional[float] = Field(None, description="Stop price")

class RouteOrderRequest(BaseModel):
    """Route order request - creates a child route from a parent order"""
    orderId: str = Field(..., description="EMSX_SEQUENCE (parent order ID)")
    broker: str = Field(..., description="Broker code for routing")
    quantity: int = Field(..., description="Quantity to route", ge=1)
    orderType: str = Field(..., description="LIMIT, MARKET, STOP, STOP_LIMIT")
    price: Optional[float] = Field(None, description="Limit price")
    stopPrice: Optional[float] = Field(None, description="Stop price")
    timeInForce: str = Field(..., description="DAY, GTC, IOC, FOK")
    exchangeDestination: Optional[str] = Field(None, description="Exchange destination")
    notes: Optional[str] = Field(None, description="Route notes")
    strategyParams: Optional[Dict[str, Any]] = Field(None, description="Strategy parameters (same format as ModifyRouteRequest)")

class ApiResponse(BaseModel):
    """Standard API response wrapper"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    message: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ExecutionHistoryFillRecord(BaseModel):
    order_id: str
    route_id: str
    fill_id: str
    order_as_of_date: str
    source_date: Optional[str] = None
    local_fill_datetime: Optional[str] = None
    exchange_exec_time: Optional[str] = None
    route_as_of_time: Optional[str] = None
    ny_fill_datetime: Optional[str] = None
    broker: Optional[str] = None
    strategy_type: Optional[str] = None
    algo: Optional[str] = None
    trader_name: Optional[str] = None
    exchange: Optional[str] = None
    side: Optional[str] = None
    equ_ticker: Optional[str] = None
    ccy_ticker: Optional[str] = None
    exec_type: Optional[str] = None
    amount: Optional[float] = None
    route_shares: Optional[float] = None
    fill_price: Optional[float] = None
    fill_shares: Optional[float] = None
    fetched_at: Optional[str] = None


class ExecutionHistoryKeyContract(BaseModel):
    canonical_fact: List[str]
    raw_lineage: List[str]
    order_grouping: List[str]
    route_grouping: List[str]


class ExecutionHistorySourceContract(BaseModel):
    owner: str
    canonical_fact_store: str
    canonical_fact_dataset: str
    canonical_fact_write_entrypoint: str
    raw_lineage_store: Optional[str] = None
    raw_lineage_dataset: Optional[str] = None
    raw_lineage_write_entrypoint: Optional[str] = None
    read_entrypoint: str


class ExecutionHistoryContractData(BaseModel):
    keys: ExecutionHistoryKeyContract
    source: ExecutionHistorySourceContract


class ExecutionHistoryFillData(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    contract: Optional[ExecutionHistoryContractData] = None
    row_count: int
    rows: List[ExecutionHistoryFillRecord]


class ExecutionHistoryFillResponse(BaseModel):
    success: bool
    data: ExecutionHistoryFillData
    message: str = ""


class ExecutionHistoryOrderSummaryRecord(BaseModel):
    order_id: str
    order_as_of_date: str
    equ_ticker: Optional[str] = None
    side: Optional[str] = None
    route_count: int
    fill_count: int
    total_fill_shares: Optional[float] = None
    average_fill_price: Optional[float] = None
    first_fill_time: Optional[str] = None
    last_fill_time: Optional[str] = None


class ExecutionHistoryOrderSummaryData(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    contract: Optional[ExecutionHistoryContractData] = None
    row_count: int
    rows: List[ExecutionHistoryOrderSummaryRecord]


class ExecutionHistoryOrderSummaryResponse(BaseModel):
    success: bool
    data: ExecutionHistoryOrderSummaryData
    message: str = ""


class ExecutionHistoryRouteSummaryRecord(BaseModel):
    order_id: str
    route_id: str
    order_as_of_date: str
    broker: Optional[str] = None
    algo: Optional[str] = None
    trader_name: Optional[str] = None
    exchange: Optional[str] = None
    side: Optional[str] = None
    equ_ticker: Optional[str] = None
    fill_count: int
    total_fill_shares: Optional[float] = None
    average_fill_price: Optional[float] = None
    first_fill_time: Optional[str] = None
    last_fill_time: Optional[str] = None


class ExecutionHistoryRouteSummaryData(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    contract: Optional[ExecutionHistoryContractData] = None
    row_count: int
    rows: List[ExecutionHistoryRouteSummaryRecord]


class ExecutionHistoryRouteSummaryResponse(BaseModel):
    success: bool
    data: ExecutionHistoryRouteSummaryData
    message: str = ""

class ConnectionStatus(BaseModel):
    """Bloomberg connection status"""
    status: Literal["connected", "disconnected", "connecting", "error"]
    message: Optional[str] = None
    lastConnected: Optional[str] = None
    uptime: Optional[int] = None  # seconds


class BackendStartupStatus(BaseModel):
    """Backend process readiness snapshot."""
    httpReady: bool
    startedAt: Optional[str] = None
    uptime: Optional[int] = None


class SubscriptionStartupStatus(BaseModel):
    """EMSX subscription warmup status."""
    ordersInitPaintDone: bool
    routesInitPaintDone: bool
    subscriptionFailed: bool
    marketDataConnected: bool
    orderCount: int
    routeCount: int
    ready: bool


class StartupStatus(BaseModel):
    """Composite startup state for frontend warmup UX."""
    phase: Literal["backend_starting", "bloomberg_connecting", "subscriptions_warming", "ready", "error"]
    ready: bool
    message: Optional[str] = None
    backend: BackendStartupStatus
    bloomberg: ConnectionStatus
    subscriptions: SubscriptionStartupStatus


class LoginRequest(BaseModel):
    """Login credentials"""
    username: str
    password: str


# ============================================================================
# Broker Algorithm Configuration Models
# ============================================================================

class StrategyParameter(BaseModel):
    """Strategy parameter configuration"""
    fieldName: str
    stringValue: str
    disable: str
    dataType: str = "string"
    description: str = ""

class StrategyConfig(BaseModel):
    """Strategy configuration for a broker"""
    name: str
    parameters: List[StrategyParameter]

class BrokerAlgorithmConfig(BaseModel):
    """Broker algorithm configuration"""
    broker: str
    exchange: str
    strategies: List[StrategyConfig]

class BrokerAlgorithmStorage(BaseModel):
    """Storage wrapper for broker algorithm data"""
    version: str = "1.0"
    lastUpdated: str = Field(default_factory=lambda: datetime.now().isoformat())
    configs: List[BrokerAlgorithmConfig]


# ============================================================================
# Parent Execution / Benchmark Scheduling Models
# ============================================================================

class CreateParentExecutionRequest(BaseModel):
    """Launch a new algorithmic parent execution."""
    orderId: str = Field(..., description="EMSX_SEQUENCE of the parent order")
    scheduleType: str = Field(..., description="TWAP | VWAP | POV")
    targetQuantity: int = Field(..., ge=1, description="Total quantity to execute")
    numSlices: int = Field(..., ge=1, le=1000, description="Number of child slices")
    startTime: str = Field(..., description="ISO-8601 schedule start")
    endTime: str = Field(..., description="ISO-8601 schedule end")
    participationRate: Optional[float] = Field(None, ge=0.0, le=1.0, description="POV participation rate (0-1)")
    volumeProfile: Optional[List[float]] = Field(None, description="Expected volume per bucket (len == numSlices)")
    broker: Optional[str] = Field(None, description="Default broker for child slices")
    urgency: Optional[str] = Field(None, description="Urgency level")
    strategyParams: Optional[Dict[str, Any]] = Field(None, description="Strategy parameters for child slices")


class ParentExecutionCommand(BaseModel):
    """Control command for an active parent execution."""
    command: str = Field(..., description="PAUSE | RESUME | CANCEL")


# ============================================================================
# Pre-trade Compliance & Batch Operations
# ============================================================================

# Use env var directly instead of settings to avoid circular import on schemas
_BATCH_ROUTE_MAX_SIZE = int(os.getenv("BATCH_ROUTE_MAX_SIZE", "500"))


class Violation(BaseModel):
    """Pre-trade compliance violation. All current violations are hard-blocking."""
    code: Literal[
        "NOTIONAL_TOO_SMALL",
        "NOTIONAL_TOO_LARGE",
        "JP_ODD_LOT",
        "NOTIONAL_UNKNOWN",
    ]
    message: str
    severity: Literal["BLOCK"] = "BLOCK"
    # Free-form context for UI tooltips, e.g. {"notionalUsd": 12345.67, "lotSize": 100}
    details: Optional[Dict[str, Any]] = None


class BatchRouteOrderItem(BaseModel):
    """Per-order entry inside a BatchRouteOrderRequest.

    ``clientKey`` lets the frontend disambiguate multiple split destinations
    for the same parent order (multi-broker split). When omitted, the result
    key falls back to ``orderId``. Convention used by the UI:
    ``f"{orderId}#{destinationIdx}"``.
    """
    orderId: str = Field(..., description="EMSX_SEQUENCE of the parent order")
    clientKey: Optional[str] = Field(
        None,
        description=(
            "Optional client-supplied unique key per item; surfaced back as "
            "BatchOperationItemResult.key. Required when sending multiple "
            "items with the same orderId (multi-broker split)."
        ),
    )
    override: Optional[Dict[str, Any]] = Field(
        None,
        description="Partial RouteOrderRequest fields that override the template for this row",
    )


class BatchRouteOrderRequest(BaseModel):
    """Batch-route N parent orders against a shared template + per-row overrides."""
    template: Dict[str, Any] = Field(
        ...,
        description=(
            "Template values for RouteOrderRequest fields (broker, orderType, "
            "timeInForce, price, stopPrice, exchangeDestination, notes, "
            "strategyParams). orderId/quantity must be provided per item."
        ),
    )
    items: List[BatchRouteOrderItem] = Field(..., min_length=1)
    dryRun: bool = Field(False, description="If true, run compliance + validation only; do not call EMSX")

    @field_validator("items")
    @classmethod
    def _validate_size(cls, v: List[BatchRouteOrderItem]) -> List[BatchRouteOrderItem]:
        if len(v) > _BATCH_ROUTE_MAX_SIZE:
            raise ValueError(
                f"Batch size {len(v)} exceeds maximum of {_BATCH_ROUTE_MAX_SIZE}"
            )
        return v


class BatchModifyRouteItem(BaseModel):
    """Per-route entry inside a BatchModifyRouteRequest."""
    sequence: int = Field(..., description="EMSX_SEQUENCE (parent order ID)")
    routeId: int = Field(..., description="EMSX_ROUTE_ID")
    clientKey: Optional[str] = Field(
        None,
        description="Optional client-supplied unique key; defaults to '{sequence}.{routeId}'.",
    )
    override: Optional[Dict[str, Any]] = Field(
        None,
        description="Partial ModifyRouteRequest fields that override the template for this row",
    )


class BatchModifyRouteRequest(BaseModel):
    """Batch-modify N existing routes against a shared template + per-row overrides."""
    template: Dict[str, Any] = Field(
        ...,
        description=(
            "Template values for ModifyRouteRequest fields (amount, orderType, "
            "limitPrice, stopPrice, tif, exchangeDestination, notes, strategyParams). "
            "sequence/routeId must be provided per item."
        ),
    )
    items: List[BatchModifyRouteItem] = Field(..., min_length=1)
    dryRun: bool = Field(False, description="If true, run compliance + validation only; do not call EMSX")

    @field_validator("items")
    @classmethod
    def _validate_size(cls, v: List[BatchModifyRouteItem]) -> List[BatchModifyRouteItem]:
        if len(v) > _BATCH_ROUTE_MAX_SIZE:
            raise ValueError(
                f"Batch size {len(v)} exceeds maximum of {_BATCH_ROUTE_MAX_SIZE}"
            )
        return v


class BatchOperationItemResult(BaseModel):
    """Per-item result for a batch route / modify-route operation."""
    key: str = Field(..., description="orderId for batch-route, '{sequence}.{routeId}' for batch-modify")
    status: Literal["SUCCESS", "BLOCKED", "FAILED"]
    message: str = ""
    violations: List[Violation] = Field(default_factory=list)
    routeId: Optional[int] = None  # Populated for SUCCESS on batch-route


class BatchOperationResult(BaseModel):
    """Aggregate result for a batch route / modify-route operation."""
    total: int
    succeeded: int
    blocked: int
    failed: int
    items: List[BatchOperationItemResult]

"""Route-related schemas."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class Route(BaseModel):
    """Route model for route-level execution data."""

    model_config = ConfigDict(use_enum_values=True)

    # Key identifiers
    routeId: int
    sequence: int
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

    # Enriched fields from parent order
    ticker: str = ""
    side: str = ""
    portfolio: str = ""
    trader: str = ""
    traderUuid: int = 0
    currency: str = ""
    exchange: str = ""


class CancelRouteRequest(BaseModel):
    """Cancel route request."""

    sequence: int = Field(..., description="EMSX_SEQUENCE (parent order ID)")
    routeId: int = Field(..., description="EMSX_ROUTE_ID")


class ModifyRouteRequest(BaseModel):
    """Modify route request."""

    sequence: int = Field(..., description="EMSX_SEQUENCE (parent order ID)")
    routeId: int = Field(..., description="EMSX_ROUTE_ID")
    amount: Optional[int] = Field(None, description="New quantity", ge=1)
    orderType: Optional[Literal["MKT", "LMT", "STP", "STOP_LIMIT", "LIMIT", "MARKET", "STOP"]] = Field(
        None, description="MKT, LMT, STP, STOP_LIMIT"
    )
    limitPrice: Optional[float] = Field(None, description="Limit price (0=ignore, -99999=reset)")
    stopPrice: Optional[float] = Field(None, description="Stop price (-1=clear)")
    tif: Optional[Literal["DAY", "GTC", "IOC", "FOK", "GTD"]] = Field(None, description="DAY, GTC, IOC, FOK, GTD")
    broker: Optional[str] = Field(None, description="New broker", max_length=128)
    exchangeDestination: Optional[str] = Field(None, description="Exchange destination", max_length=64)
    notes: Optional[str] = Field(None, description="Route notes", max_length=2000)
    strategyParams: Optional[Dict[str, Any]] = Field(None, description="Strategy parameters")


class RouteOrderRequest(BaseModel):
    """Route order request - creates a child route from a parent order."""

    orderId: str = Field(..., description="EMSX_SEQUENCE (parent order ID)", max_length=64)
    broker: str = Field(..., description="Broker code for routing", max_length=128)
    quantity: int = Field(..., description="Quantity to route", ge=1)
    orderType: Literal["LIMIT", "MARKET", "STOP", "STOP_LIMIT"] = Field(..., description="LIMIT, MARKET, STOP, STOP_LIMIT")
    price: Optional[float] = Field(None, description="Limit price", ge=0)
    stopPrice: Optional[float] = Field(None, description="Stop price", ge=0)
    timeInForce: Literal["DAY", "GTC", "IOC", "FOK", "GTD"] = Field(..., description="DAY, GTC, IOC, FOK, GTD")
    exchangeDestination: Optional[str] = Field(None, description="Exchange destination", max_length=64)
    notes: Optional[str] = Field(None, description="Route notes", max_length=2000)
    strategyParams: Optional[Dict[str, Any]] = Field(None, description="Strategy parameters")
    releaseTime: Optional[int] = Field(None, description="EMSX_RELEASE_TIME in HHMM format", ge=0, le=2359)

"""Route plan & sub-order proposal schemas."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

_BATCH_ROUTE_MAX_SIZE = int(os.getenv("BATCH_ROUTE_MAX_SIZE", "500"))


class RoutePlanAllocationItem(BaseModel):
    """Single broker allocation entry within a route plan."""

    broker: str = Field(..., description="Broker code")
    allocationType: Literal["PERCENTAGE", "FIXED"] = Field("PERCENTAGE")
    allocationValue: float = Field(..., description="Percentage (0-100) or fixed share count")
    orderType: Optional[str] = Field(None)
    limitPriceOffset: Optional[float] = Field(None)
    strategyParams: Optional[Dict[str, Any]] = Field(None)
    sortOrder: int = Field(0)


class RoutePlanCreate(BaseModel):
    """Create a new route plan."""

    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    matchMarket: str = Field(..., min_length=1, max_length=32)
    matchSymbol: Optional[str] = None
    matchSide: Literal["BUY", "SELL", "BOTH"] = Field("BOTH")
    matchPortfolio: Optional[str] = None
    matchTrader: Optional[str] = None
    matchExchange: Optional[str] = None
    matchCurrency: Optional[str] = Field(None, max_length=8)
    activationMode: Literal["AUTO", "MANUAL"] = Field("MANUAL")
    submissionMode: Literal["MANUAL_CONFIRM", "AUTO_SUBMIT"] = Field("MANUAL_CONFIRM")
    splitType: Literal["BROKER_SPLIT", "TIME_SCHEDULE", "HYBRID"] = Field("BROKER_SPLIT")
    scheduleType: Optional[str] = None
    numSlices: Optional[int] = Field(None, ge=1, le=1000)
    defaultStartOffsetMin: Optional[int] = None
    defaultEndTimeLocal: Optional[str] = None
    participationRate: Optional[float] = Field(None, ge=0.0, le=1.0)
    defaultBroker: Optional[str] = None
    defaultOrderType: Optional[str] = None
    defaultTif: Optional[str] = None
    defaultStrategyParams: Optional[Dict[str, Any]] = None
    enabled: bool = Field(True)
    priority: int = Field(0)
    allocations: Optional[List[RoutePlanAllocationItem]] = None


class RoutePlanUpdate(BaseModel):
    """Update an existing route plan (partial)."""

    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None
    matchMarket: Optional[str] = Field(None, min_length=1, max_length=32)
    matchSymbol: Optional[str] = None
    matchSide: Optional[Literal["BUY", "SELL", "BOTH"]] = None
    matchPortfolio: Optional[str] = None
    matchTrader: Optional[str] = None
    matchExchange: Optional[str] = None
    matchCurrency: Optional[str] = Field(None, max_length=8)
    activationMode: Optional[Literal["AUTO", "MANUAL"]] = None
    submissionMode: Optional[Literal["MANUAL_CONFIRM", "AUTO_SUBMIT"]] = None
    splitType: Optional[Literal["BROKER_SPLIT", "TIME_SCHEDULE", "HYBRID"]] = None
    scheduleType: Optional[str] = None
    numSlices: Optional[int] = Field(None, ge=1, le=1000)
    defaultStartOffsetMin: Optional[int] = None
    defaultEndTimeLocal: Optional[str] = None
    participationRate: Optional[float] = Field(None, ge=0.0, le=1.0)
    defaultBroker: Optional[str] = None
    defaultOrderType: Optional[str] = None
    defaultTif: Optional[str] = None
    defaultStrategyParams: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    allocations: Optional[List[RoutePlanAllocationItem]] = None


class RoutePlanResponse(BaseModel):
    """Route plan as returned by the API."""

    id: int
    name: str
    description: Optional[str] = None
    matchMarket: str
    matchSymbol: Optional[str] = None
    matchSide: str
    matchPortfolio: Optional[str] = None
    matchTrader: Optional[str] = None
    matchExchange: Optional[str] = None
    matchCurrency: Optional[str] = None
    activationMode: str
    submissionMode: str
    splitType: str
    scheduleType: Optional[str] = None
    numSlices: Optional[int] = None
    defaultStartOffsetMin: Optional[int] = None
    defaultEndTimeLocal: Optional[str] = None
    participationRate: Optional[float] = None
    defaultBroker: Optional[str] = None
    defaultOrderType: Optional[str] = None
    defaultTif: Optional[str] = None
    defaultStrategyParams: Optional[Dict[str, Any]] = None
    enabled: bool
    priority: int
    allocations: list[RoutePlanAllocationItem] = Field(default_factory=list)
    createdAt: str
    updatedAt: str


class SubOrderProposalResponse(BaseModel):
    """Sub-order proposal as returned by the API."""

    id: int
    routePlanId: Optional[int] = None
    parentOrderId: str
    routeId: Optional[int] = None
    broker: str
    quantity: int
    orderType: Optional[str] = None
    limitPrice: Optional[float] = None
    tif: Optional[str] = None
    strategyParams: Optional[Dict[str, Any]] = None
    sliceIndex: Optional[int] = None
    scheduledStart: Optional[str] = None
    scheduledEnd: Optional[str] = None
    parentSymbol: Optional[str] = None
    parentSide: Optional[str] = None
    parentTrader: Optional[str] = None
    parentPortfolio: Optional[str] = None
    status: str
    confirmedAt: Optional[str] = None
    submittedAt: Optional[str] = None
    createdAt: str
    updatedAt: str


class TestMatchResponse(BaseModel):
    """Result of testing a route plan against current orders."""

    planId: int
    planName: str
    matchedOrders: list[str] = Field(default_factory=list)
    matchCount: int = 0

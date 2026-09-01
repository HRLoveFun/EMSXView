"""Order-related schemas."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from .common import OrderSide, OrderStatus, OrderType, TimeInForce


class Order(BaseModel):
    """Order model matching frontend expectations."""

    model_config = ConfigDict(use_enum_values=True)

    id: str
    symbol: str = Field(max_length=64)
    side: OrderSide
    status: OrderStatus
    orderType: OrderType
    quantity: int
    filledQuantity: int = 0
    remainingQuantity: int
    price: Optional[float] = None
    stopPrice: Optional[float] = None
    timeInForce: TimeInForce
    account: str = Field(max_length=128)
    portfolio: str = Field(default="", max_length=128)
    trader: str = Field(max_length=128)
    createdAt: str
    updatedAt: str
    notes: Optional[str] = Field(default=None, max_length=5000)
    avgPrice: Optional[float] = None
    currency: str = Field(default="", max_length=16)
    exchange: str = Field(default="", max_length=16)
    customNote1: str = Field(default="", max_length=2000)
    customNote2: str = Field(default="", max_length=2000)
    customNote3: str = Field(default="", max_length=2000)
    customNote4: str = Field(default="", max_length=2000)
    customNote5: str = Field(default="", max_length=2000)
    traderNotes: str = Field(default="", max_length=5000)
    execInstruction: str = Field(default="", max_length=128)
    percentRemain: Optional[float] = None
    percentFilled: float = 0.0
    pctChange: Optional[float] = None
    strategyType: str = Field(default="", max_length=64)
    strategyPartRate: Optional[float] = None
    strategyStyle: str = Field(default="", max_length=64)
    strategyStartTime: str = Field(default="", max_length=16)
    strategyEndTime: str = Field(default="", max_length=16)
    broker: str = Field(default="", max_length=128)
    traderUuid: int = 0
    adv5d: Optional[float] = None
    dollarValueUsd: Optional[float] = None
    fxRate: Optional[float] = None
    arrivalPrice: Optional[float] = None
    lastPrice: Optional[float] = None
    dayAvgPrice: Optional[float] = None
    mktVwap: Optional[float] = None
    isOddLot: Optional[bool] = None
    roundLotSize: Optional[int] = None
    basketName: str = Field(default="", max_length=128)
    basketNum: Optional[int] = None


class OrderFilters(BaseModel):
    """Order filter parameters."""

    symbol: Optional[str] = Field(default=None, max_length=64)
    side: Optional[OrderSide] = None
    status: Optional[OrderStatus] = None
    orderType: Optional[OrderType] = None
    portfolio: Optional[str] = Field(default=None, max_length=128)
    trader: Optional[str] = Field(default=None, max_length=128)
    exchange: Optional[str] = Field(default=None, max_length=16)
    currency: Optional[str] = Field(default=None, max_length=16)
    oddLot: Optional[bool] = None


class ModifyOrderRequest(BaseModel):
    """Modify order request."""

    orderId: str = Field(max_length=64)
    orderType: Optional[Literal["LIMIT", "MARKET", "STOP", "STOP_LIMIT"]] = None
    price: Optional[float] = Field(default=None, ge=0)
    quantity: Optional[int] = Field(default=None, ge=1)
    timeInForce: Optional[Literal["DAY", "GTC", "IOC", "FOK", "GTD"]] = None
    stopPrice: Optional[float] = Field(default=None, ge=0)

"""Order-related schemas."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict

from .common import OrderSide, OrderStatus, OrderType, TimeInForce


class Order(BaseModel):
    """Order model matching frontend expectations."""

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
    exchange: str = ""
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
    isOddLot: Optional[bool] = None
    roundLotSize: Optional[int] = None


class OrderFilters(BaseModel):
    """Order filter parameters."""

    symbol: Optional[str] = None
    side: Optional[OrderSide] = None
    status: Optional[OrderStatus] = None
    orderType: Optional[OrderType] = None
    portfolio: Optional[str] = None
    trader: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    oddLot: Optional[bool] = None


class ModifyOrderRequest(BaseModel):
    """Modify order request."""

    orderId: str
    orderType: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    timeInForce: Optional[str] = None
    stopPrice: Optional[float] = None

"""Shared enums and the standard API response wrapper."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


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
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    GTX = "GTX"
    GTD = "GTD"


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


class ApiResponse(BaseModel):
    """Standard API response wrapper."""

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    message: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

"""Parent execution & benchmark scheduling schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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

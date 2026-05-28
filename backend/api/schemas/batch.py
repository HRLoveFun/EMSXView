"""Batch operation schemas — update, route, modify, confirm."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, ValidationInfo

# Use env var directly to avoid circular import
_MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "100"))
_BATCH_ROUTE_MAX_SIZE = int(os.getenv("BATCH_ROUTE_MAX_SIZE", "500"))


class BatchUpdateRequest(BaseModel):
    """Batch update request."""

    orderIds: List[str] = Field(..., min_length=1)
    field: Literal["price", "quantity", "timeInForce", "status"]
    value: str | float

    @field_validator("orderIds")
    @classmethod
    def validate_order_count(cls, v: List[str]) -> List[str]:
        if len(v) > _MAX_BATCH_SIZE:
            raise ValueError(f"Batch size {len(v)} exceeds maximum of {_MAX_BATCH_SIZE}")
        return v

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, v: Any, info: ValidationInfo) -> Any:
        field_name = (info.data or {}).get("field")
        if field_name in ("price", "quantity"):
            try:
                float_v = float(v)
                if float_v <= 0:
                    raise ValueError(f"{field_name} must be positive")
                return float_v
            except (ValueError, TypeError):
                raise ValueError(f"Invalid numeric value for {field_name}")
        return v


class BatchUpdateResponse(BaseModel):
    """Batch update response."""

    success: bool
    updatedCount: int
    failedOrders: Optional[List[Dict[str, str]]] = None
    message: str


class Violation(BaseModel):
    """Pre-trade compliance violation."""

    code: Literal[
        "NOTIONAL_TOO_SMALL",
        "NOTIONAL_TOO_LARGE",
        "JP_ODD_LOT",
        "NOTIONAL_UNKNOWN",
    ]
    message: str
    severity: Literal["BLOCK", "WARN"] = "BLOCK"
    details: Optional[Dict[str, Any]] = None


class BatchRouteOrderItem(BaseModel):
    """Per-order entry inside a BatchRouteOrderRequest."""

    orderId: str = Field(..., description="EMSX_SEQUENCE of the parent order")
    clientKey: Optional[str] = Field(
        None,
        description="Optional client-supplied unique key per item; surfaced as BatchOperationItemResult.key.",
    )
    override: Optional[Dict[str, Any]] = Field(
        None,
        description="Partial RouteOrderRequest fields that override the template for this row",
    )


class BatchRouteOrderRequest(BaseModel):
    """Batch-route N parent orders against a shared template."""

    template: Dict[str, Any] = Field(
        ...,
        description="Template values for RouteOrderRequest fields.",
    )
    items: List[BatchRouteOrderItem] = Field(..., min_length=1)
    dryRun: bool = Field(False, description="If true, run compliance only; do not call EMSX")

    @field_validator("items")
    @classmethod
    def _validate_size(cls, v: List[BatchRouteOrderItem]) -> List[BatchRouteOrderItem]:
        if len(v) > _BATCH_ROUTE_MAX_SIZE:
            raise ValueError(f"Batch size {len(v)} exceeds maximum of {_BATCH_ROUTE_MAX_SIZE}")
        return v


class BatchModifyRouteItem(BaseModel):
    """Per-route entry inside a BatchModifyRouteRequest."""

    sequence: int = Field(..., description="EMSX_SEQUENCE")
    routeId: int = Field(..., description="EMSX_ROUTE_ID")
    clientKey: Optional[str] = Field(None, description="Optional client-supplied unique key")
    override: Optional[Dict[str, Any]] = Field(None, description="Partial ModifyRouteRequest fields")


class BatchModifyRouteRequest(BaseModel):
    """Batch-modify N existing routes against a shared template."""

    template: Dict[str, Any] = Field(..., description="Template values for ModifyRouteRequest fields.")
    items: List[BatchModifyRouteItem] = Field(..., min_length=1)
    dryRun: bool = Field(False, description="If true, run compliance only; do not call EMSX")

    @field_validator("items")
    @classmethod
    def _validate_size(cls, v: List[BatchModifyRouteItem]) -> List[BatchModifyRouteItem]:
        if len(v) > _BATCH_ROUTE_MAX_SIZE:
            raise ValueError(f"Batch size {len(v)} exceeds maximum of {_BATCH_ROUTE_MAX_SIZE}")
        return v


class BatchOperationItemResult(BaseModel):
    """Per-item result for a batch route / modify-route operation."""

    key: str
    status: Literal["SUCCESS", "BLOCKED", "FAILED"]
    message: str = ""
    violations: List[Violation] = Field(default_factory=list)
    routeId: Optional[int] = None


class BatchOperationResult(BaseModel):
    """Aggregate result for a batch route / modify-route operation."""

    total: int
    succeeded: int
    blocked: int
    failed: int
    items: List[BatchOperationItemResult]


class BatchConfirmRequest(BaseModel):
    """Batch confirm and submit sub-order proposals."""

    proposalIds: List[int] = Field(..., min_length=1)
    dryRun: bool = Field(False)

    @field_validator("proposalIds")
    @classmethod
    def validate_size(cls, v: List[int]) -> List[int]:
        if len(v) > _BATCH_ROUTE_MAX_SIZE:
            raise ValueError(f"Batch size {len(v)} exceeds maximum of {_BATCH_ROUTE_MAX_SIZE}")
        return v

"""Route creation and modification business logic.

Centralises validation, pre-flight checks, and Bloomberg request
delegation so that both create and modify use the same strategy
parameter handling.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from schemas import RouteOrderRequest, ModifyRouteRequest

if TYPE_CHECKING:
    from services.bloomberg_interface import BloombergEMSXAdapterInterface

logger = logging.getLogger(__name__)

# Statuses that permit route creation
ROUTABLE_STATUSES = frozenset({"NEW", "ASSIGN", "WORKING", "PARTIAL", "SENT", "QUEUED"})


def validate_route_request(request: RouteOrderRequest, parent_order: Any) -> None:
    """Run pre-flight checks before sending a RouteEx request.

    Raises ``HTTPException`` on failure — suitable for direct use in
    FastAPI endpoint handlers.
    """
    if parent_order is None:
        raise HTTPException(404, f"Order {request.orderId} not found")

    if parent_order.status not in ROUTABLE_STATUSES:
        raise HTTPException(
            400,
            f"Order {request.orderId} has status '{parent_order.status}' — "
            f"only orders with status {', '.join(sorted(ROUTABLE_STATUSES))} can be routed",
        )

    if request.quantity > parent_order.remainingQuantity:
        raise HTTPException(
            400,
            f"Route quantity ({request.quantity}) exceeds remaining quantity "
            f"({parent_order.remainingQuantity})",
        )


def validate_trader_ownership(
    order_id: str,
    parent_trader: str | None,
    terminal_trader: str | None,
) -> None:
    """Verify the current terminal trader matches the order's trader."""
    if terminal_trader and parent_trader and terminal_trader.upper() != parent_trader.upper():
        raise HTTPException(
            403,
            f"Cannot route order {order_id}: assigned to trader "
            f"'{parent_trader}', but current trader is '{terminal_trader}'",
        )


def build_strategy_elements(strategy_params: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Normalise strategy param dict into internal field-indicator pairs.

    Returns ``None`` when *strategy_params* is empty or missing required keys,
    so callers can short-circuit.
    """
    if not strategy_params:
        return None

    strategy_name = strategy_params.get("strategyName", "")
    fields_data = strategy_params.get("fields", [])

    if not strategy_name or not isinstance(fields_data, list):
        return None

    return [
        {
            "value": str(f.get("value", "")) if not f.get("disabled", False) else "",
            "indicator": 1 if f.get("disabled", False) else 0,
        }
        for f in fields_data
    ]

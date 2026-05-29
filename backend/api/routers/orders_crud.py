"""Orders CRUD endpoints — /api/orders* GET/modify/route/batch endpoints.

Extracted from the formerly mixed-domain orders.py (lines 1-210).
Phase 5: Separated CRUD operations from execution scheduling and handoff.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from schemas import (
    ApiResponse, OrderFilters,
    OrderSide, OrderStatus, OrderType,
    BatchUpdateRequest, ModifyOrderRequest, RouteOrderRequest,
    BatchRouteOrderRequest,
)
from deps import verify_token, audit_log, get_bloomberg_service
from services import batch_route_service, compliance_service
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["Orders"])


@router.get("/api/orders/status", response_model=ApiResponse)
async def get_orders_status(
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Get order subscription status."""
    svc = bloomberg
    data = {
        "init_paint_done": svc._init_paint_done,
        "order_count": len(svc._orders),
        "route_count": len(svc._routes),
        "subscription_failed": svc._subscription_failed,
        "is_connected": svc.connected,
    }
    return ApiResponse(success=True, data=data, message="Order subscription status")


@router.get("/api/orders", response_model=ApiResponse)
async def get_orders(
    symbol: Optional[str] = None,
    side: Optional[OrderSide] = None,
    status: Optional[OrderStatus] = None,
    orderType: Optional[OrderType] = None,
    portfolio: Optional[str] = None,
    trader: Optional[str] = None,
    exchange: Optional[str] = None,
    currency: Optional[str] = None,
    oddLot: Optional[bool] = None,
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Get orders from EMSX with optional filtering."""
    filters = OrderFilters(
        symbol=symbol, side=side, status=status, orderType=orderType,
        portfolio=portfolio, trader=trader, exchange=exchange,
        currency=currency, oddLot=oddLot,
    )
    orders = await bloomberg.get_orders(filters)
    audit_log("GET_ORDERS", user.get("sub"), {"filters": filters.model_dump(exclude_none=True)})
    return ApiResponse(success=True, data=orders, message=f"Retrieved {len(orders)} orders")


@router.post("/api/orders/modify", response_model=ApiResponse)
async def modify_order(
    request: ModifyOrderRequest,
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Modify a single order via ModifyOrderEx."""
    audit_log("MODIFY_ORDER", user.get("sub"), {
        "orderId": request.orderId,
        "orderType": request.orderType,
        "price": request.price,
        "quantity": request.quantity,
        "timeInForce": request.timeInForce,
        "stopPrice": request.stopPrice,
    })
    field_updates = {}
    if request.orderType:
        emsx_ot = {"LIMIT": "LMT", "MARKET": "MKT", "STOP": "STP", "STOP_LIMIT": "STP_LMT"}.get(
            request.orderType, request.orderType
        )
        field_updates["orderType"] = emsx_ot
    if request.price is not None:
        field_updates["price"] = request.price
    if request.quantity is not None:
        field_updates["quantity"] = request.quantity
    if request.timeInForce:
        field_updates["timeInForce"] = request.timeInForce
    if request.stopPrice is not None:
        field_updates["stopPrice"] = request.stopPrice
    for field, value in field_updates.items():
        await bloomberg.modify_order(request.orderId, field, value)
    return ApiResponse(success=True, message=f"Order {request.orderId} modified successfully")


@router.post("/api/orders/route", response_model=ApiResponse)
async def route_order(
    request: RouteOrderRequest,
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Route an order to a broker via RouteEx."""
    audit_log("ROUTE_ORDER", user.get("sub"), {
        "orderId": request.orderId, "broker": request.broker,
        "quantity": request.quantity, "orderType": request.orderType,
    })
    parent_order = None
    if hasattr(bloomberg, "_orders") and hasattr(bloomberg, "_data_lock"):
        with bloomberg._data_lock:
            parent_order = bloomberg._orders.get(request.orderId)
    if parent_order is not None:
        violations = compliance_service.check_route(
            parent_order,
            route_qty=request.quantity,
            limit_price=request.price,
            stop_price=request.stopPrice,
            order_type=request.orderType,
        )
        if violations:
            raise HTTPException(
                400,
                detail={
                    "message": "Pre-trade compliance check failed",
                    "violations": [v.model_dump() for v in violations],
                },
            )
    result = await bloomberg.route_order(request)
    return ApiResponse(success=True, data=result, message=f"Route created for order {request.orderId}")


@router.post("/api/orders/batch-update", response_model=ApiResponse)
async def batch_update(
    request: BatchUpdateRequest,
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Batch update multiple orders."""
    audit_log("BATCH_UPDATE", user.get("sub"), {
        "orderIds": request.orderIds, "field": request.field, "value": str(request.value),
    })
    result = await bloomberg.batch_update(request)
    return ApiResponse(success=result.success, data=result.model_dump(), message=result.message)


@router.post("/api/orders/batch-route")
async def batch_route(
    request: BatchRouteOrderRequest,
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Batch-route N parent orders."""
    audit_log("BATCH_ROUTE", user.get("sub"), {
        "itemCount": len(request.items),
        "templateKeys": sorted(request.template.keys()),
        "dryRun": request.dryRun,
    })
    terminal_trader = (
        bloomberg.get_terminal_trader_name()
        if hasattr(bloomberg, "get_terminal_trader_name")
        else None
    )
    if request.dryRun:
        result = await batch_route_service.dry_run_batch_route(
            bloomberg, request, terminal_trader=terminal_trader,
        )
        return ApiResponse(
            success=True, data=result.model_dump(),
            message=f"Dry-run: {result.succeeded} ready, {result.blocked} blocked",
        )
    return StreamingResponse(
        batch_route_service.stream_batch_route(
            bloomberg, request, terminal_trader=terminal_trader,
        ),
        media_type="application/x-ndjson",
    )


@router.get("/api/orders/refresh", response_model=ApiResponse)
async def refresh_orders(
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Force-refresh order list from Bloomberg."""
    orders = await bloomberg.get_orders()
    audit_log("REFRESH_ORDERS", user.get("sub"), {})
    return ApiResponse(success=True, data=orders, message=f"Retrieved {len(orders)} orders")


@router.post("/api/orders/{order_id}/cancel", response_model=ApiResponse)
async def cancel_order(
    order_id: str,
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Cancel a single order."""
    audit_log("CANCEL_ORDER", user.get("sub"), {"orderId": order_id})
    await bloomberg.cancel_order(order_id)
    return ApiResponse(success=True, message=f"Order {order_id} cancelled successfully")

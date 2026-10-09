"""Orders CRUD endpoints — /api/orders* GET/modify/route/batch endpoints.

Extracted from the formerly mixed-domain orders.py (lines 1-210).
Phase 5: Separated CRUD operations from execution scheduling and handoff.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from schemas import (
    ApiResponse, OrderFilters,
    OrderSide, OrderStatus, OrderType,
    BatchUpdateRequest, ModifyOrderRequest, RouteOrderRequest,
    BatchRouteOrderRequest,
)
from deps import verify_token, require_permission, audit_log, audit_result, get_bloomberg_service, get_repo_provider
from services import batch_route_service, compliance_service
from services.authorization_service import enforce_for_order
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Orders"])


@router.get("/api/orders/status", response_model=ApiResponse)
async def get_orders_status(
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
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
) -> ApiResponse:
    """Get orders from EMSX with optional filtering."""
    filters = OrderFilters(
        symbol=symbol, side=side, status=status, orderType=orderType,
        portfolio=portfolio, trader=trader, exchange=exchange,
        currency=currency, oddLot=oddLot,
    )
    orders = await bloomberg.get_orders(filters)
    # 050：只读端点不写审计——前端 5 秒轮询曾刷出 1079 条 PENDING 噪音，
    # 淹没真实交易事件。审计范围收敛为写操作。
    return ApiResponse(success=True, data=orders, message=f"Retrieved {len(orders)} orders")


@router.post("/api/orders/modify", response_model=ApiResponse)
async def modify_order(
    request: ModifyOrderRequest,
    user: dict = Depends(require_permission("modify")),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
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
    user: dict = Depends(require_permission("trade")),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
    """Route an order to a broker via RouteEx."""
    # 两阶段审计 (S6/036)：发起记 PENDING，完成后回填真实结果
    correlation_id = uuid4().hex
    audit_log("ROUTE_ORDER", user.get("sub"), {
        "orderId": request.orderId, "broker": request.broker,
        "quantity": request.quantity, "orderType": request.orderType,
    }, result="PENDING", correlation_id=correlation_id)
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
            audit_result(correlation_id, "fail")
            raise HTTPException(
                400,
                detail={
                    "message": "Pre-trade compliance check failed",
                    "violations": [v.model_dump() for v in violations],
                },
            )

    # PM 授权校验 (S13/043)：exceeded 硬拒绝；not_covered 放行并告警
    # （未登记授权不阻断——严格模式由部署策略决定）；持久化不可用跳过。
    if parent_order is not None:
        authz = await enforce_for_order(
            get_repo_provider(),
            symbol=parent_order.symbol,
            side=parent_order.side,
            portfolio=parent_order.portfolio,
            additional_qty=request.quantity,
        )
        if authz and authz["outcome"] == "exceeded":
            audit_result(correlation_id, "fail")
            raise HTTPException(
                403,
                detail={
                    "message": "PM authorization limit exceeded",
                    **authz,
                },
            )
        if authz and authz["outcome"] == "not_covered":
            logger.warning(
                "Route order %s has no matching PM authorization — proceeding",
                request.orderId,
            )
    try:
        result = await bloomberg.route_order(request)
    except HTTPException as exc:
        # 超时（504）= 券商可能已收到订单但响应未返回 → 结果未知
        audit_result(correlation_id, "unknown" if exc.status_code == 504 else "fail")
        raise
    except Exception:
        audit_result(correlation_id, "fail")
        raise
    audit_result(correlation_id, "ok")
    return ApiResponse(success=True, data=result, message=f"Route created for order {request.orderId}")


@router.post("/api/orders/batch-update", response_model=ApiResponse)
async def batch_update(
    request: BatchUpdateRequest,
    user: dict = Depends(require_permission("modify")),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
    """Batch update multiple orders."""
    audit_log("BATCH_UPDATE", user.get("sub"), {
        "orderIds": request.orderIds, "field": request.field, "value": str(request.value),
    })
    result = await bloomberg.batch_update(request)
    return ApiResponse(success=result.success, data=result.model_dump(), message=result.message)


@router.post("/api/orders/batch-route")
async def batch_route(
    request: BatchRouteOrderRequest,
    user: dict = Depends(require_permission("trade")),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
    """Batch-route N parent orders."""
    # 两阶段审计 (S6/050)：发起记 PENDING，流结束后按汇总回填
    correlation_id = uuid4().hex
    audit_log("BATCH_ROUTE", user.get("sub"), {
        "itemCount": len(request.items),
        "templateKeys": sorted(request.template.keys()),
        "dryRun": request.dryRun,
    }, result="PENDING", correlation_id=correlation_id)

    # PM 授权预检 (S13/050)：逐 item 检查，任一 exceeded → 整体 403
    # （批量中部分放行部分拒绝易引发部分成交误解，保守整体拒绝）；
    # not_covered → warning 放行；缓存缺失的 item 交给 batch 内部 BLOCKED 语义。
    blocked_items: list[dict] = []
    for item in request.items:
        parent_order = None
        if hasattr(bloomberg, "_orders") and hasattr(bloomberg, "_data_lock"):
            with bloomberg._data_lock:
                parent_order = bloomberg._orders.get(item.orderId)
        if parent_order is None:
            continue
        override = item.override or {}
        qty = int(override.get("quantity") or getattr(parent_order, "remainingQuantity", 0) or 0)
        authz = await enforce_for_order(
            get_repo_provider(),
            symbol=parent_order.symbol,
            side=parent_order.side,
            portfolio=parent_order.portfolio,
            additional_qty=qty,
        )
        if authz and authz["outcome"] == "exceeded":
            blocked_items.append({"orderId": item.orderId, **authz})
        elif authz and authz["outcome"] == "not_covered":
            logger.warning(
                "Batch item %s has no matching PM authorization — proceeding",
                item.orderId,
            )
    if blocked_items:
        audit_result(correlation_id, "fail")
        raise HTTPException(
            403,
            detail={
                "message": "PM authorization limit exceeded (batch)",
                "blocked": blocked_items,
            },
        )

    terminal_trader = (
        bloomberg.get_terminal_trader_name()
        if hasattr(bloomberg, "get_terminal_trader_name")
        else None
    )
    if request.dryRun:
        result = await batch_route_service.dry_run_batch_route(
            bloomberg, request, terminal_trader=terminal_trader,
        )
        audit_result(correlation_id, "ok")
        return ApiResponse(
            success=True, data=result.model_dump(),
            message=f"Dry-run: {result.succeeded} ready, {result.blocked} blocked",
        )

    async def _stream_with_audit():
        """流结束后按汇总回填审计结果 (S6/050)。"""
        succeeded = failed = 0
        import json as _json
        async for line in batch_route_service.stream_batch_route(
            bloomberg, request, terminal_trader=terminal_trader,
        ):
            yield line
            try:
                obj = _json.loads(line) if isinstance(line, str) else line
                if isinstance(obj, dict):
                    status = obj.get("status")
                    if status == "SUCCESS":
                        succeeded += 1
                    elif status in ("FAILED", "BLOCKED"):
                        failed += 1
            except Exception:
                pass
        audit_result(correlation_id, "ok" if failed == 0 and succeeded > 0 else "fail")

    return StreamingResponse(
        _stream_with_audit(),
        media_type="application/x-ndjson",
    )


@router.get("/api/orders/refresh", response_model=ApiResponse)
async def refresh_orders(
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
    """Force-refresh order list from Bloomberg by re-subscribing EMSX."""
    orders = await bloomberg.refresh_subscription()
    audit_log("REFRESH_ORDERS", user.get("sub"), {})
    return ApiResponse(success=True, data=orders, message=f"Retrieved {len(orders)} orders")


@router.post("/api/orders/{order_id}/cancel", response_model=ApiResponse)
async def cancel_order(
    order_id: str,
    user: dict = Depends(require_permission("modify")),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
    """Cancel a single order."""
    audit_log("CANCEL_ORDER", user.get("sub"), {"orderId": order_id})
    await bloomberg.cancel_order(order_id)
    return ApiResponse(success=True, message=f"Order {order_id} cancelled successfully")

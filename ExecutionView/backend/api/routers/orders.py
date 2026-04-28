"""Orders domain router — /api/orders* endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from schemas import (
    ApiResponse, OrderFilters,
    OrderSide, OrderStatus, OrderType,
    BatchUpdateRequest, ModifyOrderRequest, RouteOrderRequest,
    BatchRouteOrderRequest,
    CreateParentExecutionRequest, ParentExecutionCommand,
)
from deps import verify_token, audit_log, get_bloomberg
from services import batch_route_service
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["Orders"])


@router.get("/api/orders/status", response_model=ApiResponse)
async def get_orders_status(user: dict = Depends(verify_token)):
    """Get order subscription status."""
    svc = get_bloomberg()
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
):
    """Get orders from EMSX with optional filtering."""
    filters = OrderFilters(
        symbol=symbol, side=side, status=status, orderType=orderType,
        portfolio=portfolio, trader=trader, exchange=exchange,
        currency=currency, oddLot=oddLot,
    )
    orders = await get_bloomberg().get_orders(filters)
    audit_log("GET_ORDERS", user.get("sub"), {"filters": filters.model_dump(exclude_none=True)})
    return ApiResponse(success=True, data=orders, message=f"Retrieved {len(orders)} orders")


@router.post("/api/orders/modify", response_model=ApiResponse)
async def modify_order(request: ModifyOrderRequest, user: dict = Depends(verify_token)):
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
        await get_bloomberg().modify_order(request.orderId, field, value)
    return ApiResponse(success=True, message=f"Order {request.orderId} modified successfully")


@router.post("/api/orders/route", response_model=ApiResponse)
async def route_order(request: RouteOrderRequest, user: dict = Depends(verify_token)):
    """Route an order to a broker via RouteEx."""
    audit_log("ROUTE_ORDER", user.get("sub"), {
        "orderId": request.orderId, "broker": request.broker,
        "quantity": request.quantity, "orderType": request.orderType,
    })
    bloomberg = get_bloomberg()
    # Pre-trade compliance check using the cached parent order.
    parent_order = None
    if hasattr(bloomberg, "_orders") and hasattr(bloomberg, "_data_lock"):
        with bloomberg._data_lock:
            parent_order = bloomberg._orders.get(request.orderId)
    if parent_order is not None:
        from services import compliance_service
        from fastapi import HTTPException
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
async def batch_update(request: BatchUpdateRequest, user: dict = Depends(verify_token)):
    """Batch update multiple orders."""
    audit_log("BATCH_UPDATE", user.get("sub"), {
        "orderIds": request.orderIds, "field": request.field, "value": str(request.value),
    })
    result = await get_bloomberg().batch_update(request)
    return ApiResponse(success=result.success, data=result.model_dump(), message=result.message)


@router.post("/api/orders/batch-route")
async def batch_route(request: BatchRouteOrderRequest, user: dict = Depends(verify_token)):
    """Batch-route N parent orders.

    - ``dryRun=true``  -> sync JSON ``BatchOperationResult`` (validation +
      compliance only; no blpapi calls).
    - ``dryRun=false`` -> NDJSON stream; one ``BatchOperationItemResult`` per
      line, plus a final ``{"summary": BatchOperationResult}`` line.
    """
    audit_log("BATCH_ROUTE", user.get("sub"), {
        "itemCount": len(request.items),
        "templateKeys": sorted(request.template.keys()),
        "dryRun": request.dryRun,
    })
    bloomberg = get_bloomberg()
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
async def refresh_orders(user: dict = Depends(verify_token)):
    """Force-refresh order list from Bloomberg."""
    orders = await get_bloomberg().get_orders()
    audit_log("REFRESH_ORDERS", user.get("sub"), {})
    return ApiResponse(success=True, data=orders, message=f"Retrieved {len(orders)} orders")


@router.post("/api/orders/{order_id}/cancel", response_model=ApiResponse)
async def cancel_order(order_id: str, user: dict = Depends(verify_token)):
    """Cancel a single order."""
    audit_log("CANCEL_ORDER", user.get("sub"), {"orderId": order_id})
    await get_bloomberg().cancel_order(order_id)
    return ApiResponse(success=True, message=f"Order {order_id} cancelled successfully")


# ============================================================================
# Parent Execution / Benchmark Scheduling Endpoints
# ============================================================================


@router.post("/api/executions", response_model=ApiResponse)
async def create_parent_execution(
    request: CreateParentExecutionRequest,
    user: dict = Depends(verify_token),
):
    """Launch a new algorithmic parent execution.

    Computes a schedule using the benchmark engine, persists
    child slices, and activates the scheduler.
    """
    from models.parent_child_orders import ScheduleType
    from services.benchmark_engine import ScheduleRequest, VolumeProfile, compute_schedule
    from services.algo_scheduler import start_execution
    from repositories.parent_child_repository import ParentChildRepository

    audit_log("CREATE_PARENT_EXEC", user.get("sub"), {
        "orderId": request.orderId,
        "scheduleType": request.scheduleType,
        "targetQuantity": request.targetQuantity,
        "numSlices": request.numSlices,
    })

    # Parse schedule type
    try:
        schedule_type = ScheduleType(request.scheduleType)
    except ValueError:
        return ApiResponse(
            success=False,
            error=f"Unsupported schedule type: {request.scheduleType}",
        )

    # Parse times
    try:
        start_time = datetime.fromisoformat(request.startTime)
        end_time = datetime.fromisoformat(request.endTime)
    except ValueError as exc:
        return ApiResponse(success=False, error=f"Invalid time format: {exc}")

    if end_time <= start_time:
        return ApiResponse(success=False, error="endTime must be after startTime")

    # Build volume profile
    volume_profile = None
    if request.volumeProfile and len(request.volumeProfile) == request.numSlices:
        volume_profile = VolumeProfile(buckets=request.volumeProfile)

    # Compute schedule
    try:
        schedule_req = ScheduleRequest(
            schedule_type=schedule_type,
            target_quantity=request.targetQuantity,
            start_time=start_time,
            end_time=end_time,
            num_slices=request.numSlices,
            participation_rate=request.participationRate,
            volume_profile=volume_profile,
        )
        planned_slices = compute_schedule(schedule_req)
    except ValueError as exc:
        return ApiResponse(success=False, error=str(exc))

    # Create parent execution record (in-memory mock — real DB in production)
    from models.parent_child_orders import ParentExecution as ParentModel
    parent = ParentModel(
        id=_next_parent_id(),
        sequence=int(request.orderId),
        order_id=request.orderId,
        trader=user.get("sub", "unknown"),
        schedule_type=schedule_type.value,
        target_quantity=request.targetQuantity,
        broker=request.broker,
        urgency=request.urgency,
        strategy_params=request.strategyParams,
        start_time=start_time,
        end_time=end_time,
        participation_rate=request.participationRate,
        status="PENDING",
    )

    # Register parent in mock store for get_execution_state lookups
    _parent_store[parent.id] = parent

    # Start via scheduler (uses mock repo)
    repo = _MockParentChildRepo(parent)
    state = await start_execution(parent, planned_slices, repo)

    return ApiResponse(
        success=True,
        data=state.to_dict(),
        message=f"Parent execution {parent.id} started with {len(planned_slices)} slices",
    )


@router.post("/api/executions/{parent_id}/command", response_model=ApiResponse)
async def control_parent_execution(
    parent_id: int,
    request: ParentExecutionCommand,
    user: dict = Depends(verify_token),
):
    """Control a running parent execution (PAUSE/RESUME/CANCEL)."""
    from services.algo_scheduler import (
        pause_execution, resume_execution, cancel_execution,
    )

    audit_log("EXEC_COMMAND", user.get("sub"), {
        "parentId": parent_id,
        "command": request.command,
    })

    parent = _parent_store.get(parent_id)
    if parent is None:
        return ApiResponse(success=False, error=f"Parent execution {parent_id} not found")

    repo = _MockParentChildRepo(parent)

    try:
        cmd = request.command.upper()
        if cmd == "PAUSE":
            state = await pause_execution(parent_id, repo)
        elif cmd == "RESUME":
            state = await resume_execution(parent_id, repo)
        elif cmd == "CANCEL":
            state = await cancel_execution(parent_id, repo)
        else:
            return ApiResponse(success=False, error=f"Unknown command: {request.command}")
    except ValueError as exc:
        return ApiResponse(success=False, error=str(exc))

    return ApiResponse(success=True, data=state.to_dict(), message=f"Command {request.command} applied")


@router.get("/api/executions/{parent_id}", response_model=ApiResponse)
async def get_parent_execution(
    parent_id: int,
    user: dict = Depends(verify_token),
):
    """Get the current state of a parent execution."""
    from services.algo_scheduler import get_execution_state

    parent = _parent_store.get(parent_id)
    if parent is None:
        return ApiResponse(success=False, error=f"Parent execution {parent_id} not found")

    repo = _MockParentChildRepo(parent)

    try:
        state = await get_execution_state(parent_id, repo)
    except ValueError as exc:
        return ApiResponse(success=False, error=str(exc))

    return ApiResponse(success=True, data=state.to_dict())


@router.get("/api/executions", response_model=ApiResponse)
async def list_parent_executions(user: dict = Depends(verify_token)):
    """List all tracked parent executions."""
    from services.algo_scheduler import list_active_parent_ids

    active_ids = list_active_parent_ids()
    result = []
    for pid in active_ids:
        parent = _parent_store.get(pid)
        if parent:
            result.append({
                "parentId": pid,
                "orderId": parent.order_id,
                "scheduleType": parent.schedule_type,
                "targetQuantity": parent.target_quantity,
                "status": parent.status,
                "trader": parent.trader,
            })

    return ApiResponse(success=True, data=result, message=f"{len(result)} active executions")


# ---------------------------------------------------------------------------
# In-memory helpers (replaced by real DB session in production)
# ---------------------------------------------------------------------------

_parent_id_counter = 0
_parent_store: dict[int, object] = {}


def _next_parent_id() -> int:
    global _parent_id_counter
    _parent_id_counter += 1
    return _parent_id_counter


class _MockParentChildRepo:
    """Thin in-memory repo adapter for parent-child operations.

    Wraps around the parent object for scheduler lifecycle calls
    without requiring a real database session.
    """

    def __init__(self, parent: object):
        self._parent = parent
        self._slices: list[object] = []
        self._slice_id_counter = 0

    async def get_parent(self, parent_id: int) -> object | None:
        if getattr(self._parent, "id", None) == parent_id:
            return self._parent
        return _parent_store.get(parent_id)

    async def update_parent_status(self, parent_id: int, status: str) -> None:
        p = _parent_store.get(parent_id)
        if p:
            p.status = status

    async def create_slices_bulk(self, slices: list[dict]) -> list[object]:
        from types import SimpleNamespace
        result = []
        for s in slices:
            self._slice_id_counter += 1
            obj = SimpleNamespace(id=self._slice_id_counter, **s)
            result.append(obj)
            self._slices.append(obj)
        return result

    async def list_slices_for_parent(self, parent_id: int) -> list[object]:
        return [s for s in self._slices if getattr(s, "parent_id", None) == parent_id]

    async def update_slice_status(self, slice_id: int, status: str) -> None:
        for s in self._slices:
            if getattr(s, "id", None) == slice_id:
                s.status = status
                break

    async def update_parent_filled(self, parent_id: int, filled_quantity: int) -> None:
        p = _parent_store.get(parent_id)
        if p:
            p.filled_quantity = filled_quantity


# ============================================================================
# WBS-08 Handoff Contracts
# ============================================================================

# Contract 1 (inbound): MarketView → ExecutionView — peek candidates
# Contract 2 (outbound): ExecutionView → CostView — publish post-trade context


class _HandoffMetadata(BaseModel):
    contract_version: str
    source: str
    handoff_target: str
    generated_at: str
    trace_id: str
    origin_trace_id: Optional[str] = None


class _CandidateRow(BaseModel):
    equ_ticker: str
    trade_date: str
    daily_close: Optional[float] = None
    total_volume: Optional[float] = None
    adv_20d: Optional[float] = None
    daily_volatility: Optional[float] = None
    intraday_volatility: Optional[float] = None
    liquidity_alert: str
    volatility_alert: str


class _CandidatePayload(BaseModel):
    source: str
    handoff_target: str
    trade_date: Optional[str] = None
    pool_id: str
    pool_label: Optional[str] = None
    row_count: int
    candidates: list[_CandidateRow] = Field(default_factory=list)


class _MarketHandoffPayload(BaseModel):
    metadata: _HandoffMetadata
    trade_date: Optional[str] = None
    pool_id: str
    pool_label: Optional[str] = None
    candidate_payload: _CandidatePayload
    execution_hint: dict = Field(default_factory=dict)


class CandidateHandoffResponse(BaseModel):
    success: bool
    data: Optional[_MarketHandoffPayload] = None
    message: str = ""


class PostTradeHandoffRequest(BaseModel):
    order_id: str = Field(min_length=1)
    parent_execution_id: Optional[str] = None
    broker: Optional[str] = None
    strategy: Optional[str] = None
    asset_class: Optional[str] = None
    urgency: Optional[str] = None
    route_ids: list[str] = Field(default_factory=list)
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    candidate_trace_id: Optional[str] = None


class _PostTradeHandoffPayload(BaseModel):
    metadata: _HandoffMetadata
    order_id: str
    parent_execution_id: Optional[str] = None
    broker: Optional[str] = None
    strategy: Optional[str] = None
    asset_class: Optional[str] = None
    urgency: Optional[str] = None
    route_ids: list[str] = Field(default_factory=list)
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    candidate_trace_id: Optional[str] = None


class PostTradeHandoffResponse(BaseModel):
    success: bool
    data: Optional[_PostTradeHandoffPayload] = None
    message: str = ""


def _serialize_metadata(metadata) -> _HandoffMetadata:
    return _HandoffMetadata(
        contract_version=metadata.contract_version,
        source=metadata.source,
        handoff_target=metadata.handoff_target,
        generated_at=metadata.generated_at,
        trace_id=metadata.trace_id,
        origin_trace_id=metadata.origin_trace_id,
    )


@router.get(
    "/api/executions/handoff/candidates",
    response_model=CandidateHandoffResponse,
)
async def get_active_candidate_handoff():
    """Peek the latest MarketView → ExecutionView candidate handoff."""
    import sys
    from pathlib import Path

    _ROOT = Path(__file__).resolve().parents[4]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from platform_data import get_shared_handoff_exchange

    handoff = get_shared_handoff_exchange().get_market_to_execution()
    if handoff is None:
        return CandidateHandoffResponse(
            success=True, data=None, message="No active MarketView → ExecutionView handoff"
        )
    payload = handoff.candidate_payload
    data = _MarketHandoffPayload(
        metadata=_serialize_metadata(handoff.metadata),
        trade_date=handoff.trade_date,
        pool_id=handoff.pool_id,
        pool_label=handoff.pool_label,
        candidate_payload=_CandidatePayload(
            source=payload.source,
            handoff_target=payload.handoff_target,
            trade_date=payload.trade_date,
            pool_id=payload.pool_id,
            pool_label=payload.pool_label,
            row_count=payload.row_count,
            candidates=[
                _CandidateRow(
                    equ_ticker=c.equ_ticker,
                    trade_date=c.trade_date,
                    daily_close=c.daily_close,
                    total_volume=c.total_volume,
                    adv_20d=c.adv_20d,
                    daily_volatility=c.daily_volatility,
                    intraday_volatility=c.intraday_volatility,
                    liquidity_alert=c.liquidity_alert,
                    volatility_alert=c.volatility_alert,
                )
                for c in payload.candidates
            ],
        ),
        execution_hint=dict(handoff.execution_hint),
    )
    return CandidateHandoffResponse(
        success=True,
        data=data,
        message=f"Handoff trace_id={handoff.metadata.trace_id}",
    )


@router.post(
    "/api/executions/handoff/post-trade",
    response_model=PostTradeHandoffResponse,
)
async def publish_post_trade_handoff(request: PostTradeHandoffRequest):
    """Publish an ExecutionView → CostView post-trade context handoff."""
    import sys
    from pathlib import Path

    _ROOT = Path(__file__).resolve().parents[4]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from platform_data import get_shared_handoff_exchange

    handoff = get_shared_handoff_exchange().publish_execution_to_cost(
        order_id=request.order_id,
        parent_execution_id=request.parent_execution_id,
        broker=request.broker,
        strategy=request.strategy,
        asset_class=request.asset_class,
        urgency=request.urgency,
        route_ids=request.route_ids,
        strategy_params=request.strategy_params,
        candidate_trace_id=request.candidate_trace_id,
    )
    return PostTradeHandoffResponse(
        success=True,
        data=_PostTradeHandoffPayload(
            metadata=_serialize_metadata(handoff.metadata),
            order_id=handoff.order_id,
            parent_execution_id=handoff.parent_execution_id,
            broker=handoff.broker,
            strategy=handoff.strategy,
            asset_class=handoff.asset_class,
            urgency=handoff.urgency,
            route_ids=list(handoff.route_ids),
            strategy_params=dict(handoff.strategy_params),
            candidate_trace_id=handoff.candidate_trace_id,
        ),
        message=(
            f"Published post-trade handoff for order {handoff.order_id} "
            f"(trace_id={handoff.metadata.trace_id})"
        ),
    )


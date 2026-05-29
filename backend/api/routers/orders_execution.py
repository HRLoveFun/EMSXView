"""Execution scheduling endpoints — /api/executions* parent execution management.

Extracted from the formerly mixed-domain orders.py (lines 213-377).
Phase 5: Separated execution scheduling from CRUD and handoff operations.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from schemas import (
    ApiResponse,
    CreateParentExecutionRequest,
    ParentExecutionCommand,
)
from deps import verify_token, audit_log
from models.parent_child_orders import ParentExecution as ParentModel, ScheduleType
from services.algo_scheduler import (
    cancel_execution,
    get_execution_state,
    list_active_parent_ids,
    pause_execution,
    resume_execution,
    start_execution,
)
from services.benchmark_engine import ScheduleRequest, VolumeProfile, compute_schedule

router = APIRouter(tags=["Executions"])


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


# ---------------------------------------------------------------------------
# Execution endpoints
# ---------------------------------------------------------------------------


@router.post("/api/executions", response_model=ApiResponse)
async def create_parent_execution(
    request: CreateParentExecutionRequest,
    user: dict = Depends(verify_token),
):
    """Launch a new algorithmic parent execution."""
    audit_log("CREATE_PARENT_EXEC", user.get("sub"), {
        "orderId": request.orderId,
        "scheduleType": request.scheduleType,
        "targetQuantity": request.targetQuantity,
        "numSlices": request.numSlices,
    })

    try:
        schedule_type = ScheduleType(request.scheduleType)
    except ValueError:
        return ApiResponse(
            success=False,
            error=f"Unsupported schedule type: {request.scheduleType}",
        )

    try:
        start_time = datetime.fromisoformat(request.startTime)
        end_time = datetime.fromisoformat(request.endTime)
    except ValueError as exc:
        return ApiResponse(success=False, error=f"Invalid time format: {exc}")

    if end_time <= start_time:
        return ApiResponse(success=False, error="endTime must be after startTime")

    volume_profile = None
    if request.volumeProfile and len(request.volumeProfile) == request.numSlices:
        volume_profile = VolumeProfile(buckets=request.volumeProfile)

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

    _parent_store[parent.id] = parent
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

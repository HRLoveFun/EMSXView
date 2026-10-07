"""Execution scheduling endpoints — /api/executions* parent execution management.

Extracted from the formerly mixed-domain orders.py (lines 213-377).
Phase 5: Separated execution scheduling from CRUD and handoff operations.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from schemas import (
    ApiResponse,
    CreateParentExecutionRequest,
    ParentExecutionCommand,
)
from config import settings
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

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Executions"])


# ---------------------------------------------------------------------------
# In-memory helpers (replaced by real DB session in production)
# ---------------------------------------------------------------------------

_parent_id_counter = 0
_parent_store: dict[int, object] = {}

# 切片存储 (S5/035)：模块级、按 parent_id 分桶——此前切片存在
# _MockParentChildRepo 实例本地列表中，查询端点每次新建 repo 实例，
# 切片「丢失」，返回 0 切片但状态仍 RUNNING。
_slices_store: dict[int, list[object]] = {}
_slice_id_counter = 0


def _next_parent_id() -> int:
    global _parent_id_counter
    _parent_id_counter += 1
    return _parent_id_counter


class _MockParentChildRepo:
    """MOCK — 内存仓库适配器（scheduler 生命周期调用的最小实现）。

    ⚠️ 非生产实现 (S5/035)：切片存于模块级 ``_slices_store``，跨请求/实例
    共享。生产环境须由 ``RepositoryProvider`` 提供真实持久化实现
    （持久化调度器与驱动循环见 029 第二波 S9）。
    """

    def __init__(self, parent: object):
        self._parent = parent

    async def get_parent(self, parent_id: int) -> object | None:
        if getattr(self._parent, "id", None) == parent_id:
            return self._parent
        return _parent_store.get(parent_id)

    async def update_parent_status(self, parent_id: int, status: str) -> None:
        p = _parent_store.get(parent_id)
        if p:
            p.status = status

    async def create_slices_bulk(self, slices: list[dict]) -> list[object]:
        global _slice_id_counter
        from types import SimpleNamespace
        bucket = _slices_store.setdefault(getattr(self._parent, "id", None), [])
        result = []
        for s in slices:
            _slice_id_counter += 1
            obj = SimpleNamespace(id=_slice_id_counter, **s)
            result.append(obj)
            bucket.append(obj)
        return result

    async def list_slices_for_parent(self, parent_id: int) -> list[object]:
        return [
            s for s in _slices_store.get(parent_id, [])
            if getattr(s, "parent_id", None) == parent_id
        ]

    async def update_slice_status(self, slice_id: int, status: str) -> None:
        for bucket in _slices_store.values():
            for s in bucket:
                if getattr(s, "id", None) == slice_id:
                    s.status = status
                    return

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
) -> ApiResponse:
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

    # S5/035：模拟仓库不可持久化——持久化已开启时告警，提示调度状态
    # 重启即失、不能仅凭配置开启判断真实持久化能力（真实实现见 029-S9）
    if settings.ENABLE_DB_PERSISTENCE:
        logger.warning(
            "Parent execution %d uses MOCK in-memory repo while "
            "ENABLE_DB_PERSISTENCE=true — slices/state will be lost on restart",
            parent.id,
        )

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
) -> ApiResponse:
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
) -> ApiResponse:
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
async def list_parent_executions(user: dict = Depends(verify_token)) -> ApiResponse:
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

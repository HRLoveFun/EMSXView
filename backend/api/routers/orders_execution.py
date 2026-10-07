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
from deps import verify_token, require_permission, audit_log, get_repo_provider
from models.parent_child_orders import ExecutionStatus, ParentExecution as ParentModel, ScheduleType
from services.algo_scheduler import (
    cancel_execution,
    get_execution_state,
    list_active_parent_ids,
    pause_execution,
    register_active_execution,
    resume_execution,
    start_execution,
)
from services.benchmark_engine import PlannedSlice, ScheduleRequest, VolumeProfile, compute_schedule

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


class _ProviderRepoAdapter:
    """DB-backed repo (S9/039)：方法调用经 RepositoryProvider 会话转发。

    与 _MockParentChildRepo 同 duck-type——调度器零改动即可切换实现。
    """

    def __init__(self, provider, parent: object):
        self._provider = provider
        self._parent = parent

    def __getattr__(self, name: str):
        async def _op(*args, **kwargs):
            return await self._provider.run_parent_child_op(name, *args, **kwargs)
        return _op


def _make_repo(parent: object) -> object:
    """按持久化可用性选择 repo 实现 (S9/039)。"""
    provider = get_repo_provider()
    if provider and provider.parent_child_available():
        return _ProviderRepoAdapter(provider, parent)
    return _MockParentChildRepo(parent)


async def persist_parent(parent: ParentModel) -> bool:
    """父单落库取 DB 主键 (S9/039)——恢复与幂等的锚点。"""
    provider = get_repo_provider()
    if not (provider and provider.parent_child_available()):
        return False
    db_parent = await provider.run_parent_child_op("create_parent", parent)
    if db_parent is not None and getattr(db_parent, "id", None):
        parent.id = db_parent.id
        _parent_store[parent.id] = parent
        return True
    logger.warning("Parent execution persist failed — falling back to in-memory id")
    return False


async def restore_active_executions() -> int:
    """重启恢复 (S9/039)：ACTIVE/PAUSED 父单与切片重建内存态与 registry。

    DB 状态为真相源；调度器 registry 重建后驱动循环可继续提交剩余切片。
    """
    provider = get_repo_provider()
    if not (provider and provider.parent_child_available()):
        return 0
    parents = await provider.run_parent_child_op("list_active_parents")
    if not parents:
        return 0
    restored = 0
    for p in parents:
        _parent_store[p.id] = p
        slices = await provider.run_parent_child_op("list_slices_for_parent", p.id) or []
        bucket = _slices_store.setdefault(p.id, [])
        bucket.extend(slices)
        # 重建调度器 registry：提交进度 = 最大已建切片 index + 1
        schedule = [
            PlannedSlice(
                slice_index=s.slice_index,
                planned_quantity=s.planned_quantity,
                scheduled_start=s.scheduled_start,
                scheduled_end=s.scheduled_end,
                weight=1.0,  # 恢复场景 weight 不参与驱动判断，占位
            )
            for s in slices
        ]
        next_index = (max((s.slice_index for s in slices), default=-1)) + 1
        register_active_execution(
            p.id, schedule,
            next_slice_index=next_index,
            is_paused=(p.status == ExecutionStatus.PAUSED.value),
        )
        restored += 1
    logger.info("Restored %d active parent execution(s) from DB", restored)
    return restored


# ---------------------------------------------------------------------------
# Execution endpoints
# ---------------------------------------------------------------------------


@router.post("/api/executions", response_model=ApiResponse)
async def create_parent_execution(
    request: CreateParentExecutionRequest,
    user: dict = Depends(require_permission("trade")),
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

    # S9/039：持久化可用时父单先落库取 DB 主键（恢复/幂等锚点），
    # 并切换 DB-backed repo；不可用时回退 MOCK（内存态，重启即失）
    persisted = await persist_parent(parent)
    if persisted:
        repo = _ProviderRepoAdapter(get_repo_provider(), parent)
    else:
        repo = _MockParentChildRepo(parent)
        if settings.ENABLE_DB_PERSISTENCE:
            logger.warning(
                "Parent execution %d uses MOCK in-memory repo while "
                "ENABLE_DB_PERSISTENCE=true — slices/state will be lost on restart",
                parent.id,
            )

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
    user: dict = Depends(require_permission("trade")),
) -> ApiResponse:
    """Control a running parent execution (PAUSE/RESUME/CANCEL)."""
    audit_log("EXEC_COMMAND", user.get("sub"), {
        "parentId": parent_id,
        "command": request.command,
    })

    parent = _parent_store.get(parent_id)
    if parent is None:
        return ApiResponse(success=False, error=f"Parent execution {parent_id} not found")

    repo = _make_repo(parent)

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

    repo = _make_repo(parent)

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

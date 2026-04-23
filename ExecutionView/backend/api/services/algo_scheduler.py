"""Runtime scheduler orchestration for algorithmic parent executions.

Manages the lifecycle of parent executions: start → pause → resume → cancel.
Uses an in-memory registry of active executions with per-parent state.
Child slices are persisted via the ParentChildRepository.

Thread-safety: All state mutations happen through async methods;
the in-memory dict is safe for single-event-loop FastAPI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from models.parent_child_orders import (
    ExecutionStatus,
    ParentExecution,
    SliceStatus,
)
from repositories.parent_child_repository import ParentChildRepository
from services.benchmark_engine import PlannedSlice

logger = logging.getLogger(__name__)


class SchedulerCommand(str, Enum):
    """Commands the scheduler accepts for a running parent execution."""

    START = "START"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"


@dataclass
class SchedulerState:
    """Snapshot of a parent execution's scheduler state."""

    parent_id: int
    status: str = ExecutionStatus.PENDING.value
    is_running: bool = False
    current_slice_index: int = 0
    total_slices: int = 0
    slices_sent: int = 0
    slices_filled: int = 0
    slices_cancelled: int = 0
    target_quantity: int = 0
    filled_quantity: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "parentId": self.parent_id,
            "status": self.status,
            "isRunning": self.is_running,
            "currentSliceIndex": self.current_slice_index,
            "totalSlices": self.total_slices,
            "slicesSent": self.slices_sent,
            "slicesFilled": self.slices_filled,
            "slicesCancelled": self.slices_cancelled,
            "targetQuantity": self.target_quantity,
            "filledQuantity": self.filled_quantity,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


# ---------------------------------------------------------------------------
# In-memory registry of active parent executions
# ---------------------------------------------------------------------------

@dataclass
class _ActiveExecution:
    """Internal tracker for a running parent execution."""

    parent_id: int
    schedule: list[PlannedSlice] = field(default_factory=list)
    next_slice_index: int = 0
    is_paused: bool = False


_registry: dict[int, _ActiveExecution] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public lifecycle API
# ---------------------------------------------------------------------------


async def start_execution(
    parent: ParentExecution,
    slices: list[PlannedSlice],
    repo: ParentChildRepository,
) -> SchedulerState:
    """Start a parent execution: persist child slices and activate tracking.

    1. Bulk-inserts ChildSlice rows (status=PENDING).
    2. Sets parent status to ACTIVE.
    3. Registers the execution in the in-memory scheduler.
    """
    if parent.id in _registry:
        raise ValueError(f"Parent {parent.id} is already registered in the scheduler")

    # Persist child slices
    slice_dicts = [
        {
            "parent_id": parent.id,
            "sequence": parent.sequence,
            "slice_index": ps.slice_index,
            "planned_quantity": ps.planned_quantity,
            "scheduled_start": ps.scheduled_start,
            "scheduled_end": ps.scheduled_end,
            "status": SliceStatus.PENDING.value,
        }
        for ps in slices
    ]
    await repo.create_slices_bulk(slice_dicts)

    # Activate parent
    await repo.update_parent_status(parent.id, ExecutionStatus.ACTIVE.value)

    # Register in scheduler
    entry = _ActiveExecution(
        parent_id=parent.id,
        schedule=slices,
        next_slice_index=0,
    )
    _registry[parent.id] = entry

    logger.warning(
        "Scheduler START parent=%d slices=%d target_qty=%d",
        parent.id,
        len(slices),
        parent.target_quantity,
    )

    return _build_state(parent.id, ExecutionStatus.ACTIVE.value, slices, entry)


async def pause_execution(
    parent_id: int,
    repo: ParentChildRepository,
) -> SchedulerState:
    """Pause an active parent execution — no new slices will be submitted."""
    entry = _registry.get(parent_id)
    if entry is None:
        raise ValueError(f"Parent {parent_id} is not active in the scheduler")
    if entry.is_paused:
        raise ValueError(f"Parent {parent_id} is already paused")

    entry.is_paused = True
    await repo.update_parent_status(parent_id, ExecutionStatus.PAUSED.value)

    logger.warning("Scheduler PAUSE parent=%d at slice_index=%d", parent_id, entry.next_slice_index)

    return _build_state(parent_id, ExecutionStatus.PAUSED.value, entry.schedule, entry)


async def resume_execution(
    parent_id: int,
    repo: ParentChildRepository,
) -> SchedulerState:
    """Resume a paused parent execution."""
    entry = _registry.get(parent_id)
    if entry is None:
        raise ValueError(f"Parent {parent_id} is not active in the scheduler")
    if not entry.is_paused:
        raise ValueError(f"Parent {parent_id} is not paused")

    entry.is_paused = False
    await repo.update_parent_status(parent_id, ExecutionStatus.ACTIVE.value)

    logger.warning("Scheduler RESUME parent=%d at slice_index=%d", parent_id, entry.next_slice_index)

    return _build_state(parent_id, ExecutionStatus.ACTIVE.value, entry.schedule, entry)


async def cancel_execution(
    parent_id: int,
    repo: ParentChildRepository,
) -> SchedulerState:
    """Cancel a parent execution. Pending child slices are marked CANCELLED."""
    entry = _registry.get(parent_id)
    if entry is None:
        raise ValueError(f"Parent {parent_id} is not active in the scheduler")

    # Cancel all pending child slices
    children = await repo.list_slices_for_parent(parent_id)
    cancelled_count = 0
    for child in children:
        if child.status in (SliceStatus.PENDING.value, SliceStatus.SENT.value):
            await repo.update_slice_status(child.id, SliceStatus.CANCELLED.value)
            cancelled_count += 1

    await repo.update_parent_status(parent_id, ExecutionStatus.CANCELLED.value)

    schedule = entry.schedule
    del _registry[parent_id]

    logger.warning(
        "Scheduler CANCEL parent=%d cancelled_slices=%d", parent_id, cancelled_count
    )

    state = _build_state(parent_id, ExecutionStatus.CANCELLED.value, schedule)
    state.slices_cancelled = cancelled_count
    state.is_running = False
    return state


async def get_execution_state(
    parent_id: int,
    repo: ParentChildRepository,
) -> SchedulerState:
    """Get current scheduler state for a parent execution."""
    parent = await repo.get_parent(parent_id)
    if parent is None:
        raise ValueError(f"Parent {parent_id} not found")

    entry = _registry.get(parent_id)
    children = await repo.list_slices_for_parent(parent_id)

    state = SchedulerState(
        parent_id=parent_id,
        status=parent.status,
        is_running=entry is not None and not entry.is_paused,
        current_slice_index=entry.next_slice_index if entry else 0,
        total_slices=len(children),
        target_quantity=parent.target_quantity,
        filled_quantity=parent.filled_quantity or 0,
        created_at=parent.created_at.isoformat() if parent.created_at else "",
        updated_at=parent.updated_at.isoformat() if parent.updated_at else "",
    )

    for child in children:
        if child.status == SliceStatus.SENT.value or child.status == SliceStatus.WORKING.value:
            state.slices_sent += 1
        elif child.status == SliceStatus.FILLED.value:
            state.slices_filled += 1
        elif child.status == SliceStatus.CANCELLED.value:
            state.slices_cancelled += 1

    return state


def list_active_parent_ids() -> list[int]:
    """Return IDs of all parents currently tracked by the scheduler."""
    return list(_registry.keys())


def reset_registry() -> None:
    """Clear the in-memory scheduler registry (for testing only)."""
    _registry.clear()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_state(
    parent_id: int,
    status: str,
    schedule: list[PlannedSlice],
    entry: _ActiveExecution | None = None,
) -> SchedulerState:
    now = _now_iso()
    return SchedulerState(
        parent_id=parent_id,
        status=status,
        is_running=entry is not None and not entry.is_paused,
        current_slice_index=entry.next_slice_index if entry else 0,
        total_slices=len(schedule),
        target_quantity=sum(s.planned_quantity for s in schedule),
        filled_quantity=0,
        created_at=now,
        updated_at=now,
    )

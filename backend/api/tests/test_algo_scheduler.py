"""Tests for algo_scheduler lifecycle and state tracking.

Covers: start → pause → resume → cancel transitions,
orphan-slice cleanup, error cases, and performance baselines.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# Path and environment setup
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("BYPASS_AUTH", "true")

from models.parent_child_orders import ExecutionStatus, SliceStatus
from services.benchmark_engine import PlannedSlice
from services.algo_scheduler import (
    SchedulerState,
    start_execution,
    pause_execution,
    resume_execution,
    cancel_execution,
    get_execution_state,
    list_active_parent_ids,
    reset_registry,
)


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fixed reference times
# ---------------------------------------------------------------------------

T0 = datetime(2026, 4, 3, 9, 30, tzinfo=timezone.utc)
T1 = datetime(2026, 4, 3, 16, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# In-memory mock repo (matches ParentChildRepository interface)
# ---------------------------------------------------------------------------

class _MockRepo:
    """Lightweight mock that stores parent/slice state in-memory."""

    def __init__(self, parent):
        self._parent = parent
        self._slices: list[SimpleNamespace] = []
        self._slice_id = 0

    async def get_parent(self, parent_id: int):
        if self._parent.id == parent_id:
            return self._parent
        return None

    async def update_parent_status(self, parent_id: int, status: str):
        if self._parent.id == parent_id:
            self._parent.status = status

    async def create_slices_bulk(self, slices: list[dict]):
        result = []
        for s in slices:
            self._slice_id += 1
            obj = SimpleNamespace(id=self._slice_id, **s)
            result.append(obj)
            self._slices.append(obj)
        return result

    async def list_slices_for_parent(self, parent_id: int):
        return [s for s in self._slices if s.parent_id == parent_id]

    async def update_slice_status(self, slice_id: int, status: str):
        for s in self._slices:
            if s.id == slice_id:
                s.status = status
                break

    async def update_parent_filled(self, parent_id: int, filled_quantity: int):
        if self._parent.id == parent_id:
            self._parent.filled_quantity = filled_quantity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_parent(pid: int = 1, qty: int = 1000) -> SimpleNamespace:
    return SimpleNamespace(
        id=pid,
        sequence=100,
        order_id="100",
        trader="test-trader",
        schedule_type="TWAP",
        target_quantity=qty,
        filled_quantity=0,
        start_time=T0,
        end_time=T1,
        status=ExecutionStatus.PENDING.value,
        created_at=T0,
        updated_at=T0,
    )


def _make_slices(n: int = 4, qty: int = 1000) -> list[PlannedSlice]:
    per = qty // n
    slices = []
    step = (T1 - T0) / n
    for i in range(n):
        slices.append(PlannedSlice(
            slice_index=i,
            planned_quantity=per + (1 if i < qty % n else 0),
            scheduled_start=T0 + step * i,
            scheduled_end=T0 + step * (i + 1),
            weight=1.0 / n,
        ))
    return slices


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure a fresh scheduler registry for every test."""
    reset_registry()
    yield
    reset_registry()


# ===================================================================
# Start lifecycle
# ===================================================================

class TestStartExecution:
    def test_basic_start(self):
        parent = _make_parent()
        slices = _make_slices(4)
        repo = _MockRepo(parent)

        state = _run(start_execution(parent, slices, repo))

        assert state.parent_id == 1
        assert state.status == ExecutionStatus.ACTIVE.value
        assert state.is_running is True
        assert state.total_slices == 4
        assert state.target_quantity == 1000

    def test_start_persists_child_slices(self):
        parent = _make_parent()
        slices = _make_slices(3)
        repo = _MockRepo(parent)

        _run(start_execution(parent, slices, repo))

        children = _run(repo.list_slices_for_parent(1))
        assert len(children) == 3
        for child in children:
            assert child.status == SliceStatus.PENDING.value

    def test_start_activates_parent(self):
        parent = _make_parent()
        repo = _MockRepo(parent)

        _run(start_execution(parent, _make_slices(2), repo))

        assert parent.status == ExecutionStatus.ACTIVE.value

    def test_start_registers_in_active_list(self):
        parent = _make_parent(pid=42)
        repo = _MockRepo(parent)

        _run(start_execution(parent, _make_slices(2), repo))

        assert 42 in list_active_parent_ids()

    def test_double_start_raises(self):
        parent = _make_parent()
        repo = _MockRepo(parent)

        _run(start_execution(parent, _make_slices(2), repo))

        with pytest.raises(ValueError, match="already registered"):
            _run(start_execution(parent, _make_slices(2), repo))


# ===================================================================
# Pause / Resume
# ===================================================================

class TestPauseResume:
    def test_pause_sets_paused_status(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(4), repo))

        state = _run(pause_execution(1, repo))

        assert state.status == ExecutionStatus.PAUSED.value
        assert state.is_running is False

    def test_pause_updates_parent_record(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(4), repo))

        _run(pause_execution(1, repo))

        assert parent.status == ExecutionStatus.PAUSED.value

    def test_double_pause_raises(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(2), repo))
        _run(pause_execution(1, repo))

        with pytest.raises(ValueError, match="already paused"):
            _run(pause_execution(1, repo))

    def test_resume_reactivates(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(4), repo))
        _run(pause_execution(1, repo))

        state = _run(resume_execution(1, repo))

        assert state.status == ExecutionStatus.ACTIVE.value
        assert state.is_running is True

    def test_resume_when_not_paused_raises(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(2), repo))

        with pytest.raises(ValueError, match="is not paused"):
            _run(resume_execution(1, repo))

    def test_pause_resume_cycle(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(4), repo))

        # Cycle: pause → resume → pause → resume
        for _ in range(2):
            s = _run(pause_execution(1, repo))
            assert s.is_running is False
            s = _run(resume_execution(1, repo))
            assert s.is_running is True


# ===================================================================
# Cancel
# ===================================================================

class TestCancel:
    def test_cancel_removes_from_registry(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(4), repo))

        _run(cancel_execution(1, repo))

        assert 1 not in list_active_parent_ids()

    def test_cancel_marks_pending_slices_cancelled(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(4), repo))

        state = _run(cancel_execution(1, repo))

        children = _run(repo.list_slices_for_parent(1))
        assert all(c.status == SliceStatus.CANCELLED.value for c in children)
        assert state.slices_cancelled == 4

    def test_cancel_preserves_filled_slices(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(4), repo))

        # Simulate: first 2 slices already filled
        children = _run(repo.list_slices_for_parent(1))
        children[0].status = SliceStatus.FILLED.value
        children[1].status = SliceStatus.FILLED.value

        state = _run(cancel_execution(1, repo))

        children = _run(repo.list_slices_for_parent(1))
        filled = [c for c in children if c.status == SliceStatus.FILLED.value]
        cancelled = [c for c in children if c.status == SliceStatus.CANCELLED.value]
        assert len(filled) == 2
        assert len(cancelled) == 2
        assert state.slices_cancelled == 2

    def test_cancel_sets_parent_cancelled(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(2), repo))

        state = _run(cancel_execution(1, repo))

        assert state.status == ExecutionStatus.CANCELLED.value
        assert parent.status == ExecutionStatus.CANCELLED.value

    def test_cancel_from_paused(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(2), repo))
        _run(pause_execution(1, repo))

        state = _run(cancel_execution(1, repo))

        assert state.status == ExecutionStatus.CANCELLED.value
        assert 1 not in list_active_parent_ids()

    def test_cancel_unknown_parent_raises(self):
        parent = _make_parent()
        repo = _MockRepo(parent)

        with pytest.raises(ValueError, match="not active"):
            _run(cancel_execution(999, repo))


# ===================================================================
# State observation
# ===================================================================

class TestGetExecutionState:
    def test_state_after_start(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(4), repo))

        state = _run(get_execution_state(1, repo))

        assert state.parent_id == 1
        assert state.status == ExecutionStatus.ACTIVE.value
        assert state.is_running is True
        assert state.total_slices == 4

    def test_state_after_pause(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(4), repo))
        _run(pause_execution(1, repo))

        state = _run(get_execution_state(1, repo))

        assert state.status == ExecutionStatus.PAUSED.value
        assert state.is_running is False

    def test_state_unknown_parent_raises(self):
        parent = _make_parent()
        repo = _MockRepo(parent)

        with pytest.raises(ValueError, match="not found"):
            _run(get_execution_state(999, repo))

    def test_to_dict_keys(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(2), repo))

        state = _run(get_execution_state(1, repo))
        d = state.to_dict()

        expected_keys = {
            "parentId", "status", "isRunning", "currentSliceIndex",
            "totalSlices", "slicesSent", "slicesFilled", "slicesCancelled",
            "targetQuantity", "filledQuantity", "createdAt", "updatedAt",
        }
        assert set(d.keys()) == expected_keys

    def test_state_counts_slice_statuses(self):
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(4), repo))

        # Simulate mixed statuses
        children = _run(repo.list_slices_for_parent(1))
        children[0].status = SliceStatus.FILLED.value
        children[1].status = SliceStatus.SENT.value
        children[2].status = SliceStatus.WORKING.value
        # children[3] stays PENDING

        state = _run(get_execution_state(1, repo))

        assert state.slices_filled == 1
        assert state.slices_sent == 2  # SENT + WORKING
        assert state.slices_cancelled == 0


# ===================================================================
# Registry helpers
# ===================================================================

class TestRegistryHelpers:
    def test_list_active_parent_ids(self):
        for pid in [10, 20, 30]:
            p = _make_parent(pid=pid)
            _run(start_execution(p, _make_slices(2), _MockRepo(p)))

        ids = list_active_parent_ids()
        assert set(ids) == {10, 20, 30}

    def test_reset_registry_clears_all(self):
        for pid in [1, 2, 3]:
            p = _make_parent(pid=pid)
            _run(start_execution(p, _make_slices(2), _MockRepo(p)))

        reset_registry()

        assert list_active_parent_ids() == []


# ===================================================================
# No-orphan-slices checkpoint
# ===================================================================

class TestNoOrphanSlices:
    def test_cancel_cleans_all_pending(self):
        """Cancelling a parent must not leave any slice in PENDING state."""
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(6), repo))

        _run(cancel_execution(1, repo))

        children = _run(repo.list_slices_for_parent(1))
        pending = [c for c in children if c.status == SliceStatus.PENDING.value]
        assert pending == [], "No orphan PENDING slices after cancel"

    def test_cancel_cleans_sent_slices(self):
        """SENT slices should also be cancelled (not orphaned)."""
        parent = _make_parent()
        repo = _MockRepo(parent)
        _run(start_execution(parent, _make_slices(4), repo))

        children = _run(repo.list_slices_for_parent(1))
        children[0].status = SliceStatus.SENT.value
        children[1].status = SliceStatus.SENT.value

        _run(cancel_execution(1, repo))

        children = _run(repo.list_slices_for_parent(1))
        sent = [c for c in children if c.status == SliceStatus.SENT.value]
        assert sent == [], "No orphan SENT slices after cancel"


# ===================================================================
# Performance baselines
# ===================================================================

class TestPerformance:
    def test_lifecycle_under_50ms(self):
        """Full start→pause→resume→cancel cycle should be fast."""
        parent = _make_parent()
        repo = _MockRepo(parent)
        slices = _make_slices(100, qty=100_000)

        t0 = time.perf_counter()

        _run(start_execution(parent, slices, repo))
        _run(pause_execution(1, repo))
        _run(resume_execution(1, repo))
        _run(cancel_execution(1, repo))

        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 50, f"Lifecycle took {elapsed_ms:.1f}ms (limit 50ms)"

    def test_many_parents_under_200ms(self):
        """Registering 50 parents and listing them stays fast."""
        t0 = time.perf_counter()

        for pid in range(1, 51):
            p = _make_parent(pid=pid)
            _run(start_execution(p, _make_slices(10, qty=1000), _MockRepo(p)))

        ids = list_active_parent_ids()

        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert len(ids) == 50
        assert elapsed_ms < 200, f"50-parent registration took {elapsed_ms:.1f}ms (limit 200ms)"

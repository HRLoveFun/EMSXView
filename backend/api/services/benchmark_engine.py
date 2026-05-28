"""Benchmark scheduling engine for TWAP, VWAP, and POV execution strategies.

Computes deterministic child-slice schedules from a parent execution
objective, a scheduling window, and an optional market volume profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from models.parent_child_orders import ScheduleType


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlannedSlice:
    """One planned child order produced by the scheduler."""

    slice_index: int
    planned_quantity: int
    scheduled_start: datetime
    scheduled_end: datetime
    weight: float  # 0..1, share of parent objective allocated to this slice


@dataclass(frozen=True)
class VolumeProfile:
    """Expected market volume distribution across equal-width time buckets."""

    buckets: Sequence[float]  # expected volume per bucket (absolute or relative)

    @property
    def total(self) -> float:
        return sum(self.buckets)

    def weights(self) -> list[float]:
        total = self.total
        if total <= 0:
            n = len(self.buckets)
            return [1.0 / n] * n if n else []
        return [v / total for v in self.buckets]


@dataclass(frozen=True)
class ScheduleRequest:
    """Input for the scheduling engine."""

    schedule_type: ScheduleType
    target_quantity: int
    start_time: datetime
    end_time: datetime
    num_slices: int
    participation_rate: float | None = None  # required for POV
    volume_profile: VolumeProfile | None = None  # required for VWAP/POV


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_schedule(request: ScheduleRequest) -> list[PlannedSlice]:
    """Produce a deterministic child-slice schedule from a parent objective.

    Raises ``ValueError`` for invalid inputs or unsupported schedule types.
    """
    if request.target_quantity <= 0:
        raise ValueError("target_quantity must be positive")
    if request.num_slices <= 0:
        raise ValueError("num_slices must be positive")
    if request.end_time <= request.start_time:
        raise ValueError("end_time must be after start_time")

    dispatch = {
        ScheduleType.TWAP: _compute_twap,
        ScheduleType.VWAP: _compute_vwap,
        ScheduleType.POV: _compute_pov,
    }
    handler = dispatch.get(request.schedule_type)
    if handler is None:
        raise ValueError(
            f"Unsupported schedule type for benchmark engine: {request.schedule_type}"
        )
    return handler(request)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _time_buckets(
    start: datetime, end: datetime, n: int
) -> list[tuple[datetime, datetime]]:
    """Split [start, end) into *n* equal-width time intervals."""
    total_secs = (end - start).total_seconds()
    bucket_secs = total_secs / n
    buckets: list[tuple[datetime, datetime]] = []
    for i in range(n):
        b_start = start + timedelta(seconds=bucket_secs * i)
        b_end = start + timedelta(seconds=bucket_secs * (i + 1))
        buckets.append((b_start, b_end))
    return buckets


def _distribute_quantity(total: int, weights: list[float]) -> list[int]:
    """Distribute *total* across *weights* with largest-remainder rounding.

    Guarantees ``sum(result) == total`` and each element >= 0.
    """
    raw = [total * w for w in weights]
    floored = [int(r) for r in raw]
    remainders = [r - f for r, f in zip(raw, floored)]
    shortfall = total - sum(floored)
    # Allocate extra units to the buckets with the largest fractional remainders
    indices = sorted(range(len(remainders)), key=lambda i: remainders[i], reverse=True)
    for i in range(shortfall):
        floored[indices[i]] += 1
    return floored


def _build_slices(
    buckets: list[tuple[datetime, datetime]],
    quantities: list[int],
    weights: list[float],
) -> list[PlannedSlice]:
    return [
        PlannedSlice(
            slice_index=i,
            planned_quantity=qty,
            scheduled_start=b_start,
            scheduled_end=b_end,
            weight=w,
        )
        for i, ((b_start, b_end), qty, w) in enumerate(
            zip(buckets, quantities, weights)
        )
    ]


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------

def _compute_twap(req: ScheduleRequest) -> list[PlannedSlice]:
    """TWAP: uniform time-sliced distribution."""
    buckets = _time_buckets(req.start_time, req.end_time, req.num_slices)
    weights = [1.0 / req.num_slices] * req.num_slices
    quantities = _distribute_quantity(req.target_quantity, weights)
    return _build_slices(buckets, quantities, weights)


def _compute_vwap(req: ScheduleRequest) -> list[PlannedSlice]:
    """VWAP: volume-profiled distribution.

    Falls back to TWAP when no matching volume profile is provided.
    """
    if (
        req.volume_profile is None
        or len(req.volume_profile.buckets) != req.num_slices
    ):
        return _compute_twap(req)

    buckets = _time_buckets(req.start_time, req.end_time, req.num_slices)
    weights = req.volume_profile.weights()
    quantities = _distribute_quantity(req.target_quantity, weights)
    return _build_slices(buckets, quantities, weights)


def _compute_pov(req: ScheduleRequest) -> list[PlannedSlice]:
    """POV: participation-rate distribution capped at target_quantity.

    Each slice's quantity is proportional to expected bucket volume at the
    given participation rate. The total is capped at *target_quantity*.
    """
    if req.participation_rate is None or req.participation_rate <= 0:
        raise ValueError("POV requires a positive participation_rate")
    if (
        req.volume_profile is None
        or len(req.volume_profile.buckets) != req.num_slices
    ):
        raise ValueError("POV requires a volume_profile with len == num_slices")

    buckets = _time_buckets(req.start_time, req.end_time, req.num_slices)

    # Maximum quantity the market can absorb at this participation rate
    max_participatable = int(round(req.participation_rate * req.volume_profile.total))
    achievable = min(req.target_quantity, max(1, max_participatable))

    weights = req.volume_profile.weights()
    quantities = _distribute_quantity(achievable, weights)
    return _build_slices(buckets, quantities, weights)

"""Golden tests for the benchmark scheduling engine.

Deterministic inputs produce exact outputs — any change to
schedule distribution logic will surface here immediately.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

# ---------------------------------------------------------------------------
# Path and environment setup
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("BYPASS_AUTH", "true")

from models.parent_child_orders import ScheduleType
from services.benchmark_engine import (
    PlannedSlice,
    ScheduleRequest,
    VolumeProfile,
    compute_schedule,
    _distribute_quantity,
    _time_buckets,
)

# Fixed reference times for deterministic assertions
T0 = datetime(2026, 4, 3, 9, 30, tzinfo=timezone.utc)
T1 = datetime(2026, 4, 3, 16, 0, tzinfo=timezone.utc)  # 6 h 30 min later


# ===================================================================
# Helper unit tests
# ===================================================================


class TestDistributeQuantity:
    def test_even_split(self):
        result = _distribute_quantity(100, [0.25, 0.25, 0.25, 0.25])
        assert result == [25, 25, 25, 25]
        assert sum(result) == 100

    def test_odd_split_largest_remainder(self):
        result = _distribute_quantity(10, [1 / 3, 1 / 3, 1 / 3])
        assert sum(result) == 10
        assert result == [4, 3, 3]

    def test_single_bucket(self):
        result = _distribute_quantity(100, [1.0])
        assert result == [100]

    def test_zero_weight_bucket(self):
        result = _distribute_quantity(100, [0.0, 1.0])
        assert result == [0, 100]

    def test_many_buckets_small_quantity(self):
        result = _distribute_quantity(3, [0.2, 0.2, 0.2, 0.2, 0.2])
        assert sum(result) == 3
        assert all(q >= 0 for q in result)


class TestTimeBuckets:
    def test_basic_split(self):
        end = T0 + timedelta(hours=2)
        buckets = _time_buckets(T0, end, 4)
        assert len(buckets) == 4
        assert buckets[0][0] == T0
        assert buckets[-1][1] == end
        for start, end_t in buckets:
            assert (end_t - start).total_seconds() == 1800

    def test_contiguous(self):
        buckets = _time_buckets(T0, T0 + timedelta(hours=6), 12)
        for i in range(len(buckets) - 1):
            assert buckets[i][1] == buckets[i + 1][0]


# ===================================================================
# TWAP golden tests
# ===================================================================


class TestTWAP:
    def test_uniform_4_slices(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.TWAP,
            target_quantity=1000,
            start_time=T0,
            end_time=T0 + timedelta(hours=4),
            num_slices=4,
        )
        slices = compute_schedule(req)
        assert len(slices) == 4
        assert all(s.planned_quantity == 250 for s in slices)
        assert sum(s.planned_quantity for s in slices) == 1000

    def test_non_divisible(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.TWAP,
            target_quantity=100,
            start_time=T0,
            end_time=T0 + timedelta(hours=3),
            num_slices=3,
        )
        slices = compute_schedule(req)
        assert len(slices) == 3
        assert sum(s.planned_quantity for s in slices) == 100
        assert slices[0].planned_quantity == 34
        assert slices[1].planned_quantity == 33
        assert slices[2].planned_quantity == 33

    def test_time_windows_contiguous(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.TWAP,
            target_quantity=100,
            start_time=T0,
            end_time=T0 + timedelta(hours=2),
            num_slices=4,
        )
        slices = compute_schedule(req)
        assert slices[0].scheduled_start == T0
        assert slices[-1].scheduled_end == T0 + timedelta(hours=2)
        for i in range(len(slices) - 1):
            assert slices[i].scheduled_end == slices[i + 1].scheduled_start

    def test_weights_uniform(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.TWAP,
            target_quantity=100,
            start_time=T0,
            end_time=T0 + timedelta(hours=2),
            num_slices=4,
        )
        slices = compute_schedule(req)
        for s in slices:
            assert s.weight == pytest.approx(0.25)


# ===================================================================
# VWAP golden tests
# ===================================================================


class TestVWAP:
    def test_with_volume_profile(self):
        profile = VolumeProfile(buckets=[100, 200, 200, 100])
        req = ScheduleRequest(
            schedule_type=ScheduleType.VWAP,
            target_quantity=600,
            start_time=T0,
            end_time=T0 + timedelta(hours=4),
            num_slices=4,
            volume_profile=profile,
        )
        slices = compute_schedule(req)
        assert len(slices) == 4
        assert sum(s.planned_quantity for s in slices) == 600
        assert slices[0].planned_quantity == 100
        assert slices[1].planned_quantity == 200
        assert slices[2].planned_quantity == 200
        assert slices[3].planned_quantity == 100

    def test_falls_back_to_twap_without_profile(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.VWAP,
            target_quantity=400,
            start_time=T0,
            end_time=T0 + timedelta(hours=4),
            num_slices=4,
        )
        slices = compute_schedule(req)
        assert all(s.planned_quantity == 100 for s in slices)

    def test_mismatched_profile_falls_back(self):
        profile = VolumeProfile(buckets=[100, 200])
        req = ScheduleRequest(
            schedule_type=ScheduleType.VWAP,
            target_quantity=400,
            start_time=T0,
            end_time=T0 + timedelta(hours=4),
            num_slices=4,
            volume_profile=profile,
        )
        slices = compute_schedule(req)
        assert all(s.planned_quantity == 100 for s in slices)

    def test_asymmetric_profile(self):
        profile = VolumeProfile(buckets=[500, 300, 100, 100])
        req = ScheduleRequest(
            schedule_type=ScheduleType.VWAP,
            target_quantity=1000,
            start_time=T0,
            end_time=T0 + timedelta(hours=4),
            num_slices=4,
            volume_profile=profile,
        )
        slices = compute_schedule(req)
        assert sum(s.planned_quantity for s in slices) == 1000
        assert slices[0].planned_quantity == 500
        assert slices[1].planned_quantity == 300
        assert slices[2].planned_quantity == 100
        assert slices[3].planned_quantity == 100


# ===================================================================
# POV golden tests
# ===================================================================


class TestPOV:
    def test_participation_rate(self):
        profile = VolumeProfile(buckets=[1000, 2000, 2000, 1000])
        req = ScheduleRequest(
            schedule_type=ScheduleType.POV,
            target_quantity=10000,
            start_time=T0,
            end_time=T0 + timedelta(hours=4),
            num_slices=4,
            participation_rate=0.10,
            volume_profile=profile,
        )
        slices = compute_schedule(req)
        assert len(slices) == 4
        # 10% of 6000 total volume = 600
        assert sum(s.planned_quantity for s in slices) == 600
        assert slices[0].planned_quantity == 100
        assert slices[1].planned_quantity == 200
        assert slices[2].planned_quantity == 200
        assert slices[3].planned_quantity == 100

    def test_target_caps_participation(self):
        profile = VolumeProfile(buckets=[10000, 10000])
        req = ScheduleRequest(
            schedule_type=ScheduleType.POV,
            target_quantity=500,
            start_time=T0,
            end_time=T0 + timedelta(hours=2),
            num_slices=2,
            participation_rate=0.50,
            volume_profile=profile,
        )
        slices = compute_schedule(req)
        # 50% of 20000 = 10000, but capped at target 500
        assert sum(s.planned_quantity for s in slices) == 500

    def test_missing_rate_raises(self):
        profile = VolumeProfile(buckets=[100])
        req = ScheduleRequest(
            schedule_type=ScheduleType.POV,
            target_quantity=100,
            start_time=T0,
            end_time=T0 + timedelta(hours=1),
            num_slices=1,
            volume_profile=profile,
        )
        with pytest.raises(ValueError, match="participation_rate"):
            compute_schedule(req)

    def test_missing_profile_raises(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.POV,
            target_quantity=100,
            start_time=T0,
            end_time=T0 + timedelta(hours=1),
            num_slices=1,
            participation_rate=0.10,
        )
        with pytest.raises(ValueError, match="volume_profile"):
            compute_schedule(req)


# ===================================================================
# Edge cases and validation
# ===================================================================


class TestEdgeCases:
    def test_single_slice(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.TWAP,
            target_quantity=1000,
            start_time=T0,
            end_time=T0 + timedelta(hours=1),
            num_slices=1,
        )
        slices = compute_schedule(req)
        assert len(slices) == 1
        assert slices[0].planned_quantity == 1000

    def test_zero_quantity_raises(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.TWAP,
            target_quantity=0,
            start_time=T0,
            end_time=T0 + timedelta(hours=1),
            num_slices=1,
        )
        with pytest.raises(ValueError, match="target_quantity"):
            compute_schedule(req)

    def test_reversed_time_raises(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.TWAP,
            target_quantity=100,
            start_time=T1,
            end_time=T0,
            num_slices=1,
        )
        with pytest.raises(ValueError, match="end_time"):
            compute_schedule(req)

    def test_unsupported_type_raises(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.IS,
            target_quantity=100,
            start_time=T0,
            end_time=T1,
            num_slices=1,
        )
        with pytest.raises(ValueError, match="Unsupported"):
            compute_schedule(req)

    def test_many_slices_sparse_distribution(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.TWAP,
            target_quantity=7,
            start_time=T0,
            end_time=T0 + timedelta(hours=10),
            num_slices=100,
        )
        slices = compute_schedule(req)
        assert len(slices) == 100
        assert sum(s.planned_quantity for s in slices) == 7
        non_zero = [s for s in slices if s.planned_quantity > 0]
        assert len(non_zero) == 7

    def test_slice_indices_sequential(self):
        req = ScheduleRequest(
            schedule_type=ScheduleType.TWAP,
            target_quantity=100,
            start_time=T0,
            end_time=T0 + timedelta(hours=5),
            num_slices=5,
        )
        slices = compute_schedule(req)
        assert [s.slice_index for s in slices] == list(range(5))


# ===================================================================
# Performance baseline
# ===================================================================


class TestPerformance:
    def test_large_schedule_under_100ms(self):
        """Generating a 1000-slice schedule must complete in < 100 ms."""
        profile = VolumeProfile(buckets=[float(i % 50 + 10) for i in range(1000)])
        req = ScheduleRequest(
            schedule_type=ScheduleType.VWAP,
            target_quantity=500_000,
            start_time=T0,
            end_time=T0 + timedelta(hours=6, minutes=30),
            num_slices=1000,
            volume_profile=profile,
        )
        start = time.perf_counter()
        slices = compute_schedule(req)
        elapsed = time.perf_counter() - start
        assert len(slices) == 1000
        assert sum(s.planned_quantity for s in slices) == 500_000
        assert elapsed < 0.1, f"Schedule generation took {elapsed:.3f}s (limit 0.1s)"

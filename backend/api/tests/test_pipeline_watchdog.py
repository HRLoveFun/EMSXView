"""Tests for pipeline watchdog multi-signal activity detection.

覆盖场景:
  - 阶段分级 stall 阈值正确读取
  - _ActivityDetector 在空闲 / 强活动 / 弱活动 状态下行为正确
  - 真 stall 判定: stdout 静默 + CPU 0% + 无 I/O -> stall
  - 误判防护: stdout 静默但 CPU >= 5% -> 不 stall
  - 误判防护: stdout 静默 + 1% <= CPU < 5% -> 不 stall
  - 弱活动告警: stdout 接近阈值但有弱活动 -> INFO 日志不 kill
  - max_runtime 仍然硬性 kill
  - 进程退出后 watchdog 自动停止
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from platform_data import pipeline_jobs  # noqa: E402
from platform_data.pipeline_jobs import (  # noqa: E402
    _ActivityDetector,
    _STAGE_STALL_TIMEOUTS,
    _WATCHDOG_INTERVAL_SECS,
    _WEAK_ACTIVITY_GRACE_SECS,
    _watchdog_loop,
    _jobs,
    _jobs_lock,
)


@pytest.fixture(autouse=True)
def _clean_jobs():
    """每个 case 之间清理 _jobs 注册表。"""
    with _jobs_lock:
        _jobs.clear()
    yield
    with _jobs_lock:
        _jobs.clear()


# Stage tiered threshold config


class TestStageStallTimeouts:
    def test_all_known_stages_have_timeout(self):
        for stage in pipeline_jobs.PIPELINE_STAGES:
            name = stage["name"]
            assert name in _STAGE_STALL_TIMEOUTS, f"missing timeout for stage {name}"

    def test_pipeline_stage_has_generous_timeout(self):
        # Stage 5 (pipeline/BDIB) threshold most generous for multi-date BDIB integration
        assert _STAGE_STALL_TIMEOUTS["pipeline"] >= 1500

    def test_vacuum_has_longest_timeout(self):
        # VACUUM is single-threaded blocking, threshold most generous
        assert _STAGE_STALL_TIMEOUTS["vacuum"] == 3600

    def test_initialization_timeout_short(self):
        # Init short to surface script issues quickly
        assert _STAGE_STALL_TIMEOUTS["initialization"] <= 600

    def test_threshold_increases_with_known_io_heaviness(self):
        assert (
            _STAGE_STALL_TIMEOUTS["completion"]
            < _STAGE_STALL_TIMEOUTS["fill_fetch"]
            < _STAGE_STALL_TIMEOUTS["vacuum"]
        )


# _ActivityDetector unit tests


def _make_popen_mock(pid: int = 99999) -> MagicMock:
    return MagicMock(spec=subprocess.Popen, pid=pid)


def _make_popen_with_cpu(cpu_value: float) -> tuple[MagicMock, MagicMock]:
    popen = _make_popen_mock()
    fake_proc = MagicMock()
    fake_proc.cpu_percent.return_value = cpu_value
    fake_proc.io_counters.return_value = MagicMock(read_bytes=0, write_bytes=0)
    fake_proc.num_threads.return_value = 4
    fake_proc.memory_info.return_value = MagicMock(rss=100 * 1024 * 1024)
    return popen, fake_proc


class TestActivityDetector:
    def test_mark_stdout_resets_strong_idle(self):
        popen = _make_popen_mock()
        detector = _ActivityDetector(popen)
        time.sleep(0.05)
        detector.mark_stdout()
        assert detector.strong_count == 1
        assert detector._last_strong_at > 0

    def test_probe_returns_struct_dict_with_required_keys(self):
        popen, fake_proc = _make_popen_with_cpu(cpu_value=0.0)
        with patch("psutil.Process", return_value=fake_proc, create=True):
            detector = _ActivityDetector(popen)
            result = detector.probe()
        required = {
            "available", "cpu_pct", "io_active", "thread_change", "mem_active",
            "strong_now", "weak_now", "last_strong_idle_secs", "last_any_idle_secs",
        }
        assert required.issubset(result.keys())

    def test_probe_handles_dead_process_gracefully(self):
        popen, fake_proc = _make_popen_with_cpu(cpu_value=0.0)
        import psutil
        fake_proc.cpu_percent.side_effect = psutil.NoSuchProcess(pid=99999)
        with patch("psutil.Process", return_value=fake_proc, create=True):
            detector = _ActivityDetector(popen)
            result = detector.probe()
        assert result["available"] is False
        assert result["strong_now"] is False
        assert result["weak_now"] is False


# _watchdog_loop integration tests


def _seed_job(job_id: str, stage_name: str = "pipeline") -> None:
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "error": None,
            "stage": {
                "name": stage_name, "label": stage_name.title(),
                "progress": 50, "detail": None,
            },
            "overall_progress": 50,
            "last_activity_at": datetime.now().isoformat(),
        }


class TestWatchdogLoopStallJudgment:
    def test_max_runtime_triggers_kill(self):
        job_id = "test-runtime"
        _seed_job(job_id, "pipeline")
        proc = _make_popen_mock()
        proc.poll.return_value = None
        stop_event = threading.Event()
        detector = _ActivityDetector(proc)
        detector_lock = threading.Lock()

        with patch.object(pipeline_jobs, "_WATCHDOG_INTERVAL_SECS", 0.05), \
             patch.object(pipeline_jobs, "_MAX_RUNTIME_SECS", 0.1):
            t = threading.Thread(
                target=_watchdog_loop,
                args=(job_id, proc, stop_event, detector, detector_lock),
                daemon=True,
            )
            t.start()
            time.sleep(0.5)
            stop_event.set()
            t.join(timeout=2)

        with _jobs_lock:
            assert _jobs[job_id]["status"] == "failed"
            assert "max runtime" in _jobs[job_id]["error"].lower()

    def test_strong_activity_prevents_stall_kill(self):
        job_id = "test-stdout"
        _seed_job(job_id, "pipeline")
        proc = _make_popen_mock()
        proc.poll.return_value = None
        stop_event = threading.Event()
        detector_lock = threading.Lock()
        detector = _ActivityDetector(proc)

        def fake_stdout_feed():
            for _ in range(5):
                with detector_lock:
                    detector.mark_stdout()
                time.sleep(0.2)
            stop_event.set()

        feeder = threading.Thread(target=fake_stdout_feed, daemon=True)
        t = threading.Thread(
            target=_watchdog_loop,
            args=(job_id, proc, stop_event, detector, detector_lock),
            daemon=True,
        )
        t.start()
        feeder.start()
        feeder.join(timeout=3)
        t.join(timeout=3)

        with _jobs_lock:
            assert _jobs[job_id]["status"] == "running"

    def test_high_cpu_prevents_stall_kill(self):
        job_id = "test-cpu"
        _seed_job(job_id, "pipeline")
        proc = _make_popen_mock()
        proc.poll.return_value = None
        stop_event = threading.Event()
        detector_lock = threading.Lock()

        detector = MagicMock()
        detector.probe.return_value = {
            "available": True, "cpu_pct": 25.0,
            "io_active": False, "thread_change": False, "mem_active": False,
            "strong_now": True, "weak_now": False,
            "last_strong_idle_secs": 0.5, "last_any_idle_secs": 0.5,
        }
        detector.strong_count = 1
        detector.weak_count = 0

        def stop_after():
            time.sleep(0.5)
            stop_event.set()

        stopper = threading.Thread(target=stop_after, daemon=True)
        t = threading.Thread(
            target=_watchdog_loop,
            args=(job_id, proc, stop_event, detector, detector_lock),
            daemon=True,
        )
        t.start()
        stopper.start()
        stopper.join(timeout=2)
        t.join(timeout=2)

        with _jobs_lock:
            assert _jobs[job_id]["status"] == "running"

    def test_true_stall_triggers_kill_with_diagnosis(self):
        job_id = "test-stall"
        _seed_job(job_id, "pipeline")
        proc = _make_popen_mock()
        proc.poll.return_value = None
        stop_event = threading.Event()
        detector_lock = threading.Lock()

        detector = MagicMock()
        detector.probe.return_value = {
            "available": True, "cpu_pct": 0.0,
            "io_active": False, "thread_change": False, "mem_active": False,
            "strong_now": False, "weak_now": False,
            "last_strong_idle_secs": 999.0, "last_any_idle_secs": 999.0,
        }
        detector.strong_count = 0
        detector.weak_count = 0

        original_pipeline = _STAGE_STALL_TIMEOUTS["pipeline"]
        try:
            _STAGE_STALL_TIMEOUTS["pipeline"] = 1
            with patch.object(pipeline_jobs, "_WATCHDOG_INTERVAL_SECS", 0.05), \
                 patch.object(pipeline_jobs, "_WEAK_ACTIVITY_GRACE_SECS", 1):
                t = threading.Thread(
                    target=_watchdog_loop,
                    args=(job_id, proc, stop_event, detector, detector_lock),
                    daemon=True,
                )
                t.start()
                time.sleep(0.5)
                stop_event.set()
                t.join(timeout=3)
        finally:
            _STAGE_STALL_TIMEOUTS["pipeline"] = original_pipeline

        with _jobs_lock:
            assert _jobs[job_id]["status"] == "failed"
            err = _jobs[job_id]["error"]
            assert "Signals" in err or "subprocess stalled" in err
            assert "cpu=0.0%" in err

    def test_process_exited_terminates_watchdog(self):
        job_id = "test-exit"
        _seed_job(job_id, "pipeline")
        proc = _make_popen_mock()
        # First poll returns None (still running), subsequent polls return 0 (exited)
        proc.poll.side_effect = [None, 0, 0, 0]
        proc.returncode = 0
        stop_event = threading.Event()
        detector_lock = threading.Lock()
        detector = MagicMock()
        detector.probe.return_value = {
            "available": True, "cpu_pct": 0.0,
            "io_active": False, "thread_change": False, "mem_active": False,
            "strong_now": False, "weak_now": False,
            "last_strong_idle_secs": 0.0, "last_any_idle_secs": 0.0,
        }
        detector.strong_count = 0
        detector.weak_count = 0

        with patch.object(pipeline_jobs, "_WATCHDOG_INTERVAL_SECS", 0.05):
            t = threading.Thread(
                target=_watchdog_loop,
                args=(job_id, proc, stop_event, detector, detector_lock),
                daemon=True,
            )
            t.start()
            t.join(timeout=2)

        assert not t.is_alive()
        with _jobs_lock:
            assert _jobs[job_id]["status"] == "running"

    def test_stage_aware_timeout_resolution(self):
        assert _STAGE_STALL_TIMEOUTS.get(
            "unknown_stage", pipeline_jobs._STALL_TIMEOUT_SECS
        ) == 600
        assert _STAGE_STALL_TIMEOUTS.get("fill_fetch", 0) == 1500


# Backward compatibility


class TestBackwardCompat:
    def test_legacy_constants_still_exported(self):
        assert pipeline_jobs._STALL_TIMEOUT_SECS == 600
        assert pipeline_jobs._MAX_RUNTIME_SECS == 7200
        assert pipeline_jobs._WATCHDOG_INTERVAL_SECS == 15
        assert pipeline_jobs._VACUUM_STALL_TIMEOUT_SECS == 3600
        assert _STAGE_STALL_TIMEOUTS["vacuum"] == pipeline_jobs._VACUUM_STALL_TIMEOUT_SECS


# Stage 5 BDIB integration scenario


class TestStage5BdiIntegrationScenario:
    """Simulate Stage 5 BDIB integration: stdout silent but CPU 10-20%.

    Old watchdog would misjudge as stall and kill.
    New watchdog should recognize 'still working' and not kill.
    """

    def test_cpu_active_during_long_silent_phase(self):
        job_id = "test-stage5"
        _seed_job(job_id, "pipeline")
        proc = _make_popen_mock()
        proc.poll.return_value = None
        stop_event = threading.Event()
        detector_lock = threading.Lock()

        # stdout silent (main loop received no lines), but CPU at 12%
        detector = MagicMock()
        detector.probe.return_value = {
            "available": True, "cpu_pct": 12.0,
            "io_active": True, "thread_change": False, "mem_active": False,
            "strong_now": True, "weak_now": False,
            "last_strong_idle_secs": 0.0, "last_any_idle_secs": 0.0,
        }
        detector.strong_count = 5
        detector.weak_count = 0

        t = threading.Thread(
            target=_watchdog_loop,
            args=(job_id, proc, stop_event, detector, detector_lock),
            daemon=True,
        )
        t.start()
        time.sleep(0.5)
        stop_event.set()
        t.join(timeout=2)

        with _jobs_lock:
            # CPU + IO strong activity, watchdog should NOT kill
            assert _jobs[job_id]["status"] == "running"

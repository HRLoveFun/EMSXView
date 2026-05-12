"""Shared process-lifetime pipeline job registry + subprocess runner.

Originally lived inside `routers/costview.py`. Extracted so that the new
DatabaseView router (`/api/db/update`, `/api/db/update-status/{job_id}`) and
the legacy CostView aliases (`/api/tca/trigger-update`,
`/api/tca/update-status/{job_id}`) share a single in-memory registry — one
active pipeline at a time, reported consistently to both frontends.

Features
--------
- **Watchdog** — monitors subprocess for stall (no activity for > 5 min)
  and total runtime (max 2 h), kills unresponsive processes automatically.
- **Lock file** — ``.pipeline.lock`` in the project root prevents concurrent
  pipeline processes across backend restarts.
"""

from __future__ import annotations

import gc
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # .../EMSX
_COSTVIEW_ROOT = _PROJECT_ROOT / "CostView"
_LOCK_FILE = _PROJECT_ROOT / ".pipeline.lock"

# ── Watchdog / safety thresholds ────────────────────────────────────────────

_WATCHDOG_INTERVAL_SECS = 15          # check every 15 s
_STALL_TIMEOUT_SECS    = 600           # 10 min without activity → stalled (must be > per_fetch_timeout_secs in fill_fetch.py)
_MAX_RUNTIME_SECS      = 7200          # 2 h total → timeout
_LOCK_STALE_AGE_SECS  = 14400         # 4 h → lock file considered stale even if PID is alive
_SUBPROCESS_STARTUP_TIMEOUT_SECS = 120  # 2 min without ANY stdout → assume startup failed
# Memory warning threshold (GB) — watchdog logs warning when subprocess exceeds this
_MEM_WARN_GB = 12.0


# ── Stage definitions (must match daily_update.py STAGE_MARKERS) ──────────────

PIPELINE_STAGES = [
    {"name": "initialization", "label": "Initialization"},
    {"name": "fill_fetch",     "label": "Fill Fetch"},
    {"name": "processing",     "label": "Processing"},
    {"name": "completion",     "label": "Completion"},
]

_STAGE_WEIGHTS = {
    "initialization": 10,
    "fill_fetch":     35,
    "processing":     45,
    "completion":     10,
}

_STAGE_PREFIX = "[STAGE]"


def _compute_progress(stage_name: str, stage_pct: int) -> int:
    stage_names = [stage["name"] for stage in PIPELINE_STAGES]
    try:
        current_index = stage_names.index(stage_name)
    except ValueError:
        current_index = 0
    prior = sum(
        _STAGE_WEIGHTS.get(PIPELINE_STAGES[i]["name"], 0)
        for i in range(current_index)
    )
    return min(100, prior + int(_STAGE_WEIGHTS.get(stage_name, 0) * stage_pct / 100))


def _mark_job_activity(job_id: str) -> None:
    if job_id in _jobs:
        _jobs[job_id]["last_activity_at"] = datetime.now().isoformat()


def _parse_stage_line(line: str):
    """Parse a ``[STAGE]`` marker line.

    Expected format::

        [STAGE] <stage_name> <progress_pct> [<freeform detail text>]

    Returns ``(name, pct, detail)`` where *detail* is the rest of the line
    after the percentage (or ``None`` if not present).
    """
    line = line.strip()
    if not line.startswith(_STAGE_PREFIX):
        return None
    rest = line[len(_STAGE_PREFIX):].strip()
    parts = rest.split()
    if len(parts) >= 2:
        detail = " ".join(parts[2:]) if len(parts) > 2 else None
        try:
            pct = min(100, max(0, int(parts[1])))
        except ValueError:
            pct = 0
        return parts[0], pct, detail
    if len(parts) == 1:
        return parts[0], 0, None
    return None


# ── Lock file helpers ────────────────────────────────────────────────────────

def _write_lock(job_id: str) -> Path:
    """Write pipeline lock file and return its path."""
    payload = {
        "pid": os.getpid(),
        "job_id": job_id,
        "started_at": datetime.now().isoformat(),
    }
    _LOCK_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Lock file written: %s (pid=%s, job=%s)", _LOCK_FILE, os.getpid(), job_id)
    return _LOCK_FILE


def _remove_lock() -> None:
    try:
        if _LOCK_FILE.exists():
            _LOCK_FILE.unlink()
            logger.info("Lock file removed: %s", _LOCK_FILE)
    except PermissionError:
        logger.warning("Could not remove lock file (permission): %s", _LOCK_FILE)


def _log_subprocess_mem(proc: Optional[subprocess.Popen], label: str = "") -> None:
    """Log subprocess RSS memory usage if psutil is available."""
    if proc is None or proc.pid is None:
        return
    try:
        import psutil
        p = psutil.Process(proc.pid)
        rss_gb = p.memory_info().rss / (1024 ** 3)
        if rss_gb >= _MEM_WARN_GB:
            logger.warning("[RSS] subprocess pid=%s %s — %.2f GB (>= %.1f GB threshold)",
                           proc.pid, label, rss_gb, _MEM_WARN_GB)
        else:
            logger.info("[RSS] subprocess pid=%s %s — %.2f GB", proc.pid, label, rss_gb)
    except ImportError:
        pass  # psutil not installed, skip
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def _check_lock() -> Optional[str]:
    """Return existing job_id from lock file if it is still valid, else ``None``.

    * If no lock file exists → ``None``.
    * If lock file exists and the recorded PID is alive → return that job_id.
    * If lock file exists but PID is dead → remove stale lock and return ``None``.
    * If lock file is older than ``_LOCK_STALE_AGE_SECS`` (4 h) → treat as stale
      even if the PID happens to be alive (pid-reuse after reboot scenario).
    """
    if not _LOCK_FILE.exists():
        return None
    try:
        payload = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupt lock file — removing: %s", _LOCK_FILE)
        _remove_lock()
        return None

    pid = payload.get("pid")
    job_id = payload.get("job_id")

    # Check lock age — protects against PID reuse after reboot
    started_at_str = payload.get("started_at")
    if started_at_str:
        try:
            started_at = datetime.fromisoformat(started_at_str)
            age_secs = (datetime.now() - started_at).total_seconds()
            if age_secs > _LOCK_STALE_AGE_SECS:
                logger.warning(
                    "Stale lock file — age %.0fs exceeds %ss threshold, removing. "
                    "pid=%s job=%s",
                    age_secs, _LOCK_STALE_AGE_SECS, pid, job_id,
                )
                _remove_lock()
                return None
        except (ValueError, TypeError):
            logger.warning("Could not parse lock started_at=%s, ignoring age check", started_at_str)

    if pid and _is_pid_alive(pid):
        logger.info("Lock file valid: pid=%s job=%s", pid, job_id)
        return job_id

    logger.warning("Stale lock file — pid %s not alive, removing", pid)
    _remove_lock()
    return None


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with *pid* is still running (cross-platform)."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ── Watchdog ─────────────────────────────────────────────────────────────────

def _watchdog_loop(job_id: str, proc: subprocess.Popen, stop_event: threading.Event) -> None:
    """Background thread that monitors the pipeline subprocess.

    Kills the subprocess if:
    * No activity from subprocess for ``_STALL_TIMEOUT_SECS``.
    * Total runtime exceeds ``_MAX_RUNTIME_SECS``.
    """
    started_at = datetime.now()
    logger.info("Watchdog started for job %s", job_id)

    while not stop_event.is_set():
        stop_event.wait(_WATCHDOG_INTERVAL_SECS)
        if stop_event.is_set():
            break

        # Check if subprocess already exited naturally
        if proc.poll() is not None:
            logger.info("Watchdog: subprocess for job %s has exited (rc=%s)", job_id, proc.returncode)
            break

        with _jobs_lock:
            job = _jobs.get(job_id)

        if job is None:
            logger.warning("Watchdog: job %s vanished from registry", job_id)
            break

        # --- Stall detection ---
        last_activity_str = job.get("last_activity_at")
        if last_activity_str:
            try:
                last_ts = datetime.fromisoformat(last_activity_str)
                stall_secs = (datetime.now() - last_ts).total_seconds()
            except ValueError:
                stall_secs = 0
        else:
            stall_secs = 0

        # --- Total runtime check ---
        runtime_secs = (datetime.now() - started_at).total_seconds()

        # --- Periodic RSS monitoring (every 30s) ---
        if int(runtime_secs) % 30 < _WATCHDOG_INTERVAL_SECS:
            _log_subprocess_mem(proc, f"job={job_id} runtime={runtime_secs:.0f}s")

        reason = None
        if runtime_secs > _MAX_RUNTIME_SECS:
            reason = f"Pipeline exceeded max runtime of {_MAX_RUNTIME_SECS // 60} minutes"
        elif stall_secs > _STALL_TIMEOUT_SECS:
            reason = (
                f"No activity for {stall_secs:.0f}s "
                f"(threshold: {_STALL_TIMEOUT_SECS}s) — subprocess stalled"
            )

        if reason:
            logger.warning("Watchdog killing subprocess (job=%s): %s", job_id, reason)
            try:
                proc.kill()
                proc.wait(timeout=10)
            except Exception:
                pass
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id]["status"] = "failed"
                    _jobs[job_id]["completed_at"] = datetime.now().isoformat()
                    _jobs[job_id]["error"] = reason
                    _jobs[job_id]["overall_progress"] = job.get("overall_progress", 0)
                    _mark_job_activity(job_id)
            _remove_lock()
            logger.info("Watchdog: job %s marked as failed (stalled)", job_id)
            break

    logger.info("Watchdog stopped for job %s", job_id)


def _run_pipeline_subprocess(job_id: str) -> None:
    daily_update_script = _COSTVIEW_ROOT / "scripts" / "daily_update.py"

    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["stage"] = {
                "name": "initialization",
                "label": "Initialization",
                "progress": 0,
                "detail": None,
            }
            _jobs[job_id]["overall_progress"] = 0
            _mark_job_activity(job_id)

    proc: Optional[subprocess.Popen] = None
    captured_lines: list[str] = []
    stop_event = threading.Event()
    watchdog_thread: Optional[threading.Thread] = None
    lock_written = False
    started_at = datetime.now()
    have_seen_first_output = False
    startup_timeout_hit = False
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(daily_update_script), "--once"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        logger.info("Pipeline subprocess launched: pid=%s job=%s script=%s", proc.pid, job_id, daily_update_script)

        # Start watchdog thread
        watchdog_thread = threading.Thread(
            target=_watchdog_loop,
            args=(job_id, proc, stop_event),
            daemon=True,
        )
        watchdog_thread.start()

        # Write lock file (best-effort)
        try:
            _write_lock(job_id)
            lock_written = True
        except Exception:
            logger.exception("Failed to write pipeline lock file")

        while True:
            # ── Startup timeout: if first output hasn't arrived in time, fail fast ──
            if not have_seen_first_output:
                elapsed = (datetime.now() - started_at).total_seconds()
                if elapsed > _SUBPROCESS_STARTUP_TIMEOUT_SECS:
                    reason = (
                        f"Subprocess pid={proc.pid} produced no output within "
                        f"{_SUBPROCESS_STARTUP_TIMEOUT_SECS}s — killed"
                    )
                    logger.warning("Pipeline startup timeout (%s)", reason)
                    try:
                        proc.kill()
                        proc.wait(timeout=10)
                    except Exception:
                        pass
                    status = "failed"
                    error = reason
                    startup_timeout_hit = True
                    break

            line = proc.stdout.readline() if proc.stdout else ""
            if not line and proc.poll() is not None:
                break
            if not line:
                continue
            if not have_seen_first_output:
                have_seen_first_output = True
                logger.info("Pipeline first output received (job=%s, pid=%s): %.80s", job_id, proc.pid, line.rstrip())
            # Keep a bounded tail for failure diagnosis — the readline loop
            # drains stdout, so proc.communicate() below would return empty.
            captured_lines.append(line.rstrip())
            if len(captured_lines) > 400:
                captured_lines = captured_lines[-400:]
            parsed = _parse_stage_line(line)
            if parsed:
                stage_name, stage_pct, stage_detail = parsed
                label = next(
                    (s["label"] for s in PIPELINE_STAGES if s["name"] == stage_name),
                    stage_name,
                )
                overall = _compute_progress(stage_name, stage_pct)
                with _jobs_lock:
                    if job_id in _jobs:
                        _jobs[job_id]["stage"] = {
                            "name": stage_name,
                            "label": label,
                            "progress": stage_pct,
                            "detail": stage_detail,
                        }
                        _jobs[job_id]["overall_progress"] = overall
                        _mark_job_activity(job_id)
            else:
                with _jobs_lock:
                    if job_id in _jobs:
                        _mark_job_activity(job_id)

        # Make sure the process has exited and pick up any final bytes flushed
        # after our readline loop saw EOF.
        if not startup_timeout_hit:
            try:
                tail, _ = proc.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise
        else:
            tail = None
        if tail:
            for t_line in tail.splitlines():
                captured_lines.append(t_line)
        if not startup_timeout_hit:
            status = "completed" if proc.returncode == 0 else "failed"
            error = None
            if proc.returncode != 0:
                non_marker = [l for l in captured_lines if not l.startswith(_STAGE_PREFIX)]
                tail_block = "\n".join((non_marker or captured_lines)[-20:])
                error = tail_block or f"Pipeline exited with code {proc.returncode} (no output captured)"
    except subprocess.TimeoutExpired:
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        status = "failed"
        error = "Pipeline timed out after 3600 seconds"
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error = str(exc)
    finally:
        # Stop watchdog
        stop_event.set()
        # Remove lock file
        if lock_written:
            _remove_lock()

    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = status
            _jobs[job_id]["completed_at"] = datetime.now().isoformat()
            _jobs[job_id]["error"] = error
            _mark_job_activity(job_id)
            if status == "completed":
                _jobs[job_id]["overall_progress"] = 100
                _jobs[job_id]["stage"] = {
                    "name": "completion",
                    "label": "Completion",
                    "progress": 100,
                    "detail": None,
                }
    gc.collect()
    _log_subprocess_mem(None, f"(parent after subprocess) job={job_id} status={status}")
    logger.info("Pipeline job %s finished: %s", job_id, status)


def trigger_pipeline(client_host: str) -> dict[str, Any]:
    """Spawn a daily-update pipeline job. Idempotent on an existing active job.

    Returns a dict with keys ``job_id``, ``status``, ``message``.
    Caller is responsible for enforcing localhost restriction.

    The lock file (``.pipeline.lock``) provides cross-restart idempotency:
    if a process crashes without cleaning up, the lock is detected as stale
    and replaced.
    """
    # 1. Check in-memory registry for active jobs
    with _jobs_lock:
        for existing_id, existing_job in _jobs.items():
            if existing_job.get("status") in ("started", "running"):
                logger.info(
                    "Returning existing active job %s (status=%s)",
                    existing_id, existing_job["status"],
                )
                return {
                    "job_id": existing_id,
                    "status": existing_job["status"],
                    "message": "Pipeline already running — returning existing job",
                }

    # 2. Check file-based lock (handles stale processes from before restart)
    existing_job_id = _check_lock()
    if existing_job_id:
        # Re-hydrate into in-memory registry
        with _jobs_lock:
            if existing_job_id not in _jobs:
                _jobs[existing_job_id] = {
                    "status": "running",
                    "started_at": datetime.now().isoformat(),
                    "completed_at": None,
                    "error": None,
                    "stage": {"name": "initialization", "label": "Initialization", "progress": 0, "detail": None},
                    "overall_progress": 0,
                    "last_activity_at": datetime.now().isoformat(),
                }
        return {
            "job_id": existing_job_id,
            "status": "running",
            "message": "Pipeline already running (lock file) — returning existing job",
        }

    # 3. All clear — create a new job
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "started",
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "error": None,
            "stage": {"name": "initialization", "label": "Initialization", "progress": 0, "detail": None},
            "overall_progress": 0,
            "last_activity_at": datetime.now().isoformat(),
        }

    threading.Thread(
        target=_run_pipeline_subprocess,
        args=(job_id,),
        daemon=True,
    ).start()
    logger.info("Pipeline triggered: job_id=%s (caller=%s)", job_id, client_host)
    return {
        "job_id": job_id,
        "status": "started",
        "message": "Daily update pipeline started.",
    }


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    return dict(job) if job is not None else None


def list_jobs() -> list[dict[str, Any]]:
    """Snapshot of all known jobs (useful for diagnostic UIs)."""
    with _jobs_lock:
        return [{"job_id": k, **v} for k, v in _jobs.items()]


__all__ = [
    "PIPELINE_STAGES",
    "get_job",
    "list_jobs",
    "trigger_pipeline",
]

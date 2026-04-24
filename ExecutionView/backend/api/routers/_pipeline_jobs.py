"""Shared process-lifetime pipeline job registry + subprocess runner.

Originally lived inside `routers/costview.py`. Extracted so that the new
DatabaseView router (`/api/db/update`, `/api/db/update-status/{job_id}`) and
the legacy CostView aliases (`/api/tca/trigger-update`,
`/api/tca/update-status/{job_id}`) share a single in-memory registry — one
active pipeline at a time, reported consistently to both frontends.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # .../EMSX
_COSTVIEW_ROOT = _PROJECT_ROOT / "CostView"


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
    line = line.strip()
    if not line.startswith(_STAGE_PREFIX):
        return None
    parts = line[len(_STAGE_PREFIX):].strip().split()
    if len(parts) >= 2:
        try:
            return parts[0], min(100, max(0, int(parts[1])))
        except ValueError:
            return parts[0], 0
    if len(parts) == 1:
        return parts[0], 0
    return None


def _run_pipeline_subprocess(job_id: str) -> None:
    daily_update_script = _COSTVIEW_ROOT / "scripts" / "daily_update.py"

    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["stage"] = {
                "name": "initialization",
                "label": "Initialization",
                "progress": 0,
            }
            _jobs[job_id]["overall_progress"] = 0
            _mark_job_activity(job_id)

    proc: Optional[subprocess.Popen] = None
    captured_lines: list[str] = []
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(daily_update_script), "--once"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line and proc.poll() is not None:
                break
            if not line:
                continue
            # Keep a bounded tail for failure diagnosis — the readline loop
            # drains stdout, so proc.communicate() below would return empty.
            captured_lines.append(line.rstrip())
            if len(captured_lines) > 400:
                captured_lines = captured_lines[-400:]
            parsed = _parse_stage_line(line)
            if parsed:
                stage_name, stage_pct = parsed
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
                        }
                        _jobs[job_id]["overall_progress"] = overall
                        _mark_job_activity(job_id)
            else:
                with _jobs_lock:
                    if job_id in _jobs:
                        _mark_job_activity(job_id)

        # Make sure the process has exited and pick up any final bytes flushed
        # after our readline loop saw EOF.
        try:
            tail, _ = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
        if tail:
            for t_line in tail.splitlines():
                captured_lines.append(t_line)
        status = "completed" if proc.returncode == 0 else "failed"
        error = None
        if proc.returncode != 0:
            non_marker = [l for l in captured_lines if not l.startswith(_STAGE_PREFIX)]
            tail_block = "\n".join((non_marker or captured_lines)[-20:])
            error = tail_block or f"Pipeline exited with code {proc.returncode} (no output captured)"
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
        status = "failed"
        error = "Pipeline timed out after 3600 seconds"
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error = str(exc)

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
                }
    logger.info("Pipeline job %s finished: %s", job_id, status)


def trigger_pipeline(client_host: str) -> dict[str, Any]:
    """Spawn a daily-update pipeline job. Idempotent on an existing active job.

    Returns a dict with keys ``job_id``, ``status``, ``message``.
    Caller is responsible for enforcing localhost restriction.
    """
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

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "started",
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "error": None,
            "stage": {"name": "initialization", "label": "Initialization", "progress": 0},
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

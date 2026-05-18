#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Architecture Refactor Workflow Engine

A DAG-based workflow engine for executing the 15-step architecture refactoring
plan with:
  - Dependency-ordered step execution (topological sort)
  - Exponential backoff retry with configurable formula
  - Human approval gates with blocking wait
  - Structured JSON execution logging
  - Persistent state for resume after interruption
  - Rollback capability per step

Usage:
  python scripts/workflow/workflow_engine.py [command] [options]

Commands:
  run          Execute workflow steps (default: next actionable step)
  status       Show current workflow state
  approve      Approve a pending approval gate
  reject       Reject a pending approval gate
  rollback     Rollback a failed step
  reset        Reset workflow state (with confirmation)
  dag          Print step dependency graph

States per step: PENDING → READY → RUNNING → VERIFYING →
                 WAITING_APPROVAL → COMPLETED / FAILED / BLOCKED / ROLLED_BACK
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from collections import deque

logger = logging.getLogger("workflow_engine")

# =============================================================================
# 0) Enums
# =============================================================================

class StepState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    ROLLED_BACK = "ROLLED_BACK"
    SKIPPED = "SKIPPED"


class ErrorCode(str, Enum):
    OK = "OK"
    E_UNKNOWN = "E_UNKNOWN"
    E_CONFIG = "E_CONFIG"
    E_IO = "E_IO"
    E_DEPENDENCY = "E_DEPENDENCY"
    E_CYCLE = "E_CYCLE"
    E_SCHEMA = "E_SCHEMA"
    E_STEP_FAILED = "E_STEP_FAILED"
    E_VERIFY_FAILED = "E_VERIFY_FAILED"
    E_APPROVAL_REJECTED = "E_APPROVAL_REJECTED"
    E_APPROVAL_TIMEOUT = "E_APPROVAL_TIMEOUT"
    E_RETRY_EXHAUSTED = "E_RETRY_EXHAUSTED"
    E_ROLLBACK_FAILED = "E_ROLLBACK_FAILED"
    E_TRANSIENT_NETWORK = "E_TRANSIENT_NETWORK"
    E_CI_TIMEOUT = "E_CI_TIMEOUT"
    E_LOCK_CONFLICT = "E_LOCK_CONFLICT"


RETRYABLE_ERRORS = {
    ErrorCode.E_TRANSIENT_NETWORK,
    ErrorCode.E_CI_TIMEOUT,
    ErrorCode.E_LOCK_CONFLICT,
    ErrorCode.E_STEP_FAILED,
}


# =============================================================================
# 1) Data structures
# =============================================================================

@dataclass
class StepLogEntry:
    """Structured log entry for a single step event."""
    timestamp: str
    step_id: str
    event: str  # started, completed, failed, retrying, waiting_approval, approved, rejected, rollback_started, rollback_completed, rollback_failed
    state: str
    error_code: str = ErrorCode.OK.value
    error_message: str = ""
    retry_count: int = 0
    duration_seconds: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepStateRecord:
    """Persistent state record for a single workflow step."""
    step_id: str
    state: StepState = StepState.PENDING
    retry_count: int = 0
    last_error_code: str = ErrorCode.OK.value
    last_error_message: str = ""
    started_at: str = ""
    completed_at: str = ""
    approved_at: str = ""
    approved_by: str = ""
    rolled_back_at: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    total_duration_seconds: float = 0.0


@dataclass
class WorkflowState:
    """Top-level workflow state persisted to disk."""
    workflow_id: str
    workflow_name: str
    created_at: str
    updated_at: str
    current_step: Optional[str] = None
    steps: dict[str, StepStateRecord] = field(default_factory=dict)
    lock_id: Optional[str] = None
    lock_acquired_at: Optional[str] = None


@dataclass
class ApprovalRequest:
    """Represents a pending approval gate."""
    gate_id: str
    step_id: str
    description: str
    created_at: str
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, approved, rejected, expired


# =============================================================================
# 2) Workflow definition loader
# =============================================================================

class WorkflowDefinition:
    """Loads and validates the workflow YAML definition."""

    def __init__(self, definition_path: Path):
        self.path = definition_path
        raw = self._load_file(definition_path)
        self.meta = raw.get("meta", {})
        self.globals = raw.get("globals", {})
        self.phases = raw.get("phases", [])
        self.steps_raw = raw.get("steps", [])
        self.retry_policy = raw.get("retry_policy", {})
        self.approval_policy = raw.get("approval_policy", {})
        self.monitoring = raw.get("monitoring", {})

        # Build step lookup
        self.steps: dict[str, dict] = {s["id"]: s for s in self.steps_raw}

        # Validate
        self._validate()

    @staticmethod
    def _load_file(path: Path) -> dict:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            raise ValueError(f"Empty definition file: {path}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} must contain JSON-compatible YAML: {exc}") from exc

    def _validate(self) -> None:
        errors = []
        step_ids = set(self.steps.keys())

        for step_id, step in self.steps.items():
            for dep in step.get("depends_on", []):
                if dep not in step_ids:
                    errors.append(f"Step {step_id} depends on unknown step {dep}")

            if step.get("requires_approval") and not step.get("approval_gate"):
                errors.append(f"Step {step_id} requires_approval=true but has no approval_gate")

        if self._has_cycle():
            errors.append("Dependency graph contains a cycle")

        if errors:
            for e in errors:
                logger.error("Validation error: %s", e)
            raise ValueError(f"Workflow definition invalid: {len(errors)} error(s)")

    def _has_cycle(self) -> bool:
        """Kahn's algorithm for cycle detection."""
        in_degree = {sid: 0 for sid in self.steps}
        adj: dict[str, list[str]] = {sid: [] for sid in self.steps}
        for sid, step in self.steps.items():
            for dep in step.get("depends_on", []):
                if dep in self.steps:
                    adj[dep].append(sid)
                    in_degree[sid] += 1

        queue = deque(sid for sid, deg in in_degree.items() if deg == 0)
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return visited != len(self.steps)

    def topological_order(self) -> list[str]:
        """Return step IDs in dependency-respecting execution order."""
        in_degree = {sid: 0 for sid in self.steps}
        adj: dict[str, list[str]] = {sid: [] for sid in self.steps}
        for sid, step in self.steps.items():
            for dep in step.get("depends_on", []):
                if dep in self.steps:
                    adj[dep].append(sid)
                    in_degree[sid] += 1

        queue = deque(sorted(sid for sid, deg in in_degree.items() if deg == 0))
        order = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in sorted(adj[node]):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        return order

    def get_dependencies(self, step_id: str) -> list[str]:
        return self.steps[step_id].get("depends_on", [])

    def get_dependents(self, step_id: str) -> list[str]:
        """Steps that depend on this step."""
        return [sid for sid, step in self.steps.items() if step_id in step.get("depends_on", [])]

    def compute_backoff(self, retry_count: int) -> float:
        """Compute exponential backoff delay in seconds.

        Formula: min(base * (multiplier ** (retry_count - 1)), max_seconds)
        E.g., base=30, multiplier=2: 30s, 60s, 120s, 240s, ...
        """
        base = self.retry_policy.get("backoff_base_seconds", 30)
        multiplier = self.retry_policy.get("backoff_multiplier", 2)
        max_seconds = self.retry_policy.get("backoff_max_seconds", 600)
        if retry_count <= 0:
            return 0
        delay = base * (multiplier ** (retry_count - 1))
        return min(delay, max_seconds)

    @property
    def max_retries(self) -> int:
        return self.retry_policy.get("max_retries", 3)


# =============================================================================
# 3) State persistence
# =============================================================================

class StateStore:
    """Manages workflow state persistence to a JSON file."""

    def __init__(self, state_file: Path, workflow_id: str, workflow_name: str):
        self.state_file = state_file
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name
        self._lock_file = state_file.with_suffix(".lock")

    def load(self) -> WorkflowState:
        if not self.state_file.exists():
            now = datetime.now(timezone.utc).isoformat()
            return WorkflowState(
                workflow_id=self.workflow_id,
                workflow_name=self.workflow_name,
                created_at=now,
                updated_at=now,
            )
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            now = datetime.now(timezone.utc).isoformat()
            return WorkflowState(
                workflow_id=self.workflow_id,
                workflow_name=self.workflow_name,
                created_at=now,
                updated_at=now,
            )

        steps = {}
        for sid, sraw in raw.get("steps", {}).items():
            steps[sid] = StepStateRecord(
                step_id=sid,
                state=StepState(sraw.get("state", "PENDING")),
                retry_count=sraw.get("retry_count", 0),
                last_error_code=sraw.get("last_error_code", "OK"),
                last_error_message=sraw.get("last_error_message", ""),
                started_at=sraw.get("started_at", ""),
                completed_at=sraw.get("completed_at", ""),
                approved_at=sraw.get("approved_at", ""),
                approved_by=sraw.get("approved_by", ""),
                rolled_back_at=sraw.get("rolled_back_at", ""),
                output=sraw.get("output", {}),
                total_duration_seconds=sraw.get("total_duration_seconds", 0.0),
            )
        return WorkflowState(
            workflow_id=raw.get("workflow_id", self.workflow_id),
            workflow_name=raw.get("workflow_name", self.workflow_name),
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
            current_step=raw.get("current_step"),
            steps=steps,
            lock_id=raw.get("lock_id"),
            lock_acquired_at=raw.get("lock_acquired_at"),
        )

    def save(self, state: WorkflowState) -> None:
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(state)
        # Ensure enum values are serialized as strings
        for sid, step_data in data.get("steps", {}).items():
            if isinstance(step_data.get("state"), StepState):
                step_data["state"] = step_data["state"].value
        self.state_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def acquire_lock(self, run_id: str) -> bool:
        if self._lock_file.exists():
            try:
                existing = self._lock_file.read_text(encoding="utf-8").strip()
                if existing and existing != run_id:
                    # Check if lock is stale
                    state = self.load()
                    if state.lock_acquired_at:
                        lock_time = datetime.fromisoformat(state.lock_acquired_at)
                        stale_timeout = 3600  # 1 hour
                        if (datetime.now(timezone.utc) - lock_time).total_seconds() > stale_timeout:
                            logger.warning("Stale lock detected, force-releasing: %s", existing)
                        else:
                            return False
                    else:
                        return False
            except (OSError, ValueError):
                pass
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file.write_text(run_id, encoding="utf-8")
        state = self.load()
        state.lock_id = run_id
        state.lock_acquired_at = datetime.now(timezone.utc).isoformat()
        self.save(state)
        return True

    def release_lock(self, run_id: str) -> None:
        state = self.load()
        if state.lock_id == run_id:
            state.lock_id = None
            state.lock_acquired_at = None
            self.save(state)
        if self._lock_file.exists():
            self._lock_file.unlink(missing_ok=True)

    def get_step(self, state: WorkflowState, step_id: str) -> StepStateRecord:
        if step_id not in state.steps:
            state.steps[step_id] = StepStateRecord(step_id=step_id)
        return state.steps[step_id]

    def set_step_state(
        self,
        state: WorkflowState,
        step_id: str,
        new_state: StepState,
        *,
        error_code: str = ErrorCode.OK.value,
        error_message: str = "",
        output: dict[str, Any] | None = None,
    ) -> StepStateRecord:
        rec = self.get_step(state, step_id)
        rec.state = new_state
        rec.last_error_code = error_code
        rec.last_error_message = error_message
        if output is not None:
            rec.output = output
        now = datetime.now(timezone.utc).isoformat()
        if new_state == StepState.RUNNING and not rec.started_at:
            rec.started_at = now
        if new_state == StepState.COMPLETED:
            rec.completed_at = now
        if new_state == StepState.ROLLED_BACK:
            rec.rolled_back_at = now
        self.save(state)
        return rec


# =============================================================================
# 4) Approval manager
# =============================================================================

class ApprovalManager:
    """Manages human approval gates with blocking wait."""

    def __init__(self, approval_file: Path, timeout_seconds: int = 86400):
        self.approval_file = approval_file
        self.timeout_seconds = timeout_seconds

    def _load_approvals(self) -> dict[str, dict]:
        if not self.approval_file.exists():
            return {}
        try:
            raw = json.loads(self.approval_file.read_text(encoding="utf-8"))
            return {a["gate_id"]: a for a in raw.get("approvals", [])}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_approvals(self, approvals: dict[str, dict]) -> None:
        self.approval_file.parent.mkdir(parents=True, exist_ok=True)
        self.approval_file.write_text(
            json.dumps(
                {"approvals": list(approvals.values())},
                indent=2,
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )

    def request_approval(self, step_def: dict, context: dict[str, Any]) -> ApprovalRequest:
        gate = step_def.get("approval_gate", {})
        gate_id = gate.get("id", f"GATE-{step_def['id']}")
        now = datetime.now(timezone.utc).isoformat()
        req = ApprovalRequest(
            gate_id=gate_id,
            step_id=step_def["id"],
            description=gate.get("description", f"Approval required for step {step_def['id']}"),
            created_at=now,
            context=context,
            status="pending",
        )
        approvals = self._load_approvals()
        approvals[gate_id] = asdict(req)
        self._save_approvals(approvals)
        return req

    def check_approval(self, gate_id: str) -> str:
        """Check approval status. Returns: pending, approved, rejected, expired."""
        approvals = self._load_approvals()
        approval = approvals.get(gate_id)
        if not approval:
            return "pending"
        status = approval.get("status", "pending")
        if status == "pending":
            created = approval.get("created_at", "")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created)
                    elapsed = (datetime.now(timezone.utc) - created_dt).total_seconds()
                    if elapsed > self.timeout_seconds:
                        approval["status"] = "expired"
                        self._save_approvals(approvals)
                        return "expired"
                except ValueError:
                    pass
        return status

    def grant_approval(self, gate_id: str, approver: str = "manual") -> bool:
        approvals = self._load_approvals()
        if gate_id not in approvals:
            return False
        approvals[gate_id]["status"] = "approved"
        approvals[gate_id]["approved_at"] = datetime.now(timezone.utc).isoformat()
        approvals[gate_id]["approved_by"] = approver
        self._save_approvals(approvals)
        return True

    def reject_approval(self, gate_id: str, reason: str = "") -> bool:
        approvals = self._load_approvals()
        if gate_id not in approvals:
            return False
        approvals[gate_id]["status"] = "rejected"
        approvals[gate_id]["rejected_at"] = datetime.now(timezone.utc).isoformat()
        approvals[gate_id]["rejection_reason"] = reason
        self._save_approvals(approvals)
        return True

    def wait_for_approval(self, gate_id: str, poll_interval: int = 10) -> str:
        """Blocking wait for approval. Returns 'approved' or 'rejected' or 'expired'."""
        logger.info("Waiting for approval on gate %s (polling every %ds)...", gate_id, poll_interval)
        while True:
            status = self.check_approval(gate_id)
            if status in ("approved", "rejected", "expired"):
                return status
            time.sleep(poll_interval)


# =============================================================================
# 5) Structured logger
# =============================================================================

class WorkflowLogger:
    """Produces structured JSON execution logs."""

    def __init__(self, log_file: Path, workflow_id: str):
        self.log_file = log_file
        self.workflow_id = workflow_id
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, entry: StepLogEntry) -> None:
        data = asdict(entry)
        data["workflow_id"] = self.workflow_id
        line = json.dumps(data, ensure_ascii=False, default=str)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        # Also emit to Python logger for console visibility
        msg = f"[{entry.step_id}] {entry.event} state={entry.state}"
        if entry.error_code != ErrorCode.OK.value:
            msg += f" error={entry.error_code} msg={entry.error_message[:200]}"
        if entry.retry_count > 0:
            msg += f" retry={entry.retry_count}"
        logger.info(msg)

    def log_event(
        self,
        step_id: str,
        event: str,
        state: str,
        *,
        error_code: str = ErrorCode.OK.value,
        error_message: str = "",
        retry_count: int = 0,
        duration_seconds: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.emit(StepLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            step_id=step_id,
            event=event,
            state=state,
            error_code=error_code,
            error_message=error_message,
            retry_count=retry_count,
            duration_seconds=duration_seconds,
            context=context or {},
        ))


# =============================================================================
# 6) Command executor
# =============================================================================

class CommandExecutor:
    """Executes shell commands and returns structured results."""

    def __init__(self, workspace: Path, timeout: int = 600):
        self.workspace = workspace
        self.timeout = timeout

    def run(self, command: str) -> tuple[bool, str, str, int]:
        """Returns (success, stdout, stderr, return_code)."""
        logger.debug("exec: %s (cwd=%s)", command, self.workspace)
        try:
            p = subprocess.run(
                command,
                cwd=str(self.workspace),
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return p.returncode == 0, p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired:
            return False, "", f"Command timed out after {self.timeout}s: {command}", -1
        except Exception as e:
            return False, "", str(e), -1


# =============================================================================
# 7) Core Workflow Engine
# =============================================================================

class WorkflowEngine:
    """DAG-based workflow executor with retry, approval gates, and rollback."""

    def __init__(
        self,
        definition: WorkflowDefinition,
        state_store: StateStore,
        approval_manager: ApprovalManager,
        wf_logger: WorkflowLogger,
        executor: CommandExecutor,
        mode: str = "apply",
    ):
        self.defn = definition
        self.state_store = state_store
        self.approval_mgr = approval_manager
        self.wf_logger = wf_logger
        self.executor = executor
        self.mode = mode

    # --- state queries ---

    def _is_step_ready(self, state: WorkflowState, step_id: str) -> bool:
        """A step is READY if all dependencies are COMPLETED and it is PENDING."""
        rec = self.state_store.get_step(state, step_id)
        if rec.state != StepState.PENDING:
            return False
        for dep_id in self.defn.get_dependencies(step_id):
            dep_rec = self.state_store.get_step(state, dep_id)
            if dep_rec.state != StepState.COMPLETED:
                return False
        return True

    def _next_actionable_step(self, state: WorkflowState) -> Optional[str]:
        """Find the next step that can be executed."""
        for step_id in self.defn.topological_order():
            rec = self.state_store.get_step(state, step_id)
            if rec.state == StepState.PENDING and self._is_step_ready(state, step_id):
                return step_id
            if rec.state == StepState.WAITING_APPROVAL:
                return step_id
            if rec.state == StepState.FAILED and self._is_retryable(state, step_id):
                return step_id
        return None

    def _is_retryable(self, state: WorkflowState, step_id: str) -> bool:
        rec = self.state_store.get_step(state, step_id)
        if rec.state not in (StepState.FAILED,):
            return False
        error_code = ErrorCode(rec.last_error_code)
        if error_code not in RETRYABLE_ERRORS:
            return False
        if rec.retry_count >= self.defn.max_retries:
            return False
        return True

    # --- execution ---

    def run(self, max_steps: int = 1, wait_for_approval: bool = False) -> dict[str, Any]:
        """Execute up to max_steps actionable steps.

        Returns a report dict with final state.
        """
        run_id = f"run-{int(time.time())}"
        report: dict[str, Any] = {
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "steps_executed": [],
            "state": "running",
        }

        if not self.state_store.acquire_lock(run_id):
            report["state"] = "locked"
            report["error_code"] = ErrorCode.E_LOCK_CONFLICT.value
            report["error_message"] = "Another workflow run is active"
            return report

        state = self.state_store.load()

        try:
            steps_executed = 0
            while steps_executed < max_steps:
                step_id = self._next_actionable_step(state)
                if step_id is None:
                    report["state"] = "done"
                    report["message"] = "No actionable steps remaining"
                    break

                result = self._execute_step(state, step_id, wait_for_approval)
                report["steps_executed"].append(result)
                steps_executed += 1

                # If step is waiting approval in non-blocking mode, stop the run
                if result.get("state") == "waiting_approval" and not wait_for_approval:
                    report["state"] = "waiting_approval"
                    report["message"] = f"Step {step_id} requires manual approval. Use 'approve' command."
                    break

                if result.get("terminal") and result.get("state") not in ("completed",):
                    report["state"] = result["state"]
                    report["error_code"] = result.get("error_code", "")
                    report["error_message"] = result.get("error_message", "")
                    break

            if steps_executed == 0 and not report.get("state"):
                report["state"] = "idle"

        finally:
            self.state_store.release_lock(run_id)

        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        return report

    def _execute_step(
        self, state: WorkflowState, step_id: str, wait_for_approval: bool
    ) -> dict[str, Any]:
        step_def = self.defn.steps[step_id]
        rec = self.state_store.get_step(state, step_id)

        # --- Handle retry case ---
        if rec.state == StepState.FAILED and self._is_retryable(state, step_id):
            rec.retry_count += 1
            backoff = self.defn.compute_backoff(rec.retry_count)
            self.wf_logger.log_event(
                step_id, "retrying", StepState.FAILED.value,
                retry_count=rec.retry_count,
                context={"backoff_seconds": backoff},
            )
            logger.info("Step %s: retry #%d, backoff %.0fs", step_id, rec.retry_count, backoff)
            if self.mode == "apply":
                time.sleep(backoff)

        # --- Handle waiting approval ---
        if rec.state == StepState.WAITING_APPROVAL:
            gate_id = step_def.get("approval_gate", {}).get("id", f"GATE-{step_id}")
            if wait_for_approval:
                result_status = self.approval_mgr.wait_for_approval(gate_id)
            else:
                result_status = self.approval_mgr.check_approval(gate_id)

            if result_status == "approved":
                self.state_store.set_step_state(state, step_id, StepState.APPROVED)
                # Mark approved_at timestamp on the step record
                rec = self.state_store.get_step(state, step_id)
                rec.approved_at = datetime.now(timezone.utc).isoformat()
                self.state_store.save(state)
                self.wf_logger.log_event(step_id, "approved", StepState.APPROVED.value)
            elif result_status == "rejected":
                self.state_store.set_step_state(
                    state, step_id, StepState.BLOCKED,
                    error_code=ErrorCode.E_APPROVAL_REJECTED.value,
                    error_message=f"Approval gate {gate_id} was rejected",
                )
                self.wf_logger.log_event(
                    step_id, "rejected", StepState.BLOCKED.value,
                    error_code=ErrorCode.E_APPROVAL_REJECTED.value,
                )
                return {"step_id": step_id, "state": "blocked", "terminal": True,
                        "error_code": ErrorCode.E_APPROVAL_REJECTED.value}
            elif result_status == "expired":
                self.state_store.set_step_state(
                    state, step_id, StepState.BLOCKED,
                    error_code=ErrorCode.E_APPROVAL_TIMEOUT.value,
                    error_message=f"Approval gate {gate_id} expired",
                )
                return {"step_id": step_id, "state": "blocked", "terminal": True,
                        "error_code": ErrorCode.E_APPROVAL_TIMEOUT.value}
            else:
                # Still pending
                return {"step_id": step_id, "state": "waiting_approval", "terminal": False}

        # --- Mark READY and check approval requirement ---
        self.state_store.set_step_state(state, step_id, StepState.READY)
        self.wf_logger.log_event(step_id, "ready", StepState.READY.value)

        # Check if approval is required and not yet granted.
        # Use approved_at as the indicator that approval was already obtained
        # (handles the case where state transitions APPROVED -> READY).
        already_approved = bool(rec.approved_at)
        if step_def.get("requires_approval") and not already_approved:
            # Request approval
            context = self._build_approval_context(step_def, state)
            req = self.approval_mgr.request_approval(step_def, context)
            self.state_store.set_step_state(state, step_id, StepState.WAITING_APPROVAL)
            self.wf_logger.log_event(
                step_id, "waiting_approval", StepState.WAITING_APPROVAL.value,
                context={"gate_id": req.gate_id},
            )
            logger.info(
                "Step %s requires approval (gate=%s). Use 'workflow_engine approve %s' to proceed.",
                step_id, req.gate_id, req.gate_id,
            )
            return {"step_id": step_id, "state": "waiting_approval", "terminal": False,
                    "gate_id": req.gate_id}

        # --- Execute the step ---
        self.state_store.set_step_state(state, step_id, StepState.RUNNING)
        state.current_step = step_id
        self.state_store.save(state)
        self.wf_logger.log_event(step_id, "started", StepState.RUNNING.value)

        start_time = time.time()
        step_result = self._run_step_implementation(step_def)
        duration = time.time() - start_time

        rec = self.state_store.get_step(state, step_id)
        rec.total_duration_seconds += duration

        if not step_result["ok"]:
            error_code = ErrorCode(step_result.get("error_code", ErrorCode.E_STEP_FAILED.value))
            is_retryable = error_code in RETRYABLE_ERRORS and rec.retry_count < self.defn.max_retries

            if is_retryable:
                self.state_store.set_step_state(
                    state, step_id, StepState.FAILED,
                    error_code=error_code.value,
                    error_message=step_result.get("error_message", ""),
                )
                self.wf_logger.log_event(
                    step_id, "failed", StepState.FAILED.value,
                    error_code=error_code.value,
                    error_message=step_result.get("error_message", "")[:500],
                    retry_count=rec.retry_count,
                    duration_seconds=duration,
                )
                return {"step_id": step_id, "state": "failed_retryable", "terminal": False,
                        "error_code": error_code.value, "retry_count": rec.retry_count}
            else:
                final_state = StepState.BLOCKED if error_code == ErrorCode.E_DEPENDENCY else StepState.FAILED
                self.state_store.set_step_state(
                    state, step_id, final_state,
                    error_code=error_code.value,
                    error_message=step_result.get("error_message", ""),
                )
                self.wf_logger.log_event(
                    step_id, "failed", final_state.value,
                    error_code=error_code.value,
                    error_message=step_result.get("error_message", "")[:500],
                    duration_seconds=duration,
                )
                return {"step_id": step_id, "state": final_state.value, "terminal": True,
                        "error_code": error_code.value,
                        "error_message": step_result.get("error_message", "")}

        # --- Verification ---
        self.state_store.set_step_state(state, step_id, StepState.VERIFYING)
        self.wf_logger.log_event(step_id, "verifying", StepState.VERIFYING.value)

        verify_result = self._run_verification(step_def)
        if not verify_result["ok"]:
            self.state_store.set_step_state(
                state, step_id, StepState.FAILED,
                error_code=verify_result.get("error_code", ErrorCode.E_VERIFY_FAILED.value),
                error_message=verify_result.get("error_message", ""),
            )
            self.wf_logger.log_event(
                step_id, "verify_failed", StepState.FAILED.value,
                error_code=verify_result.get("error_code", ErrorCode.E_VERIFY_FAILED.value),
                error_message=verify_result.get("error_message", "")[:500],
                duration_seconds=duration,
            )
            return {"step_id": step_id, "state": "failed", "terminal": True,
                    "error_code": verify_result.get("error_code", ErrorCode.E_VERIFY_FAILED.value),
                    "error_message": verify_result.get("error_message", "")}

        # --- Completed ---
        self.state_store.set_step_state(
            state, step_id, StepState.COMPLETED,
            output=step_result.get("output", {}),
        )
        state.current_step = None
        self.state_store.save(state)
        self.wf_logger.log_event(
            step_id, "completed", StepState.COMPLETED.value,
            duration_seconds=duration,
        )
        return {"step_id": step_id, "state": "completed", "terminal": False,
                "duration_seconds": duration}

    def _run_step_implementation(self, step_def: dict) -> dict[str, Any]:
        """Run the actual step implementation.

        In a real scenario, this would invoke specific scripts or AI agent actions.
        For now, it delegates to the verification command as a proxy.
        """
        if self.mode == "dry-run":
            logger.info("[dry-run] Would execute step: %s - %s", step_def["id"], step_def["title"])
            return {"ok": True, "output": {"dry_run": True}}

        # Step implementation is handled by the human+AI team.
        # The engine's role is to track state, enforce ordering, and verify.
        # We mark the step as "awaiting manual implementation" if no auto command exists.
        auto_command = step_def.get("auto_command")
        if auto_command:
            success, stdout, stderr, rc = self.executor.run(auto_command)
            if not success:
                return {
                    "ok": False,
                    "error_code": ErrorCode.E_STEP_FAILED.value,
                    "error_message": stderr[:2000] or f"exit code {rc}",
                }
            return {"ok": True, "output": {"stdout": stdout[:5000]}}

        # No auto command — step requires manual implementation
        logger.info(
            "Step %s requires manual implementation. Complete the work, then re-run engine to verify.",
            step_def["id"],
        )
        return {"ok": True, "output": {"manual_implementation": True, "note": "Awaiting human implementation"}}

    def _run_verification(self, step_def: dict) -> dict[str, Any]:
        """Run verification command for a step."""
        verify = step_def.get("verification", {})
        command = verify.get("command", "")
        if not command or self.mode == "dry-run":
            return {"ok": True}

        success, stdout, stderr, rc = self.executor.run(command)
        if not success:
            error_code = verify.get("error_code", ErrorCode.E_VERIFY_FAILED.value)
            return {
                "ok": False,
                "error_code": error_code,
                "error_message": stderr[:2000] or f"Verification failed with exit code {rc}",
            }
        return {"ok": True, "output": {"verify_stdout": stdout[:2000]}}

    def _build_approval_context(self, step_def: dict, state: WorkflowState) -> dict[str, Any]:
        """Build context information for the approval request."""
        context = {
            "step_id": step_def["id"],
            "step_title": step_def["title"],
            "risk_level": step_def.get("risk_level", "unknown"),
            "rollback": step_def.get("rollback", {}).get("description", "No rollback defined"),
            "dependencies_met": [],
            "dependencies_pending": [],
        }
        for dep_id in self.defn.get_dependencies(step_def["id"]):
            dep_rec = self.state_store.get_step(state, dep_id)
            if dep_rec.state == StepState.COMPLETED:
                context["dependencies_met"].append(dep_id)
            else:
                context["dependencies_pending"].append(dep_id)
        return context

    # --- rollback ---

    def rollback_step(self, step_id: str) -> dict[str, Any]:
        """Rollback a specific step using its defined rollback command."""
        step_def = self.defn.steps.get(step_id)
        if not step_def:
            return {"ok": False, "error": f"Unknown step: {step_id}"}

        rollback_def = step_def.get("rollback", {})
        command = rollback_def.get("command", "")
        if not command:
            return {"ok": False, "error": f"No rollback command defined for step {step_id}"}

        state = self.state_store.load()
        rec = self.state_store.get_step(state, step_id)
        if rec.state not in (StepState.FAILED, StepState.BLOCKED):
            return {"ok": False, "error": f"Step {step_id} is in state {rec.state.value}, rollback only applicable to FAILED/BLOCKED"}

        self.wf_logger.log_event(step_id, "rollback_started", rec.state.value)

        success, stdout, stderr, rc = self.executor.run(command)

        if success:
            self.state_store.set_step_state(state, step_id, StepState.ROLLED_BACK)
            self.wf_logger.log_event(step_id, "rollback_completed", StepState.ROLLED_BACK.value)
            return {"ok": True, "step_id": step_id, "state": "rolled_back"}
        else:
            self.wf_logger.log_event(
                step_id, "rollback_failed", rec.state.value,
                error_code=ErrorCode.E_ROLLBACK_FAILED.value,
                error_message=stderr[:1000],
            )
            return {"ok": False, "step_id": step_id, "error": stderr[:1000]}

    # --- status ---

    def get_status(self) -> dict[str, Any]:
        """Return comprehensive workflow status."""
        state = self.state_store.load()
        order = self.defn.topological_order()
        steps_status = []
        for step_id in order:
            rec = self.state_store.get_step(state, step_id)
            step_def = self.defn.steps[step_id]
            steps_status.append({
                "id": step_id,
                "title": step_def.get("title", ""),
                "phase": step_def.get("phase", ""),
                "state": rec.state.value,
                "risk_level": step_def.get("risk_level", ""),
                "retry_count": rec.retry_count,
                "requires_approval": step_def.get("requires_approval", False),
                "last_error": rec.last_error_message[:200] if rec.last_error_message else "",
                "duration_seconds": rec.total_duration_seconds,
            })

        completed = sum(1 for s in steps_status if s["state"] == "completed")
        total = len(steps_status)

        # Identify blockers
        blockers = []
        for s in steps_status:
            if s["state"] in ("failed", "blocked", "waiting_approval"):
                blockers.append(s)

        return {
            "workflow": self.defn.meta.get("name", ""),
            "progress": f"{completed}/{total}",
            "progress_pct": round(completed / total * 100, 1) if total else 0,
            "current_step": state.current_step,
            "blockers": blockers,
            "steps": steps_status,
        }

    def print_dag(self) -> str:
        """Return a text representation of the dependency graph."""
        order = self.defn.topological_order()
        lines = []
        for step_id in order:
            step = self.defn.steps[step_id]
            deps = step.get("depends_on", [])
            dep_str = ", ".join(deps) if deps else "(none)"
            approval = " [APPROVAL]" if step.get("requires_approval") else ""
            risk = step.get("risk_level", "")
            lines.append(f"  {step_id} ({step.get('phase', '?')}) -- depends: [{dep_str}]{approval} risk:{risk}")
        return "\n".join(lines)


# =============================================================================
# 8) CLI
# =============================================================================

def build_engine(args: argparse.Namespace) -> WorkflowEngine:
    workspace = Path(args.workspace).resolve()
    defn_path = workspace / args.definition
    definition = WorkflowDefinition(defn_path)

    state_file = workspace / definition.monitoring.get(
        "state_file", "plans/architecture-refactor-workflow-state.json"
    )
    approval_file = workspace / definition.approval_policy.get(
        "approval_state_file", "plans/architecture-refactor-approvals.json"
    )
    log_file = workspace / definition.monitoring.get(
        "log_file", "logs/workflow/architecture-refactor.log"
    )

    workflow_id = f"arch-refactor-{int(time.time())}"
    state_store = StateStore(state_file, workflow_id, definition.meta.get("name", ""))
    approval_mgr = ApprovalManager(
        approval_file,
        timeout_seconds=definition.approval_policy.get("default_timeout_seconds", 86400),
    )
    wf_logger = WorkflowLogger(log_file, workflow_id)
    executor = CommandExecutor(workspace)
    mode = getattr(args, "mode", "apply")

    return WorkflowEngine(definition, state_store, approval_mgr, wf_logger, executor, mode)


def cmd_run(args: argparse.Namespace) -> int:
    engine = build_engine(args)
    report = engine.run(
        max_steps=args.max_steps,
        wait_for_approval=getattr(args, "wait", False),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    state = report.get("state", "unknown")
    if state in ("done", "idle"):
        return 0
    if state == "locked":
        return 2
    if "blocked" in str(report.get("error_code", "")).lower():
        return 4
    return 3


def cmd_status(args: argparse.Namespace) -> int:
    engine = build_engine(args)
    status = engine.get_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    defn_path = workspace / args.definition
    definition = WorkflowDefinition(defn_path)
    approval_file = workspace / definition.approval_policy.get(
        "approval_state_file", "plans/architecture-refactor-approvals.json"
    )
    mgr = ApprovalManager(approval_file)
    ok = mgr.grant_approval(args.gate_id, approver=args.approver or "cli")
    if ok:
        print(f"Gate {args.gate_id} approved by {args.approver or 'cli'}")
        return 0
    else:
        print(f"Gate {args.gate_id} not found")
        return 1


def cmd_reject(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    defn_path = workspace / args.definition
    definition = WorkflowDefinition(defn_path)
    approval_file = workspace / definition.approval_policy.get(
        "approval_state_file", "plans/architecture-refactor-approvals.json"
    )
    mgr = ApprovalManager(approval_file)
    ok = mgr.reject_approval(args.gate_id, reason=args.reason or "")
    if ok:
        print(f"Gate {args.gate_id} rejected")
        return 0
    else:
        print(f"Gate {args.gate_id} not found")
        return 1


def cmd_rollback(args: argparse.Namespace) -> int:
    engine = build_engine(args)
    result = engine.rollback_step(args.step_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def cmd_reset(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    defn_path = workspace / args.definition
    definition = WorkflowDefinition(defn_path)
    state_file = workspace / definition.monitoring.get(
        "state_file", "plans/architecture-refactor-workflow-state.json"
    )
    approval_file = workspace / definition.approval_policy.get(
        "approval_state_file", "plans/architecture-refactor-approvals.json"
    )
    if not args.force:
        print("WARNING: This will reset all workflow state. Use --force to confirm.")
        return 1
    if state_file.exists():
        state_file.unlink()
        print(f"Deleted state file: {state_file}")
    if approval_file.exists():
        approval_file.unlink()
        print(f"Deleted approvals file: {approval_file}")
    return 0


def cmd_dag(args: argparse.Namespace) -> int:
    engine = build_engine(args)
    print(engine.print_dag())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Architecture Refactor Workflow Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--definition", default="plans/architecture-refactor-workflow.yaml")
    parser.add_argument("--mode", choices=["dry-run", "apply"], default="apply")
    parser.add_argument("--log-level", default="INFO")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run
    run_parser = subparsers.add_parser("run", help="Execute workflow steps")
    run_parser.add_argument("--max-steps", type=int, default=1, help="Max steps to execute")
    run_parser.add_argument("--wait", action="store_true", help="Block waiting for approvals")

    # status
    subparsers.add_parser("status", help="Show workflow status")

    # approve
    approve_parser = subparsers.add_parser("approve", help="Approve a gate")
    approve_parser.add_argument("gate_id", help="Gate ID to approve (e.g., GATE-S06)")
    approve_parser.add_argument("--approver", default="", help="Approver identifier")

    # reject
    reject_parser = subparsers.add_parser("reject", help="Reject a gate")
    reject_parser.add_argument("gate_id", help="Gate ID to reject")
    reject_parser.add_argument("--reason", default="", help="Rejection reason")

    # rollback
    rollback_parser = subparsers.add_parser("rollback", help="Rollback a failed step")
    rollback_parser.add_argument("step_id", help="Step ID to rollback (e.g., S06)")

    # reset
    reset_parser = subparsers.add_parser("reset", help="Reset workflow state")
    reset_parser.add_argument("--force", action="store_true", help="Confirm reset")

    # dag
    subparsers.add_parser("dag", help="Print dependency graph")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    cmd = args.command or "status"
    handlers = {
        "run": cmd_run,
        "status": cmd_status,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "rollback": cmd_rollback,
        "reset": cmd_reset,
        "dag": cmd_dag,
    }
    handler = handlers.get(cmd)
    if not handler:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

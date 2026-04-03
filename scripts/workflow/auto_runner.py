#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Execution Platform Autopilot Runner

Reads the delivery ledger, selects the next actionable issue, runs the
verification chain, updates ledger status, and optionally waits for CI.

States: PENDING -> IMPLEMENTING -> VERIFYING -> UPDATING_LEDGER
        -> WAITING_CI -> DONE / FAILED / BLOCKED / WAITING_MANUAL_GATE
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol, TypedDict

logger = logging.getLogger("auto_runner")

# =============================================================================
# 0) Enums: FSM states / error codes / exit codes
# =============================================================================

class RunnerState(str, Enum):
    PENDING = "PENDING"
    IMPLEMENTING = "IMPLEMENTING"
    VERIFYING = "VERIFYING"
    UPDATING_LEDGER = "UPDATING_LEDGER"
    WAITING_CI = "WAITING_CI"
    WAITING_MANUAL_GATE = "WAITING_MANUAL_GATE"
    DONE = "DONE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"


class ErrorCode(str, Enum):
    OK = "OK"
    E_UNKNOWN = "E_UNKNOWN"
    E_CONFIG = "E_CONFIG"
    E_IO = "E_IO"
    E_LOCK_CONFLICT = "E_LOCK_CONFLICT"
    E_CONCURRENCY = "E_CONCURRENCY"
    E_LEDGER_PARSE = "E_LEDGER_PARSE"
    E_LEDGER_INVALID = "E_LEDGER_INVALID"
    E_DEPENDENCY = "E_DEPENDENCY"
    E_NO_ACTIONABLE_ISSUE = "E_NO_ACTIONABLE_ISSUE"
    E_MANUAL_GATE_REQUIRED = "E_MANUAL_GATE_REQUIRED"
    E_IMPLEMENTATION_FAILED = "E_IMPLEMENTATION_FAILED"
    E_VERIFY_PLAN_FAILED = "E_VERIFY_PLAN_FAILED"
    E_VERIFY_BUILD_FAILED = "E_VERIFY_BUILD_FAILED"
    E_VERIFY_SCRIPT_FAILED = "E_VERIFY_SCRIPT_FAILED"
    E_CI_TIMEOUT = "E_CI_TIMEOUT"
    E_CI_FAILED = "E_CI_FAILED"
    E_CI_API = "E_CI_API"
    E_TRANSIENT_NETWORK = "E_TRANSIENT_NETWORK"
    E_SCHEMA = "E_SCHEMA"


class ExitCode(int, Enum):
    SUCCESS = 0
    RETRYABLE_FAILURE = 2
    PERMANENT_FAILURE = 3
    BLOCKED = 4
    WAITING_MANUAL_GATE = 5


RETRYABLE_ERROR_CODES = {
    ErrorCode.E_TRANSIENT_NETWORK,
    ErrorCode.E_CI_TIMEOUT,
    ErrorCode.E_CI_API,
    ErrorCode.E_LOCK_CONFLICT,
}


# =============================================================================
# 1) I/O data structures
# =============================================================================

class RunnerReport(TypedDict, total=False):
    run_id: str
    started_at: str
    finished_at: str
    state: str
    error_code: str
    error_message: str
    current_issue_id: Optional[str]
    current_step: Optional[str]
    retry_count: int
    commit_sha: Optional[str]
    ci_conclusion: Optional[str]
    details: dict[str, Any]


@dataclass
class RunConfig:
    workspace: Path
    status_file: Path
    risk_file: Path
    policy_file: Path
    runstate_file: Path
    mode: str = "apply"
    max_steps: int = 1
    allow_risky_gates: bool = False
    ci_timeout_seconds: int = 1200
    ci_poll_interval_seconds: int = 15
    max_retries: int = 3
    backoff_seconds: list[int] = field(default_factory=lambda: [30, 120, 300])


@dataclass
class RunStateSnapshot:
    run_id: str
    state: RunnerState
    updated_at: str
    current_issue_id: Optional[str] = None
    current_step: Optional[str] = None
    retry_count: int = 0
    last_error_code: ErrorCode = ErrorCode.OK
    last_error_message: str = ""
    commit_sha: Optional[str] = None


@dataclass
class IssueRef:
    phase_id: str
    sprint_id: str
    issue_id: str
    title: str
    status: str
    dependencies: list[str]
    checkpoints: list[dict[str, Any]]
    files: list[str] = field(default_factory=list)


@dataclass
class StepResult:
    ok: bool
    error_code: ErrorCode = ErrorCode.OK
    error_message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# 2) Protocol interfaces
# =============================================================================

class LedgerGateway(Protocol):
    def load(self) -> dict[str, Any]: ...
    def save(self, data: dict[str, Any]) -> None: ...
    def select_next_issue(self, data: dict[str, Any]) -> Optional[IssueRef]: ...
    def set_issue_status(self, data: dict[str, Any], issue_id: str, status: str) -> None: ...
    def set_checkpoint_status(self, data: dict[str, Any], issue_id: str, checkpoint_id: str, status: str) -> None: ...
    def current_sprint(self, data: dict[str, Any]) -> str: ...


class RunStateStore(Protocol):
    def load(self) -> Optional[RunStateSnapshot]: ...
    def save(self, snapshot: RunStateSnapshot) -> None: ...
    def clear(self) -> None: ...
    def acquire_lock(self, run_id: str) -> bool: ...
    def release_lock(self, run_id: str) -> None: ...


class CIGateway(Protocol):
    def wait_for_commit_checks(self, commit_sha: str, timeout_sec: int, poll_sec: int) -> StepResult: ...


class CommandExecutor(Protocol):
    def run(self, command: str, cwd: Path) -> StepResult: ...


# =============================================================================
# 3) Default implementations
# =============================================================================

class JsonFileLedgerGateway:
    """Ledger stored as JSON-compatible YAML (current repo format)."""

    def __init__(self, status_file: Path):
        self.status_file = status_file

    def load(self) -> dict[str, Any]:
        try:
            return json.loads(self.status_file.read_text(encoding="utf-8"))
        except Exception as e:
            raise RuntimeError(f"load ledger failed: {e}") from e

    def save(self, data: dict[str, Any]) -> None:
        data["program"]["last_synced_at"] = datetime.now(timezone.utc).isoformat()
        self.status_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def current_sprint(self, data: dict[str, Any]) -> str:
        return data.get("program", {}).get("current_sprint", "")

    def select_next_issue(self, data: dict[str, Any]) -> Optional[IssueRef]:
        """Pick the first actionable issue in the current sprint.

        Actionable = status in {todo, in_progress} AND all dependencies
        are completed or cancelled.
        """
        current_sprint_id = self.current_sprint(data)
        if not current_sprint_id:
            return None

        # Build completed set for dependency check
        completed: set[str] = set()
        sprint_issues: list[tuple[str, str, dict]] = []
        for phase in data.get("phases", []):
            phase_id = phase.get("id", "")
            for sprint in phase.get("sprints", []):
                sprint_id = sprint.get("id", "")
                for issue in sprint.get("issues", []):
                    iid = issue.get("id", "")
                    st = issue.get("status", "")
                    if st in ("completed", "cancelled"):
                        completed.add(iid)
                    if sprint_id == current_sprint_id:
                        sprint_issues.append((phase_id, sprint_id, issue))

        for phase_id, sprint_id, issue in sprint_issues:
            st = issue.get("status", "")
            if st not in ("todo", "in_progress"):
                continue
            deps = issue.get("dependencies", [])
            if all(d in completed for d in deps):
                return IssueRef(
                    phase_id=phase_id,
                    sprint_id=sprint_id,
                    issue_id=issue["id"],
                    title=issue.get("title", ""),
                    status=st,
                    dependencies=deps,
                    checkpoints=issue.get("checkpoints", []),
                    files=issue.get("files", []),
                )
        return None

    def set_issue_status(self, data: dict[str, Any], issue_id: str, status: str) -> None:
        for phase in data.get("phases", []):
            for sprint in phase.get("sprints", []):
                for issue in sprint.get("issues", []):
                    if issue.get("id") == issue_id:
                        issue["status"] = status
                        return
        raise KeyError(f"Issue {issue_id} not found in ledger")

    def set_checkpoint_status(self, data: dict[str, Any], issue_id: str, checkpoint_id: str, status: str) -> None:
        for phase in data.get("phases", []):
            for sprint in phase.get("sprints", []):
                for issue in sprint.get("issues", []):
                    if issue.get("id") == issue_id:
                        for cp in issue.get("checkpoints", []):
                            if cp.get("id") == checkpoint_id:
                                cp["status"] = status
                                return
        raise KeyError(f"Checkpoint {checkpoint_id} in issue {issue_id} not found")


class JsonRunStateStore:
    def __init__(self, runstate_file: Path):
        self.runstate_file = runstate_file
        self.lock_file = runstate_file.with_suffix(".lock")

    def load(self) -> Optional[RunStateSnapshot]:
        if not self.runstate_file.exists():
            return None
        try:
            raw = json.loads(self.runstate_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not raw.get("run_id"):
            return None
        return RunStateSnapshot(
            run_id=raw["run_id"],
            state=RunnerState(raw.get("state", "PENDING")),
            updated_at=raw.get("updated_at", ""),
            current_issue_id=raw.get("current_issue_id"),
            current_step=raw.get("current_step"),
            retry_count=raw.get("retry_count", 0),
            last_error_code=ErrorCode(raw.get("last_error_code", "OK")),
            last_error_message=raw.get("last_error_message", ""),
            commit_sha=raw.get("commit_sha"),
        )

    def save(self, snapshot: RunStateSnapshot) -> None:
        self.runstate_file.parent.mkdir(parents=True, exist_ok=True)
        self.runstate_file.write_text(
            json.dumps(
                {
                    **asdict(snapshot),
                    "state": snapshot.state.value,
                    "last_error_code": snapshot.last_error_code.value,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def clear(self) -> None:
        if self.runstate_file.exists():
            self.runstate_file.unlink(missing_ok=True)

    def acquire_lock(self, run_id: str) -> bool:
        if self.lock_file.exists():
            try:
                existing = self.lock_file.read_text(encoding="utf-8").strip()
                if existing and existing != run_id:
                    return False
            except OSError:
                return False
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file.write_text(run_id, encoding="utf-8")
        return True

    def release_lock(self, run_id: str) -> None:
        if self.lock_file.exists():
            self.lock_file.unlink(missing_ok=True)


class SubprocessCommandExecutor:
    def run(self, command: str, cwd: Path) -> StepResult:
        logger.info("exec: %s (cwd=%s)", command, cwd)
        try:
            p = subprocess.run(
                command,
                cwd=str(cwd),
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if p.returncode == 0:
                return StepResult(ok=True, payload={"stdout": p.stdout, "stderr": p.stderr})
            return StepResult(
                ok=False,
                error_code=ErrorCode.E_VERIFY_SCRIPT_FAILED,
                error_message=p.stderr[:2000] or f"exit code {p.returncode}",
                payload={"stdout": p.stdout, "stderr": p.stderr, "returncode": p.returncode},
            )
        except subprocess.TimeoutExpired:
            return StepResult(ok=False, error_code=ErrorCode.E_CI_TIMEOUT, error_message=f"command timed out: {command}")
        except Exception as e:
            return StepResult(ok=False, error_code=ErrorCode.E_IO, error_message=str(e))


class LocalCIGateway:
    """CI check via scripts/workflow/collect_ci_status.py (or dummy skip)."""

    def __init__(self, workspace: Path, executor: CommandExecutor):
        self.workspace = workspace
        self.executor = executor
        self.collector = workspace / "scripts" / "workflow" / "collect_ci_status.py"

    def wait_for_commit_checks(self, commit_sha: str, timeout_sec: int, poll_sec: int) -> StepResult:
        if not self.collector.exists():
            logger.info("collect_ci_status.py not found — skipping CI wait")
            return StepResult(ok=True, payload={"skipped": True, "reason": "no collector script"})

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            res = self.executor.run(
                f"python scripts/workflow/collect_ci_status.py --commit {commit_sha} --output-json -",
                self.workspace,
            )
            if not res.ok:
                if res.error_code in RETRYABLE_ERROR_CODES:
                    time.sleep(poll_sec)
                    continue
                return res

            try:
                ci_data = json.loads(res.payload.get("stdout", "{}"))
            except json.JSONDecodeError:
                time.sleep(poll_sec)
                continue

            conclusion = ci_data.get("overall_conclusion", "pending")
            if conclusion == "success":
                return StepResult(ok=True, payload=ci_data)
            if conclusion == "failure":
                return StepResult(ok=False, error_code=ErrorCode.E_CI_FAILED, error_message="CI checks failed", payload=ci_data)
            if conclusion in ("pending", "queued", "in_progress"):
                time.sleep(poll_sec)
                continue
            # Unknown status
            return StepResult(ok=False, error_code=ErrorCode.E_CI_API, error_message=f"unexpected CI status: {conclusion}", payload=ci_data)

        return StepResult(ok=False, error_code=ErrorCode.E_CI_TIMEOUT, error_message=f"CI timed out after {timeout_sec}s")


# =============================================================================
# 4) Policy loader
# =============================================================================

def load_policy(policy_file: Path) -> dict[str, Any]:
    """Load the autopilot policy; return empty dict if missing."""
    if not policy_file.exists():
        return {}
    try:
        return json.loads(policy_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_manual_gate_required(policy: dict[str, Any], *, sprint_closing: bool = False,
                            phase_changing: bool = False, risk_downgrade: bool = False) -> bool:
    """Check if any manual gate trigger is active."""
    triggers = policy.get("manual_gate_required", {}).get("triggers", [])
    trigger_ids = {t.get("id") for t in triggers}

    if sprint_closing and "sprint-close" in trigger_ids:
        return True
    if phase_changing and "phase-transition" in trigger_ids:
        return True
    if risk_downgrade and "risk-status-downgrade" in trigger_ids:
        return True
    return False


# =============================================================================
# 5) AutoRunner core
# =============================================================================

class AutoRunner:
    def __init__(
        self,
        config: RunConfig,
        ledger: LedgerGateway,
        runstate: RunStateStore,
        executor: CommandExecutor,
        ci: CIGateway,
        policy: dict[str, Any] | None = None,
    ):
        self.cfg = config
        self.ledger = ledger
        self.runstate = runstate
        self.executor = executor
        self.ci = ci
        self.policy = policy or {}
        self._run_id = f"run-{int(time.time())}"

    # --- state transition helper ---
    def _transition(self, snap: RunStateSnapshot, to_state: RunnerState, step: str | None = None) -> None:
        snap.state = to_state
        if step is not None:
            snap.current_step = step
        snap.updated_at = datetime.now(timezone.utc).isoformat()
        self.runstate.save(snap)
        logger.info("transition -> %s step=%s issue=%s", to_state.value, step, snap.current_issue_id)

    # --- main entry ---
    def run(self) -> RunnerReport:
        started_at = datetime.now(timezone.utc).isoformat()
        report: RunnerReport = {
            "run_id": self._run_id,
            "started_at": started_at,
            "state": RunnerState.PENDING.value,
            "retry_count": 0,
        }

        if not self.runstate.acquire_lock(self._run_id):
            return self._fail_report(report, ErrorCode.E_LOCK_CONFLICT, "another run is active", ExitCode.RETRYABLE_FAILURE)

        snap = RunStateSnapshot(run_id=self._run_id, state=RunnerState.PENDING, updated_at=started_at)
        self.runstate.save(snap)

        try:
            steps_done = 0
            for _ in range(self.cfg.max_steps):
                result = self._run_one_cycle(snap, report)
                steps_done += 1
                if result is not None:
                    return result
                # cycle completed successfully, snap.state is DONE for that issue
                # reset for next issue to pick up
                snap.state = RunnerState.PENDING
                snap.current_issue_id = None
                snap.current_step = None
                snap.retry_count = 0

            self._transition(snap, RunnerState.DONE, f"completed-{steps_done}-steps")
            report["state"] = RunnerState.DONE.value
            return self._success_report(report)
        finally:
            self.runstate.release_lock(self._run_id)

    def _run_one_cycle(self, snap: RunStateSnapshot, report: RunnerReport) -> RunnerReport | None:
        """Run one full issue cycle. Return report on terminal state, None if issue completed OK."""
        # 1) Select issue
        issue = self._select_issue(snap)
        if issue is None:
            self._transition(snap, RunnerState.DONE, "no-actionable-issue")
            report["state"] = RunnerState.DONE.value
            report["error_code"] = ErrorCode.E_NO_ACTIONABLE_ISSUE.value
            report["error_message"] = "no actionable issue in current sprint"
            return self._success_report(report)

        snap.current_issue_id = issue.issue_id
        report["current_issue_id"] = issue.issue_id

        # 2) Manual gate check
        gate = self._check_manual_gate(issue, snap)
        if not gate.ok:
            self._transition(snap, RunnerState.WAITING_MANUAL_GATE, "manual-gate")
            report["state"] = RunnerState.WAITING_MANUAL_GATE.value
            return self._fail_report(report, gate.error_code, gate.error_message, ExitCode.WAITING_MANUAL_GATE)

        # 3) Mark issue in_progress
        self._transition(snap, RunnerState.IMPLEMENTING, "set-in-progress")
        if self.cfg.mode == "apply":
            try:
                data = self.ledger.load()
                self.ledger.set_issue_status(data, issue.issue_id, "in_progress")
                self.ledger.save(data)
            except Exception as e:
                logger.warning("failed to set issue in_progress: %s", e)

        # 4) Verify
        self._transition(snap, RunnerState.VERIFYING, "verify")
        ver = self._verify_issue(issue)
        if not ver.ok:
            return self._handle_failure(report, snap, ver)

        # 5) Update ledger
        self._transition(snap, RunnerState.UPDATING_LEDGER, "update-ledger")
        upd = self._update_ledger(issue)
        if not upd.ok:
            return self._handle_failure(report, snap, upd)

        # 6) CI wait
        if snap.commit_sha:
            self._transition(snap, RunnerState.WAITING_CI, "wait-ci")
            ci_res = self.ci.wait_for_commit_checks(
                snap.commit_sha,
                self.cfg.ci_timeout_seconds,
                self.cfg.ci_poll_interval_seconds,
            )
            if not ci_res.ok:
                return self._handle_failure(report, snap, ci_res)
            report["ci_conclusion"] = ci_res.payload.get("overall_conclusion", "unknown")

        # Done for this issue
        self._transition(snap, RunnerState.DONE, f"issue-{issue.issue_id}-done")
        return None  # signals caller to continue

    # --- sub-steps ---
    def _select_issue(self, snap: RunStateSnapshot) -> IssueRef | None:
        try:
            data = self.ledger.load()
        except Exception as e:
            logger.error("ledger load failed: %s", e)
            return None
        return self.ledger.select_next_issue(data)

    def _check_manual_gate(self, issue: IssueRef, snap: RunStateSnapshot) -> StepResult:
        """Check if issue requires manual gate per policy."""
        data = self.ledger.load()
        current_sprint_id = self.ledger.current_sprint(data)

        # Detect sprint closing: if this is the last open issue in the sprint
        sprint_issues = []
        for phase in data.get("phases", []):
            for sprint in phase.get("sprints", []):
                if sprint.get("id") == current_sprint_id:
                    sprint_issues = sprint.get("issues", [])
                    break

        open_count = sum(1 for i in sprint_issues if i.get("status") not in ("completed", "cancelled"))
        sprint_closing = open_count <= 1 and issue.status in ("todo", "in_progress")

        if is_manual_gate_required(self.policy, sprint_closing=sprint_closing) and not self.cfg.allow_risky_gates:
            return StepResult(
                ok=False,
                error_code=ErrorCode.E_MANUAL_GATE_REQUIRED,
                error_message=f"manual gate required: last issue in sprint {current_sprint_id}",
            )
        return StepResult(ok=True)

    def _verify_issue(self, issue: IssueRef) -> StepResult:
        """Run verification chain from policy or defaults."""
        chain = self.policy.get("verification_chain", {}).get("steps", [])
        if not chain:
            # Default chain
            chain = [
                {"id": "compile-check", "command": "python -m compileall Execution/backend/api scripts/workflow -q"},
                {"id": "plan-validation", "command": "python scripts/workflow/validate_phase_gate.py --mode plan"},
                {"id": "status-sync", "command": "python scripts/workflow/sync_execution_status.py --output-json docs/generated/execution-platform-status.json"},
                {"id": "handoff-snapshot", "command": "python scripts/workflow/generate_handoff_snapshot.py --output docs/generated/execution-platform-handoff.md"},
            ]

        for step in chain:
            cmd = step.get("command", "")
            step_id = step.get("id", "unknown")
            logger.info("verify step: %s", step_id)

            if self.cfg.mode == "dry-run":
                logger.info("  [dry-run] would run: %s", cmd)
                continue

            r = self.executor.run(cmd, self.cfg.workspace)
            if not r.ok:
                ec = ErrorCode(step.get("error_code", "E_VERIFY_SCRIPT_FAILED"))
                return StepResult(
                    ok=False,
                    error_code=ec,
                    error_message=f"verify step '{step_id}' failed: {r.error_message[:500]}",
                    payload=r.payload,
                )
        return StepResult(ok=True)

    def _update_ledger(self, issue: IssueRef) -> StepResult:
        """Mark issue completed and its checkpoints passed."""
        if self.cfg.mode == "dry-run":
            logger.info("[dry-run] would mark issue %s completed", issue.issue_id)
            return StepResult(ok=True)

        try:
            data = self.ledger.load()
            self.ledger.set_issue_status(data, issue.issue_id, "completed")
            for cp in issue.checkpoints:
                cp_id = cp.get("id")
                if cp_id:
                    self.ledger.set_checkpoint_status(data, issue.issue_id, cp_id, "passed")
            data["program"]["updated_by"] = f"autopilot: {issue.issue_id} completed"
            self.ledger.save(data)
            return StepResult(ok=True)
        except Exception as e:
            return StepResult(ok=False, error_code=ErrorCode.E_LEDGER_INVALID, error_message=str(e))

    # --- failure handling ---
    def _handle_failure(self, report: RunnerReport, snap: RunStateSnapshot, res: StepResult) -> RunnerReport:
        is_retryable = res.error_code in RETRYABLE_ERROR_CODES and snap.retry_count < self.cfg.max_retries
        if is_retryable:
            snap.retry_count += 1
            snap.last_error_code = res.error_code
            snap.last_error_message = res.error_message
            self._transition(snap, RunnerState.FAILED_RETRYABLE, snap.current_step)
            self._backoff(snap.retry_count)
            report["retry_count"] = snap.retry_count
            return self._fail_report(report, res.error_code, res.error_message, ExitCode.RETRYABLE_FAILURE)

        is_blocked = res.error_code in {ErrorCode.E_DEPENDENCY, ErrorCode.E_MANUAL_GATE_REQUIRED}
        terminal = RunnerState.BLOCKED if is_blocked else RunnerState.FAILED
        self._transition(snap, terminal, snap.current_step)

        # Write blocked status back to ledger
        if self.cfg.mode == "apply" and snap.current_issue_id:
            try:
                data = self.ledger.load()
                self.ledger.set_issue_status(data, snap.current_issue_id, "blocked" if is_blocked else "in_progress")
                self.ledger.save(data)
            except Exception as e:
                logger.warning("failed to write failure state to ledger: %s", e)

        exit_code = ExitCode.BLOCKED if is_blocked else ExitCode.PERMANENT_FAILURE
        return self._fail_report(report, res.error_code, res.error_message, exit_code)

    def _backoff(self, retry_count: int) -> None:
        idx = min(retry_count - 1, len(self.cfg.backoff_seconds) - 1)
        delay = self.cfg.backoff_seconds[idx]
        logger.info("backoff: retry #%d, sleeping %ds", retry_count, delay)
        time.sleep(delay)

    # --- report builders ---
    def _success_report(self, report: RunnerReport) -> RunnerReport:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        if "error_code" not in report:
            report["error_code"] = ErrorCode.OK.value
        report["details"] = {"suggested_exit_code": int(ExitCode.SUCCESS)}
        return report

    def _fail_report(self, report: RunnerReport, code: ErrorCode, msg: str, _exit: ExitCode) -> RunnerReport:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["error_code"] = code.value
        report["error_message"] = msg
        if "state" not in report or report["state"] == RunnerState.PENDING.value:
            report["state"] = RunnerState.FAILED.value
        report["details"] = {"suggested_exit_code": int(_exit)}
        return report


# =============================================================================
# 6) CLI
# =============================================================================

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Execution platform autopilot runner")
    p.add_argument("--workspace", default=".")
    p.add_argument("--status-file", default=".workbuddy/plans/execution-platform-status.yaml")
    p.add_argument("--risk-file", default=".workbuddy/plans/execution-platform-risk-register.yaml")
    p.add_argument("--policy-file", default=".workbuddy/plans/execution-platform-autopilot-policy.yaml")
    p.add_argument("--runstate-file", default=".workbuddy/plans/execution-platform-autopilot-runstate.json")
    p.add_argument("--mode", choices=["dry-run", "apply"], default="apply")
    p.add_argument("--max-steps", type=int, default=1)
    p.add_argument("--allow-risky-gates", action="store_true")
    p.add_argument("--ci-timeout-seconds", type=int, default=1200)
    p.add_argument("--ci-poll-interval-seconds", type=int, default=15)
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def build_config(args: argparse.Namespace) -> RunConfig:
    ws = Path(args.workspace).resolve()
    return RunConfig(
        workspace=ws,
        status_file=(ws / args.status_file).resolve(),
        risk_file=(ws / args.risk_file).resolve(),
        policy_file=(ws / args.policy_file).resolve(),
        runstate_file=(ws / args.runstate_file).resolve(),
        mode=args.mode,
        max_steps=args.max_steps,
        allow_risky_gates=args.allow_risky_gates,
        ci_timeout_seconds=args.ci_timeout_seconds,
        ci_poll_interval_seconds=args.ci_poll_interval_seconds,
        max_retries=args.max_retries,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    cfg = build_config(args)
    ledger = JsonFileLedgerGateway(cfg.status_file)
    runstate = JsonRunStateStore(cfg.runstate_file)
    executor = SubprocessCommandExecutor()
    ci = LocalCIGateway(cfg.workspace, executor)
    policy = load_policy(cfg.policy_file)

    runner = AutoRunner(cfg, ledger, runstate, executor, ci, policy)
    report = runner.run()
    print(json.dumps(report, indent=2, ensure_ascii=False))

    suggested = report.get("details", {}).get("suggested_exit_code", int(ExitCode.SUCCESS))
    return int(suggested)


if __name__ == "__main__":
    raise SystemExit(main())

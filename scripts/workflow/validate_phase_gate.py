#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS = ROOT / "plans/execution-platform-status.yaml"
DEFAULT_RISKS = ROOT / "plans/execution-platform-risk-register.yaml"
VALID_STATUSES = {"planned", "todo", "in_progress", "blocked", "completed", "cancelled"}
VALID_CHECKPOINT_STATUSES = {"todo", "in_progress", "passed", "failed", "waived"}


def load_yaml_like_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"Empty data file: {path}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} must contain JSON-compatible YAML. {exc}") from exc


def validate_plan(status_data: dict[str, Any], risk_data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    program = status_data.get("program", {})
    phases = status_data.get("phases", [])
    risks = risk_data.get("risks", [])

    if not program.get("current_phase"):
        errors.append("program.current_phase is required")
    if not program.get("current_sprint"):
        errors.append("program.current_sprint is required")
    if not phases:
        errors.append("At least one phase is required")

    phase_ids: set[str] = set()
    sprint_ids: set[str] = set()
    issue_ids: set[str] = set()

    for phase in phases:
        phase_id = phase.get("id")
        if not phase_id:
            errors.append("Phase missing id")
            continue
        if phase_id in phase_ids:
            errors.append(f"Duplicate phase id: {phase_id}")
        phase_ids.add(phase_id)

        for sprint in phase.get("sprints", []):
            sprint_id = sprint.get("id")
            if not sprint_id:
                errors.append(f"Phase {phase_id} contains sprint without id")
                continue
            if sprint_id in sprint_ids:
                errors.append(f"Duplicate sprint id: {sprint_id}")
            sprint_ids.add(sprint_id)

            for issue in sprint.get("issues", []):
                issue_id = issue.get("id")
                if not issue_id:
                    errors.append(f"Sprint {sprint_id} contains issue without id")
                    continue
                if issue_id in issue_ids:
                    errors.append(f"Duplicate issue id: {issue_id}")
                issue_ids.add(issue_id)

                status = issue.get("status")
                if status not in VALID_STATUSES:
                    errors.append(f"Issue {issue_id} has invalid status: {status}")

                for checkpoint in issue.get("checkpoints", []):
                    cp_status = checkpoint.get("status")
                    if cp_status not in VALID_CHECKPOINT_STATUSES:
                        errors.append(f"Issue {issue_id} has invalid checkpoint status: {cp_status}")

    if program.get("current_phase") not in phase_ids:
        errors.append(f"current_phase not found: {program.get('current_phase')}")
    if program.get("current_sprint") not in sprint_ids:
        errors.append(f"current_sprint not found: {program.get('current_sprint')}")

    for phase in phases:
        for sprint in phase.get("sprints", []):
            for issue in sprint.get("issues", []):
                for dependency in issue.get("dependencies", []):
                    if dependency not in issue_ids:
                        errors.append(f"Issue {issue.get('id')} depends on missing issue: {dependency}")

    risk_ids: set[str] = set()
    for risk in risks:
        risk_id = risk.get("id")
        if not risk_id:
            errors.append("Risk missing id")
            continue
        if risk_id in risk_ids:
            errors.append(f"Duplicate risk id: {risk_id}")
        risk_ids.add(risk_id)
        for linked_sprint in risk.get("linked_sprints", []):
            if linked_sprint not in sprint_ids:
                errors.append(f"Risk {risk_id} references missing sprint: {linked_sprint}")

    return errors


def validate_sprint_gate(status_data: dict[str, Any], risk_data: dict[str, Any], sprint_id: str) -> list[str]:
    issues = []
    for phase in status_data.get("phases", []):
        for sprint in phase.get("sprints", []):
            if sprint.get("id") == sprint_id:
                issues = sprint.get("issues", [])
                break
    errors: list[str] = []
    if not issues:
        errors.append(f"No issues found for sprint {sprint_id}")
        return errors

    incomplete = [issue.get("id") for issue in issues if issue.get("status") not in {"completed", "cancelled"}]
    if incomplete:
        errors.append(f"Sprint {sprint_id} has incomplete issues: {', '.join(incomplete)}")

    blocking_risks = [
        risk.get("id")
        for risk in risk_data.get("risks", [])
        if sprint_id in risk.get("linked_sprints", [])
        and risk.get("status") in {"open", "watch"}
        and risk.get("severity") in {"critical", "high"}
    ]
    if blocking_risks:
        errors.append(f"Sprint {sprint_id} has unresolved high/critical risks: {', '.join(blocking_risks)}")
    return errors


def classify_error(msg: str) -> str:
    """Map a validation error message to an error code."""
    if "missing id" in msg.lower() or "duplicate" in msg.lower() or "invalid status" in msg.lower():
        return "E_SCHEMA"
    if "depends on missing" in msg.lower():
        return "E_DEPENDENCY"
    if "unresolved high/critical risks" in msg.lower():
        return "E_RISK_BLOCKING"
    if "incomplete issues" in msg.lower():
        return "E_DEPENDENCY"
    if "not found" in msg.lower():
        return "E_SCHEMA"
    return "E_UNKNOWN"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate execution-platform plan and sprint gates.")
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--risk-file", type=Path, default=DEFAULT_RISKS)
    parser.add_argument("--mode", choices=["plan", "sprint"], default="plan")
    parser.add_argument("--sprint-id", default=None)
    parser.add_argument("--output-json", type=Path, default=None, help="Write structured errors to JSON file")
    args = parser.parse_args()

    status_data = load_yaml_like_json(args.status_file)
    risk_data = load_yaml_like_json(args.risk_file)

    errors = validate_plan(status_data, risk_data)
    if args.mode == "sprint":
        sprint_id = args.sprint_id or status_data.get("program", {}).get("current_sprint")
        errors.extend(validate_sprint_gate(status_data, risk_data, sprint_id))

    if args.output_json:
        structured = [
            {"code": classify_error(e), "message": e} for e in errors
        ]
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps({"mode": args.mode, "ok": len(errors) == 0, "errors": structured}, indent=2),
            encoding="utf-8",
        )

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"Validation passed for mode={args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS = ROOT / "plans/execution-platform-status.yaml"
DEFAULT_RISKS = ROOT / "plans/execution-platform-risk-register.yaml"
DEFAULT_METRICS = ROOT / ".github/knowledge/metrics.md"
DEFAULT_ITERATION = ROOT / ".github/knowledge/iteration-log.md"

METRICS_START = "<!-- execution-platform:metrics:start -->"
METRICS_END = "<!-- execution-platform:metrics:end -->"
ITERATION_START = "<!-- execution-platform:iteration:start -->"
ITERATION_END = "<!-- execution-platform:iteration:end -->"


def load_yaml_like_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"Empty data file: {path}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} must contain JSON-compatible YAML. {exc}") from exc


def flatten_issues(status_data: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for phase in status_data.get("phases", []):
        for sprint in phase.get("sprints", []):
            for issue in sprint.get("issues", []):
                enriched = dict(issue)
                enriched["phase_id"] = phase.get("id")
                enriched["phase_name"] = phase.get("name")
                enriched["sprint_id"] = sprint.get("id")
                enriched["sprint_name"] = sprint.get("name")
                issues.append(enriched)
    return issues


def find_current_sprint(status_data: dict[str, Any]) -> dict[str, Any] | None:
    current_sprint_id = status_data.get("program", {}).get("current_sprint")
    for phase in status_data.get("phases", []):
        for sprint in phase.get("sprints", []):
            if sprint.get("id") == current_sprint_id:
                return sprint
    return None


def build_snapshot(status_data: dict[str, Any], risk_data: dict[str, Any]) -> dict[str, Any]:
    issues = flatten_issues(status_data)
    issue_counts = Counter(issue.get("status", "unknown") for issue in issues)
    checkpoints = Counter(
        checkpoint.get("status", "unknown")
        for issue in issues
        for checkpoint in issue.get("checkpoints", [])
    )
    risks = risk_data.get("risks", [])
    open_risks = [r for r in risks if r.get("status") in {"open", "watch"}]
    current_sprint = find_current_sprint(status_data)
    current_issues = current_sprint.get("issues", []) if current_sprint else []

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current_phase": status_data.get("program", {}).get("current_phase"),
        "current_sprint": status_data.get("program", {}).get("current_sprint"),
        "program_status": status_data.get("program", {}).get("status"),
        "issue_counts": dict(issue_counts),
        "checkpoint_counts": dict(checkpoints),
        "open_risks": len(open_risks),
        "critical_open_risks": len([r for r in open_risks if r.get("severity") == "critical"]),
        "high_open_risks": len([r for r in open_risks if r.get("severity") == "high"]),
        "current_issues": current_issues,
        "current_sprint_goal": current_sprint.get("goal") if current_sprint else None,
    }


def build_metrics_block(snapshot: dict[str, Any]) -> str:
    issue_counts = snapshot["issue_counts"]
    checkpoint_counts = snapshot["checkpoint_counts"]
    total_issues = sum(issue_counts.values())
    lines = [
        "_Managed by `scripts/workflow/sync_execution_status.py`. Do not edit inside this block manually._",
        f"- **Last Sync**: {snapshot['generated_at']}",
        f"- **Current Phase**: `{snapshot['current_phase']}`",
        f"- **Current Sprint**: `{snapshot['current_sprint']}`",
        f"- **Program Status**: `{snapshot['program_status']}`",
        f"- **Total Tracked Issues**: {total_issues}",
        f"- **Issues Completed**: {issue_counts.get('completed', 0)}",
        f"- **Issues In Progress**: {issue_counts.get('in_progress', 0)}",
        f"- **Issues Blocked**: {issue_counts.get('blocked', 0)}",
        f"- **Open/Watch Risks**: {snapshot['open_risks']}",
        f"- **Critical Open Risks**: {snapshot['critical_open_risks']}",
        f"- **High Open Risks**: {snapshot['high_open_risks']}",
        f"- **Checkpoints Passed**: {checkpoint_counts.get('passed', 0)}",
        f"- **Checkpoints Failed**: {checkpoint_counts.get('failed', 0)}",
        f"- **Checkpoints Pending/In Progress**: {checkpoint_counts.get('todo', 0) + checkpoint_counts.get('in_progress', 0)}",
    ]
    return "\n".join(lines)


def build_iteration_block(snapshot: dict[str, Any]) -> str:
    lines = [
        "_Managed by `scripts/workflow/sync_execution_status.py`. Do not edit inside this block manually._",
        f"- **Last Sync**: {snapshot['generated_at']}",
        f"- **Active Sprint**: `{snapshot['current_sprint']}`",
        f"- **Sprint Goal**: {snapshot['current_sprint_goal'] or 'N/A'}",
        "- **Tracked Issues**:",
    ]
    current_issues = snapshot.get("current_issues", [])
    if not current_issues:
        lines.append("  - None")
    else:
        for issue in current_issues:
            lines.append(f"  - `{issue.get('id')}` — {issue.get('title')} ({issue.get('status')})")
    return "\n".join(lines)


def replace_or_append_block(path: Path, start_marker: str, end_marker: str, heading: str, content: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = f"{start_marker}\n{content}\n{end_marker}"
    if start_marker in text and end_marker in text:
        prefix, remainder = text.split(start_marker, 1)
        _, suffix = remainder.split(end_marker, 1)
        new_text = f"{prefix}{block}{suffix}"
    else:
        separator = "\n\n" if text and not text.endswith("\n") else "\n"
        new_text = f"{text}{separator}{heading}\n\n{block}\n"
    path.write_text(new_text, encoding="utf-8")


def apply_status_overrides(status_data: dict[str, Any], issue_overrides: list[str], checkpoint_overrides: list[str]) -> list[str]:
    """Apply --set-issue-status and --set-checkpoint-status overrides to ledger data in-place.

    issue_overrides: ["ISSUE_ID=STATUS", ...]
    checkpoint_overrides: ["ISSUE_ID:CP_ID=STATUS", ...]
    Returns list of warning messages for unresolved IDs.
    """
    warnings: list[str] = []

    for override in issue_overrides:
        if "=" not in override:
            warnings.append(f"Invalid format (expected ISSUE_ID=STATUS): {override}")
            continue
        issue_id, status = override.split("=", 1)
        found = False
        for phase in status_data.get("phases", []):
            for sprint in phase.get("sprints", []):
                for issue in sprint.get("issues", []):
                    if issue.get("id") == issue_id:
                        issue["status"] = status
                        found = True
                        break
        if not found:
            warnings.append(f"Issue not found: {issue_id}")

    for override in checkpoint_overrides:
        if "=" not in override:
            warnings.append(f"Invalid format (expected ISSUE_ID:CP_ID=STATUS): {override}")
            continue
        key, status = override.split("=", 1)
        if ":" not in key:
            warnings.append(f"Invalid format (expected ISSUE_ID:CP_ID): {key}")
            continue
        issue_id, cp_id = key.split(":", 1)
        found = False
        for phase in status_data.get("phases", []):
            for sprint in phase.get("sprints", []):
                for issue in sprint.get("issues", []):
                    if issue.get("id") == issue_id:
                        for cp in issue.get("checkpoints", []):
                            if cp.get("id") == cp_id:
                                cp["status"] = status
                                found = True
                                break
        if not found:
            warnings.append(f"Checkpoint not found: {issue_id}:{cp_id}")

    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync execution-platform delivery status into knowledge artifacts.")
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--risk-file", type=Path, default=DEFAULT_RISKS)
    parser.add_argument("--metrics-file", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--iteration-log", type=Path, default=DEFAULT_ITERATION)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--set-issue-status", action="append", default=[], metavar="ISSUE_ID=STATUS",
                        help="Set issue status before syncing (repeatable)")
    parser.add_argument("--set-checkpoint-status", action="append", default=[], metavar="ISSUE_ID:CP_ID=STATUS",
                        help="Set checkpoint status before syncing (repeatable)")
    args = parser.parse_args()

    status_data = load_yaml_like_json(args.status_file)
    risk_data = load_yaml_like_json(args.risk_file)

    # Apply write-back overrides
    if args.set_issue_status or args.set_checkpoint_status:
        warnings = apply_status_overrides(status_data, args.set_issue_status, args.set_checkpoint_status)
        for w in warnings:
            print(f"WARNING: {w}")
        if not args.dry_run:
            from datetime import datetime as _dt, timezone as _tz
            status_data.setdefault("program", {})["last_synced_at"] = _dt.now(_tz.utc).isoformat()
            args.status_file.write_text(json.dumps(status_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    snapshot = build_snapshot(status_data, risk_data)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    if not args.dry_run:
        replace_or_append_block(
            args.metrics_file,
            METRICS_START,
            METRICS_END,
            "## ExecutionView Platform Delivery Tracking",
            build_metrics_block(snapshot),
        )
        replace_or_append_block(
            args.iteration_log,
            ITERATION_START,
            ITERATION_END,
            "## ExecutionView Platform Delivery Snapshot",
            build_iteration_block(snapshot),
        )

    print(json.dumps(snapshot, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

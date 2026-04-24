#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS = ROOT / ".workbuddy/plans/execution-platform-status.yaml"
DEFAULT_RISKS = ROOT / ".workbuddy/plans/execution-platform-risk-register.yaml"
DEFAULT_OUTPUT = ROOT / "docs/generated/execution-platform-handoff.md"


def load_yaml_like_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"Empty data file: {path}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} must contain JSON-compatible YAML. {exc}") from exc


def find_current_sprint(status_data: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    current_sprint_id = status_data.get("program", {}).get("current_sprint")
    for phase in status_data.get("phases", []):
        for sprint in phase.get("sprints", []):
            if sprint.get("id") == current_sprint_id:
                return phase, sprint
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a sprint-aware handoff snapshot.")
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--risk-file", type=Path, default=DEFAULT_RISKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    status_data = load_yaml_like_json(args.status_file)
    risk_data = load_yaml_like_json(args.risk_file)
    phase, sprint = find_current_sprint(status_data)

    generated_at = datetime.now(timezone.utc).isoformat()
    issues = sprint.get("issues", []) if sprint else []
    active_risks = [
        risk for risk in risk_data.get("risks", [])
        if (sprint and sprint.get("id") in risk.get("linked_sprints", [])) and risk.get("status") in {"open", "watch"}
    ]

    lines = [
        "# ExecutionView Platform Handoff Snapshot",
        "",
        f"**Generated**: {generated_at}",
        f"**Current Phase**: `{phase.get('id') if phase else 'unknown'}` - {phase.get('name') if phase else 'Unknown'}",
        f"**Current Sprint**: `{sprint.get('id') if sprint else 'unknown'}` - {sprint.get('name') if sprint else 'Unknown'}",
        "",
        "## Sprint Goal",
        "",
        sprint.get("goal", "No sprint goal recorded.") if sprint else "No active sprint found.",
        "",
        "## Issue Status",
        "",
        "| Issue | Status | Depends On | Files |",
        "|---|---|---|---|",
    ]

    if issues:
        for issue in issues:
            dependencies = ", ".join(issue.get("dependencies", [])) or "—"
            file_count = len(issue.get("files", []))
            lines.append(f"| `{issue.get('id')}` | {issue.get('status')} | {dependencies} | {file_count} |")
    else:
        lines.append("| — | — | — | — |")

    lines.extend([
        "",
        "## Active Sprint Risks",
        "",
        "| Risk | Severity | Status | Mitigation |",
        "|---|---|---|---|",
    ])

    if active_risks:
        for risk in active_risks:
            lines.append(
                f"| `{risk.get('id')}` | {risk.get('severity')} | {risk.get('status')} | {risk.get('mitigation')} |"
            )
    else:
        lines.append("| — | — | — | No sprint-linked open risks |")

    lines.extend([
        "",
        "## Next Actions",
        "",
    ])

    # Dynamic next actions from current sprint issues
    action_num = 0
    todo_issues = [i for i in issues if i.get("status") == "todo"]
    in_progress_issues = [i for i in issues if i.get("status") == "in_progress"]
    blocked_issues = [i for i in issues if i.get("status") == "blocked"]

    for issue in in_progress_issues:
        action_num += 1
        lines.append(f"{action_num}. Continue work on `{issue.get('id')}` — {issue.get('title')} (in_progress).")

    for issue in blocked_issues:
        action_num += 1
        lines.append(f"{action_num}. Unblock `{issue.get('id')}` — {issue.get('title')} (blocked).")

    for issue in todo_issues:
        action_num += 1
        lines.append(f"{action_num}. Start `{issue.get('id')}` — {issue.get('title')} (todo).")

    if not in_progress_issues and not todo_issues and not blocked_issues:
        action_num += 1
        lines.append(f"{action_num}. All issues in the current sprint are completed. Proceed to sprint gate validation.")

    action_num += 1
    lines.append(f"{action_num}. Validate the plan ledger with `validate_phase_gate.py --mode plan`.")
    action_num += 1
    lines.append(f"{action_num}. Run `sync_execution_status.py` to refresh metrics and iteration-log sections.")

    lines.extend([
        "",
        f"- `{args.status_file.as_posix()}`",
        f"- `{args.risk_file.as_posix()}`",
    ])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.output.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Sync metrics baseline from knowledge files back into metrics.md.

Usage:
    python scripts/ops/sync-metrics.py

Scans error-patterns.md and user-needs.md, counts entries by status,
updates metrics.md counters, and rolls forward an expired assessment date.
Safe to run multiple times (idempotent).
"""

import os
import re
from datetime import datetime, timedelta

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
KNOWLEDGE_DIR = os.path.join(REPO_ROOT, ".github", "knowledge")
METRICS_PATH = os.path.join(KNOWLEDGE_DIR, "metrics.md")


def count_markdown_entries(path: str, heading_prefix: str) -> dict:
    """Count markdown entries and their statuses."""
    if not os.path.exists(path):
        return {"total": 0, "by_status": {}}

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find all headings like ## Pattern: ... or ## Need: ...
    heading_pattern = re.compile(rf"^## {heading_prefix}:\s*(.+)$", re.MULTILINE)
    status_pattern = re.compile(r"^-\s*\*\*Status\*\*:\s*(.+)$", re.MULTILINE)

    headings = list(heading_pattern.finditer(content))
    statuses = list(status_pattern.finditer(content))

    total = len(headings)
    by_status: dict[str, int] = {}

    # Naive pairing: assume statuses appear in same order as headings
    for i, st in enumerate(statuses):
        if i >= total:
            break
        status = st.group(1).strip()
        by_status[status] = by_status.get(status, 0) + 1

    return {"total": total, "by_status": by_status}


def update_metrics_file(
    patterns_total: int,
    patterns_resolved: int,
    needs_total: int,
    needs_automated: int,
) -> str:
    """Read metrics.md, update counters, write back. Returns a summary."""
    if not os.path.exists(METRICS_PATH):
        return "metrics.md not found."

    with open(METRICS_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    today_str = datetime.now().strftime("%Y-%m-%d")
    next_due_str = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    def repl_field(pattern: str, new_value: str) -> None:
        nonlocal content
        def _repl(m: re.Match) -> str:
            return m.group(1) + new_value
        content = re.sub(
            rf"^({pattern}\s*).*?$",
            _repl,
            content,
            flags=re.MULTILINE,
        )

    # Update date
    repl_field(r"(- \*\*Date\*\*:\s*)", today_str)
    repl_field(r"(- \*\*Assessor\*\*:\s*)", "Auto-sync")

    # Update error resolution metrics
    repl_field(r"(- \*\*Total Patterns Recorded\*\*:\s*)", str(patterns_total))
    repl_field(r"(- \*\*Patterns Resolved\*\*:\s*)", str(patterns_resolved))

    # Update user needs metrics
    repl_field(r"(- \*\*Total Needs Identified\*\*:\s*)", str(needs_total))
    repl_field(r"(- \*\*Needs Automated\*\*:\s*)", str(needs_automated))

    # Roll forward expired assessment date
    due_match = re.search(r"^(- \*\*Next Assessment Due\*\*:\s*)(\d{4}-\d{2}-\d{2})$", content, re.MULTILINE)
    if due_match:
        due_date = datetime.strptime(due_match.group(2), "%Y-%m-%d")
        if due_date < datetime.now():
            repl_field(r"(- \*\*Next Assessment Due\*\*:\s*)", next_due_str)

    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    return (
        f"Metrics synced: "
        f"Patterns={patterns_total} (Resolved={patterns_resolved}), "
        f"Needs={needs_total} (Automated={needs_automated})"
    )


def main() -> None:
    patterns = count_markdown_entries(
        os.path.join(KNOWLEDGE_DIR, "error-patterns.md"), "Pattern"
    )
    needs = count_markdown_entries(
        os.path.join(KNOWLEDGE_DIR, "user-needs.md"), "Need"
    )

    summary = update_metrics_file(
        patterns_total=patterns["total"],
        patterns_resolved=patterns["by_status"].get("Resolved", 0),
        needs_total=needs["total"],
        needs_automated=needs["by_status"].get("Automated", 0),
    )
    print(summary)


if __name__ == "__main__":
    main()

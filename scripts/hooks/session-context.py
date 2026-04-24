"""
SessionStart hook: Inject knowledge base summary into agent context.

Reads the knowledge base files and outputs a condensed summary as a systemMessage.
Runs at the start of every agent session.
"""

import json
import os
import subprocess
import sys

# Auto-sync metrics baseline before generating context
_SYNC_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "sync-metrics.py")
if os.path.exists(_SYNC_SCRIPT):
    try:
        subprocess.run(
            [sys.executable, _SYNC_SCRIPT],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except Exception:
        pass  # Fail silently so session context is never blocked

KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", ".github", "knowledge")

MAX_PATTERNS = 5
MAX_NEEDS = 5
MAX_LOG_ENTRIES = 15


def read_file_safe(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, PermissionError):
        return ""


def extract_patterns(content: str) -> list[str]:
    """Extract pattern names and statuses from error-patterns.md."""
    patterns = []
    current_name = ""
    for line in content.splitlines():
        if line.startswith("## Pattern:"):
            current_name = line.replace("## Pattern:", "").strip()
        elif line.startswith("- **Status**:") and current_name:
            status = line.replace("- **Status**:", "").strip()
            patterns.append(f"  - {current_name} [{status}]")
            current_name = ""
    return patterns[:MAX_PATTERNS]


def extract_needs(content: str) -> list[str]:
    """Extract need names and statuses from user-needs.md."""
    needs = []
    current_name = ""
    for line in content.splitlines():
        if line.startswith("## Need:"):
            current_name = line.replace("## Need:", "").strip()
        elif line.startswith("- **Status**:") and current_name:
            status = line.replace("- **Status**:", "").strip()
            needs.append(f"  - {current_name} [{status}]")
            current_name = ""
    return needs[:MAX_NEEDS]


def extract_recent_log(content: str) -> list[str]:
    """Extract last N log entries from iteration-log.md."""
    lines = content.strip().splitlines()
    # Skip header lines (title, description, blank, table header, separator)
    data_lines = [l for l in lines if l.startswith("|") and not l.startswith("| Date") and "---" not in l]
    return data_lines[-MAX_LOG_ENTRIES:]


def extract_metrics_summary(content: str) -> str:
    """Extract key metrics from metrics.md."""
    lines = content.splitlines()
    summary_parts = []
    for line in lines:
        if line.startswith("- **Next Assessment Due**:"):
            summary_parts.append(line.strip("- ").strip())
        elif line.startswith("- **Total Patterns Recorded**:"):
            summary_parts.append(f"Error Patterns: {line.split(':')[1].strip()}")
        elif line.startswith("- **Needs Automated**:"):
            summary_parts.append(f"Needs Automated: {line.split(':')[1].strip()}")
        elif line.startswith("- **Technical Debt Items**:"):
            summary_parts.append(f"Tech Debt: {line.split(':')[1].strip()}")
    return "; ".join(summary_parts) if summary_parts else "No metrics available"


def main():
    patterns_content = read_file_safe(os.path.join(KNOWLEDGE_DIR, "error-patterns.md"))
    needs_content = read_file_safe(os.path.join(KNOWLEDGE_DIR, "user-needs.md"))
    log_content = read_file_safe(os.path.join(KNOWLEDGE_DIR, "iteration-log.md"))
    metrics_content = read_file_safe(os.path.join(KNOWLEDGE_DIR, "metrics.md"))

    parts = ["[Iterative Update Mechanism — Session Context]"]

    patterns = extract_patterns(patterns_content)
    if patterns:
        parts.append("Known Error Patterns:")
        parts.extend(patterns)

    needs = extract_needs(needs_content)
    if needs:
        parts.append("Tracked User Needs:")
        parts.extend(needs)

    recent_log = extract_recent_log(log_content)
    if recent_log:
        parts.append(f"Recent Iterations ({len(recent_log)} entries):")
        parts.extend(f"  {entry}" for entry in recent_log[-5:])

    metrics_summary = extract_metrics_summary(metrics_content)
    parts.append(f"Metrics: {metrics_summary}")

    parts.append("Consult .github/knowledge/ for full details. Follow .github/copilot-instructions.md for update rules.")

    message = "\n".join(parts)
    output = {"systemMessage": message}
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()

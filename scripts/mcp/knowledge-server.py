"""
EMSXView Knowledge Base MCP Server.

A Model Context Protocol (stdio) server that provides tools for reading and
writing the iterative update knowledge base in .github/knowledge/.

Tools:
  - search_error_patterns: Fuzzy search error patterns
  - add_error_pattern: Add a new error pattern entry
  - search_user_needs: Search tracked user needs
  - add_user_need: Add or update a user need
  - get_iteration_log: Get recent iteration log entries
  - add_iteration_entry: Append an iteration log entry
  - get_metrics: Get current self-assessment metrics
  - analyze_logs: Search application logs for error patterns
"""

import os
import re
from datetime import datetime

from mcp.server.fastmcp import FastMCP

# Knowledge base directory (relative to workspace root)
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
KNOWLEDGE_DIR = os.path.join(WORKSPACE_ROOT, ".github", "knowledge")

# Validate paths stay within workspace
def _safe_path(filename: str) -> str:
    """Ensure the path is within the knowledge directory. Prevents path traversal."""
    safe_name = os.path.basename(filename)
    path = os.path.join(KNOWLEDGE_DIR, safe_name)
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(KNOWLEDGE_DIR)):
        raise ValueError(f"Path traversal blocked: {filename}")
    return path


def _safe_log_path(log_path: str) -> str:
    """Ensure log path is within the workspace. Prevents path traversal."""
    full = os.path.join(WORKSPACE_ROOT, log_path)
    real = os.path.realpath(full)
    if not real.startswith(os.path.realpath(WORKSPACE_ROOT)):
        raise ValueError(f"Path traversal blocked: {log_path}")
    return real


def _read_file(filename: str) -> str:
    path = _safe_path(filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _append_file(filename: str, text: str):
    path = _safe_path(filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


# --- MCP Server ---

mcp = FastMCP(
    "emsx-knowledge",
    version="1.0.0",
    description="EMSXView Trading Platform — Iterative Update Knowledge Base",
)


@mcp.tool()
def search_error_patterns(query: str) -> str:
    """Search error patterns knowledge base for matching entries.

    Args:
        query: Search term (matched case-insensitively against pattern names, signatures, and root causes)

    Returns:
        Matching pattern sections, or 'No matches found'
    """
    content = _read_file("error-patterns.md")
    if not content:
        return "Knowledge base empty or not found."

    # Split into pattern sections
    sections = re.split(r"(?=^## Pattern:)", content, flags=re.MULTILINE)
    query_lower = query.lower()
    matches = [s.strip() for s in sections if query_lower in s.lower()]

    if not matches:
        return "No matches found."
    return "\n\n---\n\n".join(matches)


@mcp.tool()
def add_error_pattern(
    name: str,
    signature: str,
    root_cause: str,
    resolution: str,
    files: str,
    lessons: str,
) -> str:
    """Add a new error pattern to the knowledge base.

    Args:
        name: Descriptive name for the pattern
        signature: Error message, exception type, and trigger conditions
        root_cause: Why the error occurs
        resolution: Step-by-step fix (use numbered list)
        files: Comma-separated file paths involved
        lessons: What to watch for to prevent recurrence

    Returns:
        Confirmation message
    """
    # Check for duplicate
    content = _read_file("error-patterns.md")
    if f"## Pattern: {name}" in content:
        return f"Pattern '{name}' already exists. Update it manually or use a different name."

    date = datetime.now().strftime("%Y-%m-%d")
    entry = f"""

---

## Pattern: {name}

- **Signature**: {signature}
- **Root Cause**: {root_cause}
- **Resolution**:
{resolution}
- **Status**: Resolved
- **Date**: {date}
- **Files**: {files}
- **Lessons**: {lessons}
"""
    _append_file("error-patterns.md", entry)
    return f"Added pattern '{name}' to error-patterns.md."


@mcp.tool()
def search_user_needs(query: str) -> str:
    """Search user needs knowledge base for matching entries.

    Args:
        query: Search term (matched case-insensitively against need names, solutions, and statuses)

    Returns:
        Matching need sections, or 'No matches found'
    """
    content = _read_file("user-needs.md")
    if not content:
        return "Knowledge base empty or not found."

    sections = re.split(r"(?=^## Need:)", content, flags=re.MULTILINE)
    query_lower = query.lower()
    matches = [s.strip() for s in sections if query_lower in s.lower()]

    if not matches:
        return "No matches found."
    return "\n\n---\n\n".join(matches)


@mcp.tool()
def add_user_need(
    name: str,
    frequency: str,
    impact: str,
    current_solution: str,
    proposed_automation: str,
) -> str:
    """Add or update a user need in the knowledge base.

    Args:
        name: Descriptive name for the need
        frequency: How often this need occurs (e.g., 'High', 'Medium', 'Low', or 1-5)
        impact: Business impact when unaddressed (e.g., 'High', 'Medium', 'Low', or 1-5)
        current_solution: How the need is currently addressed manually
        proposed_automation: Suggested automation approach

    Returns:
        Confirmation message
    """
    content = _read_file("user-needs.md")
    if f"## Need: {name}" in content:
        return f"Need '{name}' already exists. Update it manually or use a different name."

    date = datetime.now().strftime("%Y-%m-%d")
    entry = f"""

---

## Need: {name}

- **Frequency**: {frequency}
- **Impact**: {impact}
- **Effort**: TBD
- **Current Solution**: {current_solution}
- **Proposed Automation**: {proposed_automation}
- **Status**: Identified
- **Date**: {date}
"""
    _append_file("user-needs.md", entry)
    return f"Added need '{name}' to user-needs.md."


@mcp.tool()
def get_iteration_log(last_n: int = 20) -> str:
    """Get recent entries from the iteration log.

    Args:
        last_n: Number of recent entries to return (default: 20)

    Returns:
        Table-formatted recent log entries
    """
    content = _read_file("iteration-log.md")
    if not content:
        return "Iteration log empty or not found."

    lines = content.strip().splitlines()
    # Separate header and data
    header_lines = []
    data_lines = []
    for line in lines:
        if line.startswith("|") and ("Date" in line or "---" in line):
            header_lines.append(line)
        elif line.startswith("|"):
            data_lines.append(line)

    recent = data_lines[-last_n:]
    return "\n".join(header_lines + recent) if recent else "No log entries found."


@mcp.tool()
def add_iteration_entry(
    entry_type: str,
    trigger: str,
    action: str,
    outcome: str,
) -> str:
    """Append an entry to the iteration log.

    Args:
        entry_type: Category — one of: error, need, architecture, task, mechanism, session
        trigger: What initiated this iteration (e.g., 'test failure', 'user request', 'scheduled review')
        action: What was done
        outcome: Result of the action

    Returns:
        Confirmation message
    """
    valid_types = {"error", "need", "architecture", "task", "mechanism", "session"}
    if entry_type not in valid_types:
        return f"Invalid type '{entry_type}'. Must be one of: {', '.join(sorted(valid_types))}"

    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"| {date} | {entry_type} | {trigger} | {action} | {outcome} | manual |\n"
    _append_file("iteration-log.md", entry)
    return f"Logged iteration entry: [{entry_type}] {action}"


@mcp.tool()
def get_metrics() -> str:
    """Get current self-assessment metrics from the knowledge base.

    Returns:
        Full contents of metrics.md
    """
    content = _read_file("metrics.md")
    return content if content else "Metrics file empty or not found."


@mcp.tool()
def analyze_logs(log_path: str, pattern: str) -> str:
    """Search application logs for error patterns.

    Args:
        log_path: Relative path to log file from workspace root (e.g., 'logs/emsx_api.log')
        pattern: Regex pattern to search for in the log file

    Returns:
        Matching log lines (max 50)
    """
    try:
        full_path = _safe_log_path(log_path)
    except ValueError as e:
        return str(e)

    if not os.path.exists(full_path):
        return f"Log file not found: {log_path}"

    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid regex pattern: {e}"

    matches = []
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            for line_num, line in enumerate(f, 1):
                if compiled.search(line):
                    matches.append(f"L{line_num}: {line.rstrip()}")
                    if len(matches) >= 50:
                        break
    except PermissionError:
        return f"Permission denied: {log_path}"

    if not matches:
        return f"No matches for pattern '{pattern}' in {log_path}"
    return f"Found {len(matches)} matches:\n" + "\n".join(matches)


if __name__ == "__main__":
    mcp.run(transport="stdio")

"""
PostToolUse hook: Log file changes to the iteration log for learning.

Receives PostToolUse JSON on stdin, extracts relevant info for file edit tools,
and appends an entry to the iteration log.
"""

import json
import os
import sys
from datetime import datetime

ITERATION_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", ".github", "knowledge", "iteration-log.md"
)

# Tool names that indicate file modifications
EDIT_TOOLS = {"replace_string_in_file", "create_file", "edit_notebook_file", "multi_replace_string_in_file"}


def append_log_entry(tool_name: str, file_path: str, summary: str):
    """Append an entry to iteration-log.md."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"| {date} | task | PostToolUse:{tool_name} | Edited `{file_path}` | {summary} | auto |\n"
    try:
        with open(ITERATION_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
    except (FileNotFoundError, PermissionError):
        pass  # Fail silently — hook must not block agent


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    tool_name = input_data.get("toolName", "")
    tool_input = input_data.get("toolInput", {})

    if tool_name in EDIT_TOOLS:
        file_path = tool_input.get("filePath", tool_input.get("path", "unknown"))
        # Use just the filename for brevity
        short_path = os.path.basename(file_path) if file_path else "unknown"
        append_log_entry(tool_name, short_path, "File modified")

    # Always continue
    output = {"continue": True}
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()

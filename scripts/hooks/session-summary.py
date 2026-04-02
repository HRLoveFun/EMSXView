"""
Stop hook: Generate a session summary and append to the iteration log.

Runs when an agent session ends. Produces a summary entry in iteration-log.md
marking the session boundary.
"""

import json
import os
import sys
from datetime import datetime

ITERATION_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", ".github", "knowledge", "iteration-log.md"
)


def append_session_boundary():
    """Append a session boundary entry to iteration-log.md."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"| {date} | session | Stop | Session ended | — | auto |\n"
    try:
        with open(ITERATION_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
    except (FileNotFoundError, PermissionError):
        pass  # Fail silently


def main():
    # Read stdin (may contain session context)
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    append_session_boundary()

    output = {"continue": True}
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()

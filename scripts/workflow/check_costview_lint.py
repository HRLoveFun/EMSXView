#!/usr/bin/env python3
"""CI lint check for CostView database subsystem constraints.

Checks:
    1. No ``sqlite3.connect()`` calls outside allowed storage dirs
2. (Future) No direct ``from CostView.src.*`` imports in ``platform_data/``
3. (Future) Table name consistency

Exit code 0 = pass, 1 = violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_SQLITE_CONNECT_DIRS = {
    "DataPipeline/src/storage",       # Storage layer — ConnectionManager + repos
    "platform_data",                  # DatabaseView diagnostic reader (file-level inspection)
}
VIOLATIONS: list[str] = []


def check_sqlite3_connect() -> None:
    """Ensure sqlite3.connect() is only called from allowed directories."""
    pattern = re.compile(r"sqlite3\.connect\(")
    source_roots = [
        ROOT / "DataPipeline/src",
        ROOT / "platform_data",
    ]

    for root in source_roots:
        if not root.exists():
            continue
        for py_file in sorted(root.rglob("*.py")):
            # Skip __pycache__
            if "__pycache__" in py_file.parts:
                continue
            rel = py_file.relative_to(ROOT)
            # Normalize to POSIX separators for cross-platform matching
            rel_posix = str(rel).replace("\\", "/")
            allowed = any(
                rel_posix.startswith(d) for d in ALLOWED_SQLITE_CONNECT_DIRS
            )
            if allowed:
                continue

            content = py_file.read_text(encoding="utf-8")
            for lineno, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    VIOLATIONS.append(
                        f"{rel}:{lineno}: sqlite3.connect() outside allowed dirs "
                        f"({', '.join(sorted(ALLOWED_SQLITE_CONNECT_DIRS))})"
                    )


def main() -> int:
    check_sqlite3_connect()

    if VIOLATIONS:
        print("❌ CostView lint violations found:\n", file=sys.stderr)
        for v in VIOLATIONS:
            print(f"  {v}", file=sys.stderr)
        print(
            f"\n{len(VIOLATIONS)} violation(s). "
            "sqlite3.connect() must only appear in "
            "DataPipeline/src/storage/ or platform_data.",
            file=sys.stderr,
        )
        return 1

    print("✅ CostView lint: all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

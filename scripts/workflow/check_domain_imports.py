#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module Dependency Boundary Checker

Validates that modules respect architectural dependency rules:
- execution must NOT import from costview, marketview, databaseview
- costview must NOT import from execution, marketview, databaseview
- marketview must NOT import from execution, costview, databaseview
- databaseview must NOT import from execution, costview, marketview
- shared can be imported by anyone
- app can import from shared and modules (as entry point)
- Modules must NOT import from sibling module internals (use public API only)

Usage:
  python scripts/workflow/check_domain_imports.py
  python scripts/workflow/check_domain_imports.py --mode error
  python scripts/workflow/check_domain_imports.py --mode warning

Exit codes:
  0 = no violations (or warnings-only mode with warnings found)
  1 = violations found in error mode
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = ROOT / "ExecutionView" / "frontend" / "src"

# Domain modules and their boundaries
MODULES = ["execution", "costview", "marketview", "databaseview"]

# Dependency rules: module -> list of modules it MUST NOT import from
FORBIDDEN_IMPORTS: dict[str, list[str]] = {
    "execution": ["costview", "marketview", "databaseview"],
    "costview": ["execution", "marketview", "databaseview"],
    "marketview": ["execution", "costview", "databaseview"],
    "databaseview": ["execution", "costview", "marketview"],
}

# Import patterns to check
IMPORT_PATTERNS = [
    # Path-based imports: from '@/modules/xxx/...' or from '../modules/xxx/...'
    re.compile(r"""from\s+['"](@/modules/(\w+)/|['"].*?/modules/(\w+)/)"""),
    # Alias-based imports: from '@execution/...' etc
    re.compile(r"""from\s+['"]@(\w+)/"""),
]


@dataclass
class Violation:
    file: Path
    line: int
    source_module: str
    forbidden_import: str
    import_statement: str


def get_module_for_file(file_path: Path) -> str | None:
    """Determine which domain module a file belongs to."""
    rel = file_path.relative_to(FRONTEND_SRC)
    parts = rel.parts

    if parts[0] == "modules" and len(parts) > 1:
        if parts[1] in MODULES:
            return parts[1]
    return None


def check_file(file_path: Path) -> list[Violation]:
    """Check a single file for dependency violations."""
    source_module = get_module_for_file(file_path)
    if source_module is None:
        return []

    forbidden = FORBIDDEN_IMPORTS.get(source_module, [])
    if not forbidden:
        return []

    violations = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    for line_no, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if not stripped.startswith("import ") and "from " not in stripped:
            continue

        # Check path-based imports to other modules
        for mod in forbidden:
            # Check @/modules/<mod>/ imports
            if f"/modules/{mod}/" in stripped or f"\\modules\\{mod}\\" in stripped:
                violations.append(Violation(
                    file=file_path,
                    line=line_no,
                    source_module=source_module,
                    forbidden_import=mod,
                    import_statement=stripped,
                ))
                continue

            # Check alias imports: @<mod> where <mod> is a forbidden module alias
            # Only execution has @execution alias currently
            alias_map = {"execution": "@execution"}
            alias = alias_map.get(mod)
            if alias and f"from '{alias}/" in stripped or f'from "{alias}/' in stripped:
                violations.append(Violation(
                    file=file_path,
                    line=line_no,
                    source_module=source_module,
                    forbidden_import=mod,
                    import_statement=stripped,
                ))

    return violations


def check_all_boundaries() -> list[Violation]:
    """Check all domain module files for boundary violations."""
    violations = []

    for module_name in MODULES:
        module_dir = FRONTEND_SRC / "modules" / module_name
        if not module_dir.is_dir():
            continue

        for ts_file in module_dir.rglob("*.ts"):
            violations.extend(check_file(ts_file))
        for tsx_file in module_dir.rglob("*.tsx"):
            violations.extend(check_file(tsx_file))

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Check module dependency boundaries")
    parser.add_argument(
        "--mode",
        choices=["warning", "error"],
        default="warning",
        help="Violation reporting mode (default: warning)",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write results to JSON file",
    )
    args = parser.parse_args()

    violations = check_all_boundaries()

    # Print results
    if violations:
        print(f"\nFound {len(violations)} dependency boundary violation(s):\n")
        for v in violations:
            rel_path = v.file.relative_to(ROOT)
            print(f"  [{v.source_module} -> {v.forbidden_import}] {rel_path}:{v.line}")
            print(f"    {v.import_statement}")
            print()
    else:
        print("\nNo dependency boundary violations found. All modules respect their boundaries.")

    # JSON output
    if args.json:
        import json
        output = {
            "total_violations": len(violations),
            "mode": args.mode,
            "violations": [
                {
                    "file": str(v.file.relative_to(ROOT)),
                    "line": v.line,
                    "source_module": v.source_module,
                    "forbidden_import": v.forbidden_import,
                    "import_statement": v.import_statement,
                }
                for v in violations
            ],
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.mode == "error" and violations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

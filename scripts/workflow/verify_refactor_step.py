#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Architecture Refactor Step Verification Script

Verifies that each step of the architecture refactoring plan has been
correctly implemented. Each step has specific validation criteria
based on its output_schema and expected artifacts.

Usage:
  python scripts/workflow/verify_refactor_step.py --step S01
  python scripts/workflow/verify_refactor_step.py --step S03 --output-json result.json

Exit codes:
  0 = verification passed
  1 = verification failed (with structured error output)
  2 = unknown step or config error
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = ROOT / ""frontend" / "src"
BACKEND_API = ROOT / ""backend" / "api"


@dataclass
class VerifyResult:
    step_id: str
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def run_command(cmd: str, cwd: Path | None = None, timeout: int = 120) -> tuple[bool, str, str]:
    """Run a shell command, return (success, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd or ROOT), shell=True,
            capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode == 0, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out: {cmd}"
    except Exception as e:
        return False, "", str(e)


def dir_exists(path: Path) -> bool:
    return path.is_dir()


def file_exists(path: Path) -> bool:
    return path.is_file()


def file_contains(path: Path, pattern: str) -> bool:
    if not path.exists():
        return False
    return pattern in path.read_text(encoding="utf-8", errors="ignore")


def check_reexport(path: Path, expected_exports: list[str]) -> tuple[bool, list[str]]:
    """Check that a file re-exports the expected symbols."""
    if not path.exists():
        return False, [f"File not found: {path}"]
    content = path.read_text(encoding="utf-8", errors="ignore")
    missing = []
    for symbol in expected_exports:
        if symbol not in content:
            missing.append(symbol)
    return len(missing) == 0, missing


# =============================================================================
# Step-specific verifiers
# =============================================================================

def verify_S01() -> VerifyResult:
    """S01: Create new directory skeleton and bridge mechanism."""
    result = VerifyResult(step_id="S01", passed=True)

    # Check directories exist
    required_dirs = [
        FRONTEND_SRC / "app",
        FRONTEND_SRC / "shared",
        FRONTEND_SRC / "modules" / "execution",
        FRONTEND_SRC / "modules" / "costview",
        FRONTEND_SRC / "modules" / "marketview",
        FRONTEND_SRC / "modules" / "databaseview",
    ]
    for d in required_dirs:
        ok = dir_exists(d)
        result.checks.append({"check": f"dir_exists:{d.relative_to(ROOT)}", "passed": ok})
        if not ok:
            result.passed = False
            result.errors.append(f"Directory missing: {d}")

    # Check build still passes
    success, stdout, stderr = run_command(
        "npx tsc --noEmit", cwd=ROOT / ""frontend", timeout=120
    )
    result.checks.append({"check": "tsc_noEmit", "passed": success})
    if not success:
        result.passed = False
        result.errors.append(f"TypeScript compilation failed: {stderr[:500]}")

    return result


def verify_S02() -> VerifyResult:
    """S02: Establish migration verification baseline."""
    result = VerifyResult(step_id="S02", passed=True)

    baseline_file = ROOT / "docs" / "migration-baseline.md"
    ok = file_exists(baseline_file)
    result.checks.append({"check": f"file_exists:{baseline_file.relative_to(ROOT)}", "passed": ok})
    if not ok:
        result.passed = False
        result.errors.append("Baseline file docs/migration-baseline.md not found")

    return result


def verify_S03() -> VerifyResult:
    """S03: Split type definition files by domain."""
    result = VerifyResult(step_id="S03", passed=True)

    # Check new type directories exist
    shared_types_dir = FRONTEND_SRC / "shared" / "types"
    exec_types_dir = FRONTEND_SRC / "modules" / "execution" / "types"

    for d in [shared_types_dir, exec_types_dir]:
        ok = dir_exists(d)
        result.checks.append({"check": f"dir_exists:{d.relative_to(ROOT)}", "passed": ok})
        if not ok:
            result.passed = False
            result.errors.append(f"Type directory missing: {d}")

    # Check old types/index.ts still works as re-export
    old_types = FRONTEND_SRC / "types" / "index.ts"
    if file_exists(old_types):
        has_reexport = file_contains(old_types, "export") and (
            file_contains(old_types, "@shared/types") or
            file_contains(old_types, "@execution/types") or
            file_contains(old_types, "shared/types") or
            file_contains(old_types, "modules/execution/types")
        )
        result.checks.append({"check": "old_types_reexport", "passed": has_reexport})
    else:
        result.checks.append({"check": "old_types_exists", "passed": False})
        result.passed = False
        result.errors.append("src/types/index.ts no longer exists (should be re-export)")

    # Check TypeScript compilation
    success, _, stderr = run_command(
        "npx tsc --noEmit", cwd=ROOT / ""frontend", timeout=120
    )
    result.checks.append({"check": "tsc_noEmit", "passed": success})
    if not success:
        result.passed = False
        result.errors.append(f"TypeScript compilation failed: {stderr[:500]}")

    return result


def verify_S04() -> VerifyResult:
    """S04: Split shared utility library."""
    result = VerifyResult(step_id="S04", passed=True)

    shared_lib = FRONTEND_SRC / "shared" / "lib"
    exec_lib = FRONTEND_SRC / "modules" / "execution" / "lib"

    # Check shared lib has expected files
    shared_expected = ["cache-manager.ts", "format-utils.ts", "utils.ts"]
    for f in shared_expected:
        ok = file_exists(shared_lib / f)
        result.checks.append({"check": f"shared_lib:{f}", "passed": ok})
        if not ok:
            result.passed = False

    # Check execution lib has expected files
    exec_expected = ["health-palette.ts", "monitor-conditions.ts"]
    for f in exec_expected:
        ok = file_exists(exec_lib / f)
        result.checks.append({"check": f"exec_lib:{f}", "passed": ok})
        if not ok:
            result.passed = False

    # TypeScript compilation
    success, _, stderr = run_command(
        "npx tsc --noEmit", cwd=ROOT / ""frontend", timeout=120
    )
    result.checks.append({"check": "tsc_noEmit", "passed": success})
    if not success:
        result.passed = False

    return result


def verify_S05() -> VerifyResult:
    """S05: Split static data files."""
    result = VerifyResult(step_id="S05", passed=True)

    exec_data = FRONTEND_SRC / "modules" / "execution" / "data"
    expected_files = [
        "broker-exchange-mapping.ts",
        "broker-time-mapping.ts",
        "broker-volume-cap-mapping.ts",
        "broker-common-params.ts",
        "exchange-region-mapping.ts",
    ]
    for f in expected_files:
        ok = file_exists(exec_data / f)
        result.checks.append({"check": f"exec_data:{f}", "passed": ok})
        if not ok:
            result.passed = False

    success, _, stderr = run_command(
        "npx tsc --noEmit", cwd=ROOT / ""frontend", timeout=120
    )
    result.checks.append({"check": "tsc_noEmit", "passed": success})
    if not success:
        result.passed = False

    return result


def verify_S06() -> VerifyResult:
    """S06: Split service layer (api.ts + realtime.ts + handoff-api.ts)."""
    result = VerifyResult(step_id="S06", passed=True)

    # Check execution API created (whole api.ts moved, not split internally)
    exec_api = FRONTEND_SRC / "modules" / "execution" / "services" / "execution-api.ts"
    result.checks.append({
        "check": "execution_api_exists",
        "passed": file_exists(exec_api),
    })

    # Check handoff moved to shared
    handoff_api = FRONTEND_SRC / "shared" / "services" / "handoff-api.ts"
    result.checks.append({
        "check": "shared_handoff_api_exists",
        "passed": file_exists(handoff_api),
    })

    # Check realtime moved to execution
    realtime = FRONTEND_SRC / "modules" / "execution" / "services" / "realtime.ts"
    result.checks.append({
        "check": "execution_realtime_exists",
        "passed": file_exists(realtime),
    })

    # Check old services still re-export
    old_api = FRONTEND_SRC / "services" / "api.ts"
    if file_exists(old_api):
        has_reexport = file_contains(old_api, "export") and (
            file_contains(old_api, "execution-api") or
            file_contains(old_api, "http-client")
        )
        result.checks.append({"check": "old_api_reexport", "passed": has_reexport})

    # TypeScript compilation
    success, _, stderr = run_command(
        "npx tsc --noEmit", cwd=ROOT / ""frontend", timeout=120
    )
    result.checks.append({"check": "tsc_noEmit", "passed": success})
    if not success:
        result.passed = False
        result.errors.append(f"TypeScript compilation failed: {stderr[:500]}")

    # Dev server smoke test
    success, _, _ = run_command(
        "npx vite build --mode development", cwd=ROOT / ""frontend", timeout=180
    )
    result.checks.append({"check": "vite_build", "passed": success})
    if not success:
        result.passed = False

    return result


def verify_S07() -> VerifyResult:
    """S07: Split state store layer."""
    result = VerifyResult(step_id="S07", passed=True)

    exec_stores = FRONTEND_SRC / "modules" / "execution" / "stores"
    for f in ["order-stream-store.ts", "route-stream-store.ts"]:
        ok = file_exists(exec_stores / f)
        result.checks.append({"check": f"exec_stores:{f}", "passed": ok})
        if not ok:
            result.passed = False

    success, _, _ = run_command(
        "npx tsc --noEmit", cwd=ROOT / ""frontend", timeout=120
    )
    result.checks.append({"check": "tsc_noEmit", "passed": success})
    if not success:
        result.passed = False

    return result


def verify_S08() -> VerifyResult:
    """S08: Split hooks layer + decompose useAppShellState."""
    result = VerifyResult(step_id="S08", passed=True)

    # Check execution hooks
    exec_hooks = FRONTEND_SRC / "modules" / "execution" / "hooks"
    exec_hook_files = [
        "use-execution-state.ts",
        "use-execution-view-data.ts",
        "use-orders-stream.ts",
        "use-routes-stream.ts",
        "use-broker-algorithms.ts",
        "use-market-broker-mapping.ts",
    ]
    for f in exec_hook_files:
        ok = file_exists(exec_hooks / f)
        result.checks.append({"check": f"exec_hooks:{f}", "passed": ok})
        if not ok:
            result.passed = False

    # Check shared hooks
    shared_hooks = FRONTEND_SRC / "shared" / "hooks"
    ok = file_exists(shared_hooks / "use-handoff-contracts.tsx")
    result.checks.append({"check": "shared_hooks:use-handoff-contracts", "passed": ok})

    # Check app hooks
    app_hooks = FRONTEND_SRC / "app" / "hooks"
    ok = file_exists(app_hooks / "use-module-navigation.ts")
    result.checks.append({"check": "app_hooks:use-module-navigation", "passed": ok})

    # Check old hooks still has aggregate re-export
    old_shell = FRONTEND_SRC / "hooks" / "use-app-shell-state.ts"
    if file_exists(old_shell):
        is_bridge = (
            file_contains(old_shell, "use-module-navigation") or
            file_contains(old_shell, "use-execution-state")
        )
        result.checks.append({"check": "old_shell_state_is_bridge", "passed": is_bridge})

    success, _, _ = run_command(
        "npx tsc --noEmit", cwd=ROOT / ""frontend", timeout=120
    )
    result.checks.append({"check": "tsc_noEmit", "passed": success})
    if not success:
        result.passed = False

    return result


def verify_S09() -> VerifyResult:
    """S09: Extract Platform Shell from App.tsx."""
    result = VerifyResult(step_id="S09", passed=True)

    # Check new app structure
    new_app = FRONTEND_SRC / "app" / "App.tsx"
    app_shell = FRONTEND_SRC / "app" / "AppShell.tsx"
    rt_provider = FRONTEND_SRC / "app" / "providers" / "RealtimeProvider.tsx"
    auth_provider = FRONTEND_SRC / "app" / "providers" / "AuthProvider.tsx"
    toast_provider = FRONTEND_SRC / "app" / "providers" / "ToastProvider.tsx"

    for path, name in [(new_app, "app/App.tsx"), (app_shell, "app/AppShell.tsx"),
                       (rt_provider, "app/providers/RealtimeProvider.tsx"),
                       (auth_provider, "app/providers/AuthProvider.tsx"),
                       (toast_provider, "app/providers/ToastProvider.tsx")]:
        ok = file_exists(path)
        result.checks.append({"check": f"exists:{name}", "passed": ok})
        if not ok:
            result.passed = False

    # Check old App.tsx is a re-export
    old_app = FRONTEND_SRC / "App.tsx"
    if file_exists(old_app):
        is_bridge = file_contains(old_app, "app/App") or file_contains(old_app, "AppShell")
        result.checks.append({"check": "old_app_is_reexport", "passed": is_bridge})

    # Check new App.tsx is small (< 100 lines)
    if file_exists(new_app):
        lines = len(new_app.read_text(encoding="utf-8", errors="ignore").splitlines())
        is_small = lines < 100
        result.checks.append({"check": f"new_app_lines:{lines}", "passed": is_small})
        if not is_small:
            result.passed = False
            result.errors.append(f"New App.tsx has {lines} lines, expected < 100")

    success, _, _ = run_command(
        "npx tsc --noEmit", cwd=ROOT / ""frontend", timeout=120
    )
    result.checks.append({"check": "tsc_noEmit", "passed": success})
    if not success:
        result.passed = False

    return result


def verify_S10() -> VerifyResult:
    """S10: Establish Execution module entry point."""
    result = VerifyResult(step_id="S10", passed=True)

    module_entry = FRONTEND_SRC / "modules" / "execution" / "ExecutionModule.tsx"
    ok = file_exists(module_entry)
    result.checks.append({"check": "ExecutionModule_exists", "passed": ok})
    if not ok:
        result.passed = False

    # Check AppShell lazy-loads the module
    app_shell = FRONTEND_SRC / "app" / "AppShell.tsx"
    if file_exists(app_shell):
        has_lazy = file_contains(app_shell, "lazy") and file_contains(app_shell, "ExecutionModule")
        result.checks.append({"check": "app_shell_lazy_loads_module", "passed": has_lazy})

    success, _, _ = run_command(
        "npx tsc --noEmit", cwd=ROOT / ""frontend", timeout=120
    )
    result.checks.append({"check": "tsc_noEmit", "passed": success})
    if not success:
        result.passed = False

    return result


def verify_S11() -> VerifyResult:
    """S11: Enforce module dependency boundaries."""
    result = VerifyResult(step_id="S11", passed=True)

    check_script = ROOT / "scripts" / "workflow" / "check_domain_imports.py"
    ok = file_exists(check_script)
    result.checks.append({"check": "check_domain_imports_script_exists", "passed": ok})
    if not ok:
        result.passed = False

    # Run the check script
    if ok:
        success, stdout, stderr = run_command(
            f"python {check_script}", cwd=ROOT, timeout=60
        )
        result.checks.append({"check": "domain_import_check_passed", "passed": success})
        if not success:
            result.errors.append(f"Domain import violations found: {stdout[:500]}")

    return result


def verify_S12() -> VerifyResult:
    """S12: Clean up bridge re-exports."""
    result = VerifyResult(step_id="S12", passed=True)

    # Verify old directories no longer have re-export files
    # (they should be deleted or contain actual code, not just re-exports)
    old_dirs = [
        FRONTEND_SRC / "types" / "index.ts",
        FRONTEND_SRC / "services" / "api.ts",
        FRONTEND_SRC / "services" / "realtime.ts",
    ]
    for f in old_dirs:
        # After S12, these should either not exist or not be re-export bridges
        if file_exists(f):
            content = f.read_text(encoding="utf-8", errors="ignore")
            lines = [l.strip() for l in content.splitlines() if l.strip() and not l.strip().startswith("//")]
            is_only_reexport = all(
                l.startswith("export") and ("from" in l or "{" in l)
                for l in lines
            )
            result.checks.append({
                "check": f"not_pure_reexport:{f.relative_to(ROOT)}",
                "passed": not is_only_reexport,
            })

    # Verify no old-path imports remain
    success, stdout, _ = run_command(
        'grep -r "from \'@/types\'\\|from \'@/services/api\'\\|from \'@/services/realtime\'" '
        f'{FRONTEND_SRC} --include="*.ts" --include="*.tsx" -l || true',
        timeout=30,
    )
    old_refs = stdout.strip().splitlines() if stdout.strip() else []
    result.checks.append({
        "check": "no_old_path_refs",
        "passed": len(old_refs) == 0,
        "details": {"old_refs_count": len(old_refs), "files": old_refs[:10]},
    })
    if old_refs:
        result.passed = False
        result.errors.append(f"Found {len(old_refs)} files with old import paths")

    success, _, _ = run_command(
        "npx tsc --noEmit", cwd=ROOT / ""frontend", timeout=120
    )
    result.checks.append({"check": "tsc_noEmit", "passed": success})
    if not success:
        result.passed = False

    return result


def verify_S13() -> VerifyResult:
    """S13: Split backend schemas and services."""
    result = VerifyResult(step_id="S13", passed=True)

    # Check schemas directory
    schemas_dir = BACKEND_API / "schemas"
    if dir_exists(schemas_dir):
        expected = ["__init__.py", "orders.py", "routes.py", "common.py"]
        for f in expected:
            ok = file_exists(schemas_dir / f)
            result.checks.append({"check": f"schemas:{f}", "passed": ok})
            if not ok:
                result.passed = False
    else:
        result.checks.append({"check": "schemas_dir_exists", "passed": False})
        result.passed = False

    # Check bloomberg subdirectory
    bloomberg_dir = BACKEND_API / "services" / "bloomberg"
    if dir_exists(bloomberg_dir):
        expected = ["adapter.py", "connection.py", "subscriptions.py", "order_ops.py", "route_ops.py", "data_query.py"]
        for f in expected:
            ok = file_exists(bloomberg_dir / f)
            result.checks.append({"check": f"bloomberg:{f}", "passed": ok})
            if not ok:
                result.passed = False
    else:
        result.checks.append({"check": "bloomberg_dir_exists", "passed": False})
        result.passed = False

    # pytest
    success, stdout, _ = run_command(
        "python -m pytest backend/api/tests/ -q --tb=short", timeout=120
    )
    result.checks.append({"check": "pytest", "passed": success})

    return result


def verify_S14() -> VerifyResult:
    """S14: Reorganize backend routers into domain packages."""
    result = VerifyResult(step_id="S14", passed=True)

    domains_dir = BACKEND_API / "domains"
    expected_domains = ["execution", "costview", "marketview", "database"]
    for d in expected_domains:
        domain_path = domains_dir / d
        ok = dir_exists(domain_path)
        result.checks.append({"check": f"domain:{d}", "passed": ok})
        if not ok:
            result.passed = False

    # Check execution domain has routers
    exec_routers = domains_dir / "execution" / "routers"
    if dir_exists(exec_routers):
        result.checks.append({"check": "execution_routers_dir", "passed": True})
    else:
        result.checks.append({"check": "execution_routers_dir", "passed": False})
        result.passed = False

    # pytest
    success, _, _ = run_command(
        "python -m pytest backend/api/tests/ -q --tb=short", timeout=120
    )
    result.checks.append({"check": "pytest", "passed": success})

    return result


def verify_S15() -> VerifyResult:
    """S15: Establish backend domain dependency rules."""
    result = VerifyResult(step_id="S15", passed=True)

    check_script = ROOT / "scripts" / "check_domain_imports.py"
    ok = file_exists(check_script)
    result.checks.append({"check": "check_domain_imports_exists", "passed": ok})
    if not ok:
        result.passed = False

    if ok:
        success, stdout, _ = run_command(f"python {check_script}", timeout=60)
        result.checks.append({"check": "domain_import_check_passed", "passed": success})

    return result


# =============================================================================
# Dispatcher
# =============================================================================

VERIFIERS = {
    "S01": verify_S01,
    "S02": verify_S02,
    "S03": verify_S03,
    "S04": verify_S04,
    "S05": verify_S05,
    "S06": verify_S06,
    "S07": verify_S07,
    "S08": verify_S08,
    "S09": verify_S09,
    "S10": verify_S10,
    "S11": verify_S11,
    "S12": verify_S12,
    "S13": verify_S13,
    "S14": verify_S14,
    "S15": verify_S15,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify architecture refactor step")
    parser.add_argument("--step", required=True, choices=list(VERIFIERS.keys()), help="Step ID to verify")
    parser.add_argument("--output-json", type=Path, default=None, help="Write result to JSON file")
    args = parser.parse_args()

    verifier = VERIFIERS[args.step]
    result = verifier()

    output = asdict(result)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(output, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # Print summary
    total = len(result.checks)
    passed = sum(1 for c in result.checks if c.get("passed"))
    status = "PASSED" if result.passed else "FAILED"
    print(f"\nStep {args.step} verification: {status} ({passed}/{total} checks passed)")

    for check in result.checks:
        icon = "[PASS]" if check.get("passed") else "[FAIL]"
        print(f"  {icon} {check.get('check', 'unknown')}")

    if result.errors:
        print("\nErrors:")
        for err in result.errors:
            print(f"  - {err}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

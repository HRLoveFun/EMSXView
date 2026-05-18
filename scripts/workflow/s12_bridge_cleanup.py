#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S12 Bridge Cleanup Script

Automatically replaces old bridge path imports with new path alias imports
across all frontend source files, then deletes the bridge files.

Mapping rules:
  @/types -> @shared/types or @execution/types (based on imported symbol)
  @/lib/cache-manager -> @shared/lib/cache-manager
  @/lib/format-utils -> @shared/lib/format-utils
  @/lib/utils -> @shared/lib/utils
  @/lib/reconcile-settings -> @shared/lib/reconcile-settings
  @/lib/table-constants -> @shared/lib/table-constants
  @/lib/health-palette -> @execution/lib/health-palette
  @/lib/monitor-conditions -> @execution/lib/monitor-conditions
  @/data/* -> @execution/data/*
  @/services/api -> @execution/services/execution-api
  @/services/realtime -> @execution/services/realtime
  @/services/handoff-api -> @shared/services/handoff-api
  @/services/strategy-data-service -> @execution/services/strategy-data-service
  @/stores/* -> @execution/stores/*
  @/hooks/use-app-shell-state -> @app/hooks/use-module-navigation + @execution/hooks/use-execution-state
  @/hooks/use-broker-algorithms -> @execution/hooks/use-broker-algorithms
  @/hooks/use-execution-view-data -> @execution/hooks/use-execution-view-data
  @/hooks/use-handoff-contracts -> @shared/hooks/use-handoff-contracts
  @/hooks/use-market-broker-mapping -> @execution/hooks/use-market-broker-mapping
  @/hooks/use-mobile -> @shared/hooks/use-mobile
  @/hooks/use-orders-stream -> @execution/hooks/use-orders-stream
  @/hooks/use-routes-stream -> @execution/hooks/use-routes-stream
  @/hooks/use-startup-status -> @app/hooks/use-startup-status
  @/hooks/use-trade-hotkeys -> @execution/hooks/use-trade-hotkeys
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = ROOT / "ExecutionView" / "frontend" / "src"

# Shared types (from @shared/types)
SHARED_TYPE_SYMBOLS = {
    'Toast', 'ApiResponse', 'ConnectionStatus', 'BloombergConnectionState',
    'StartupPhase', 'BackendStartupSnapshot', 'BloombergStartupSnapshot',
    'SubscriptionStartupSnapshot', 'StartupStatusSnapshot',
}

# Direct path replacements (no symbol analysis needed)
DIRECT_REPLACEMENTS: list[tuple[str, str]] = [
    # lib
    (r"""from ['"]@/lib/cache-manager['"]""", r"""from '@shared/lib/cache-manager'"""),
    (r"""from ['"]@/lib/format-utils['"]""", r"""from '@shared/lib/format-utils'"""),
    (r"""from ['"]@/lib/utils['"]""", r"""from '@shared/lib/utils'"""),
    (r"""from ['"]@/lib/reconcile-settings['"]""", r"""from '@shared/lib/reconcile-settings'"""),
    (r"""from ['"]@/lib/table-constants['"]""", r"""from '@shared/lib/table-constants'"""),
    (r"""from ['"]@/lib/health-palette['"]""", r"""from '@execution/lib/health-palette'"""),
    (r"""from ['"]@/lib/monitor-conditions['"]""", r"""from '@execution/lib/monitor-conditions'"""),
    # data
    (r"""from ['"]@/data/broker-exchange-mapping['"]""", r"""from '@execution/data/broker-exchange-mapping'"""),
    (r"""from ['"]@/data/broker-time-mapping['"]""", r"""from '@execution/data/broker-time-mapping'"""),
    (r"""from ['"]@/data/broker-volume-cap-mapping['"]""", r"""from '@execution/data/broker-volume-cap-mapping'"""),
    (r"""from ['"]@/data/broker-common-params['"]""", r"""from '@execution/data/broker-common-params'"""),
    (r"""from ['"]@/data/exchange-region-mapping['"]""", r"""from '@execution/data/exchange-region-mapping'"""),
    # services
    (r"""from ['"]@/services/api['"]""", r"""from '@execution/services/execution-api'"""),
    (r"""from ['"]@/services/realtime['"]""", r"""from '@execution/services/realtime'"""),
    (r"""from ['"]@/services/handoff-api['"]""", r"""from '@shared/services/handoff-api'"""),
    (r"""from ['"]@/services/strategy-data-service['"]""", r"""from '@execution/services/strategy-data-service'"""),
    # stores
    (r"""from ['"]@/stores/order-stream-store['"]""", r"""from '@execution/stores/order-stream-store'"""),
    (r"""from ['"]@/stores/route-stream-store['"]""", r"""from '@execution/stores/route-stream-store'"""),
    # hooks
    (r"""from ['"]@/hooks/use-broker-algorithms['"]""", r"""from '@execution/hooks/use-broker-algorithms'"""),
    (r"""from ['"]@/hooks/use-execution-view-data['"]""", r"""from '@execution/hooks/use-execution-view-data'"""),
    (r"""from ['"]@/hooks/use-handoff-contracts['"]""", r"""from '@shared/hooks/use-handoff-contracts'"""),
    (r"""from ['"]@/hooks/use-market-broker-mapping['"]""", r"""from '@execution/hooks/use-market-broker-mapping'"""),
    (r"""from ['"]@/hooks/use-mobile['"]""", r"""from '@shared/hooks/use-mobile'"""),
    (r"""from ['"]@/hooks/use-orders-stream['"]""", r"""from '@execution/hooks/use-orders-stream'"""),
    (r"""from ['"]@/hooks/use-routes-stream['"]""", r"""from '@execution/hooks/use-routes-stream'"""),
    (r"""from ['"]@/hooks/use-startup-status['"]""", r"""from '@app/hooks/use-startup-status'"""),
    (r"""from ['"]@/hooks/use-trade-hotkeys['"]""", r"""from '@execution/hooks/use-trade-hotkeys'"""),
    # App.tsx bridge
    (r"""from ['"]\./app/App['"]""", r"""from './app/App'"""),  # no-op, just for clarity
]

# Bridge files to delete after migration
BRIDGE_FILES = [
    "types/index.ts",
    "lib/cache-manager.ts",
    "lib/format-utils.ts",
    "lib/utils.ts",
    "lib/reconcile-settings.ts",
    "lib/table-constants.ts",
    "lib/health-palette.ts",
    "lib/monitor-conditions.ts",
    "data/broker-exchange-mapping.ts",
    "data/broker-time-mapping.ts",
    "data/broker-volume-cap-mapping.ts",
    "data/broker-common-params.ts",
    "data/exchange-region-mapping.ts",
    "services/api.ts",
    "services/realtime.ts",
    "services/handoff-api.ts",
    "services/strategy-data-service.ts",
    "stores/order-stream-store.ts",
    "stores/route-stream-store.ts",
    "hooks/use-app-shell-state.ts",
    "hooks/use-broker-algorithms.ts",
    "hooks/use-execution-view-data.ts",
    "hooks/use-handoff-contracts.tsx",
    "hooks/use-market-broker-mapping.ts",
    "hooks/use-mobile.ts",
    "hooks/use-orders-stream.ts",
    "hooks/use-routes-stream.ts",
    "hooks/use-startup-status.ts",
    "hooks/use-trade-hotkeys.tsx",
]

# Special: @/types import splitting
def split_types_import(line: str) -> str:
    """Split a `from '@/types'` import into @shared/types and @execution/types."""
    # Match: import { X, Y, Z } from '@/types'
    # or: import type { X, Y, Z } from '@/types'
    m = re.match(
        r"""(import\s+(?:type\s+)?)\{([^}]+)\}\s+from\s+['"]@/types['"]""",
        line.strip()
    )
    if not m:
        return line

    prefix = m.group(1)
    symbols_str = m.group(2)

    # Parse symbols
    symbols = [s.strip().rstrip(',') for s in symbols_str.split(',') if s.strip()]
    # Handle "type X" syntax within braces
    clean_symbols = []
    for s in symbols:
        s = s.strip()
        if s.startswith('type '):
            s = s[5:].strip()
        clean_symbols.append(s)

    shared = [s for s in clean_symbols if s in SHARED_TYPE_SYMBOLS]
    execution = [s for s in clean_symbols if s not in SHARED_TYPE_SYMBOLS]

    results = []
    if shared:
        results.append(f"{prefix}{{ {', '.join(shared)} }} from '@shared/types'")
    if execution:
        results.append(f"{prefix}{{ {', '.join(execution)} }} from '@execution/types'")

    return '\n'.join(results)


def process_file(file_path: Path) -> bool:
    """Process a single file, replacing old imports. Returns True if changed."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return False

    original = content
    lines = content.splitlines()
    new_lines = []

    for line in lines:
        # Handle @/types imports specially
        if "from '@/types'" in line or 'from "@/types"' in line:
            new_line = split_types_import(line)
            new_lines.append(new_line)
            continue

        # Handle @/hooks/use-app-shell-state specially - this is a combined hook
        # Only the bridge file uses it now; consumers should use the split hooks
        if "@/hooks/use-app-shell-state" in line:
            # Keep as-is for now - the bridge file is still used by sections/components
            # that haven't been migrated yet. We'll handle this separately.
            new_lines.append(line)
            continue

        # Apply direct replacements
        new_line = line
        for pattern, replacement in DIRECT_REPLACEMENTS:
            new_line = re.sub(pattern, replacement, new_line)

        new_lines.append(new_line)

    new_content = '\n'.join(new_lines)
    if new_content != original:
        file_path.write_text(new_content, encoding="utf-8")
        print(f"  Updated: {file_path.relative_to(ROOT)}")
        return True
    return False


def main() -> int:
    print("S12: Cleaning up bridge re-exports")
    print("=" * 60)

    # Step 1: Update all imports
    print("\nStep 1: Updating imports in source files...")
    updated_count = 0
    for ts_file in FRONTEND_SRC.rglob("*.ts"):
        # Skip bridge files themselves and node_modules
        rel = ts_file.relative_to(FRONTEND_SRC)
        if any(str(rel).startswith(b) for b in ["types/", "lib/", "data/", "services/", "stores/", "hooks/"]):
            continue
        if "node_modules" in str(ts_file):
            continue
        if process_file(ts_file):
            updated_count += 1

    for tsx_file in FRONTEND_SRC.rglob("*.tsx"):
        rel = tsx_file.relative_to(FRONTEND_SRC)
        if any(str(rel).startswith(b) for b in ["hooks/"]):
            continue
        if "node_modules" in str(tsx_file):
            continue
        if process_file(tsx_file):
            updated_count += 1

    print(f"\n  Total files updated: {updated_count}")

    # Step 2: Delete bridge files
    print("\nStep 2: Deleting bridge files...")
    deleted_count = 0
    for bridge_rel in BRIDGE_FILES:
        bridge_path = FRONTEND_SRC / bridge_rel
        if bridge_path.exists():
            bridge_path.unlink()
            print(f"  Deleted: {bridge_rel}")
            deleted_count += 1
        else:
            print(f"  Not found (already deleted?): {bridge_rel}")

    print(f"\n  Total bridge files deleted: {deleted_count}")

    # Step 3: Clean up empty directories
    print("\nStep 3: Checking for empty directories...")
    for dir_path in [
        FRONTEND_SRC / "types",
        FRONTEND_SRC / "lib",
        FRONTEND_SRC / "data",
        FRONTEND_SRC / "services",
        FRONTEND_SRC / "stores",
        FRONTEND_SRC / "hooks",
    ]:
        if dir_path.exists() and dir_path.is_dir():
            remaining = list(dir_path.iterdir())
            if not remaining:
                dir_path.rmdir()
                print(f"  Removed empty dir: {dir_path.relative_to(ROOT)}")
            else:
                print(f"  Dir not empty ({len(remaining)} files): {dir_path.relative_to(ROOT)}")
                for f in remaining:
                    print(f"    - {f.name}")

    print("\nS12 cleanup complete!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

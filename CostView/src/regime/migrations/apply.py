"""
Forward-only migration runner for regime.db.

Usage (CLI):
    python -m CostView.src.regime.migrations.apply
    python -m CostView.src.regime.migrations.apply --db path/to/regime.db
    python -m CostView.src.regime.migrations.apply --dry-run

Behavior:
1. Reads PRAGMA user_version from the DB (0 if fresh).
2. Discovers `vN_to_vN+1.sql` files in this directory.
3. Applies pending migrations in order, each in a single transaction.
4. Sets PRAGMA user_version = N+1 after each successful migration.
5. Final user_version MUST equal schema.SCHEMA_VERSION; mismatch raises.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

from DataPipeline.src.storage.connection import ConnectionManager

_MIGRATIONS_DIR = Path(__file__).resolve().parent
_MIGRATION_NAME_RE = re.compile(r"^v(\d+)_to_v(\d+)\.sql$")


def _discover() -> List[Tuple[int, int, Path]]:
    """Return [(from_version, to_version, path), ...] sorted by from_version."""
    found: List[Tuple[int, int, Path]] = []
    for p in _MIGRATIONS_DIR.glob("v*_to_v*.sql"):
        m = _MIGRATION_NAME_RE.match(p.name)
        if not m:
            raise RuntimeError(f"Bad migration filename: {p.name}")
        from_v, to_v = int(m.group(1)), int(m.group(2))
        if to_v != from_v + 1:
            raise RuntimeError(f"Migrations must step +1: {p.name}")
        found.append((from_v, to_v, p))
    found.sort(key=lambda t: t[0])
    # Validate contiguity
    for i, (fv, _tv, p) in enumerate(found):
        if fv != i:
            raise RuntimeError(f"Non-contiguous migration chain at {p.name}")
    return found


def apply_pending(db_path: Path | str, dry_run: bool = False) -> int:
    """Apply pending migrations. Returns the final user_version."""
    db_path = Path(db_path)

    # autocommit mode: executescript() does not collide with implicit transactions.
    # Atomicity within a single migration is delivered by `BEGIN; ... COMMIT;` wrapping
    # inside the .sql file itself (forward-only DDL is also idempotent via IF NOT EXISTS).
    mgr = ConnectionManager(path_overrides={"regime": db_path})
    conn = mgr.get_admin_connection("regime")
    conn.isolation_level = None  # autocommit required for executescript()
    try:
        conn.execute("PRAGMA foreign_keys=ON")  # already set by ConnectionManager; idempotent
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        migrations = _discover()
        pending = [(fv, tv, p) for (fv, tv, p) in migrations if fv >= current]

        if not pending:
            print(f"[migrate] DB at user_version={current}; nothing to apply.")
            return current

        for fv, tv, path in pending:
            print(f"[migrate] {'(dry-run) ' if dry_run else ''}v{fv} -> v{tv}  ({path.name})")
            if dry_run:
                continue
            sql = path.read_text(encoding="utf-8")
            conn.executescript(sql)
            # PRAGMA user_version cannot be parameterized
            conn.execute(f"PRAGMA user_version = {tv}")
            print(f"[migrate]   ok -> user_version={tv}")

        final = conn.execute("PRAGMA user_version").fetchone()[0]
        return final
    finally:
        conn.close()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply regime.db migrations")
    parser.add_argument("--db", type=Path, default=None,
                        help="Override DB path (default: CostView/data/regime.db)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.db is None:
        # Lazy import to avoid forcing schema import when only running CLI in --dry-run
        from CostView.src.regime.schema import REGIME_DB_PATH, SCHEMA_VERSION
        db_path = REGIME_DB_PATH
        target = SCHEMA_VERSION
    else:
        db_path = args.db
        from CostView.src.regime.schema import SCHEMA_VERSION
        target = SCHEMA_VERSION

    final = apply_pending(db_path, dry_run=args.dry_run)
    if not args.dry_run and final != target:
        print(f"[migrate] FAIL: final user_version={final} != SCHEMA_VERSION={target}",
              file=sys.stderr)
        return 1
    print(f"[migrate] done. user_version={final}, target={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

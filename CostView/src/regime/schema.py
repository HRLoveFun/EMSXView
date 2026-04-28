"""
Regime DB schema management.

DDL itself lives in `migrations/vN_to_vN+1.sql` (single source of truth).
This module:
- Pins SCHEMA_VERSION (must match PRAGMA user_version after migrations)
- Provides connect() with the standard pragma triple
- Provides create_all() for fresh-DB bootstrapping
- Provides ensure_schema_current() startup guard
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# Pinned schema version. Bump → add new migrations/vN_to_vN+1.sql + apply.py runs it.
SCHEMA_VERSION: int = 3

# Repo-relative DB path. Caller MAY override via env / explicit path.
_THIS = Path(__file__).resolve()
_COSTVIEW_ROOT = _THIS.parents[2]                           # CostView/
REGIME_DB_PATH: Path = _COSTVIEW_ROOT / "data" / "regime.db"

_MIGRATIONS_DIR: Path = _THIS.parent / "migrations"


def connect(db_path: Path | str = REGIME_DB_PATH) -> sqlite3.Connection:
    """Open a regime.db connection with project-standard pragmas."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)  # autocommit; we manage txns
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def create_all(db_path: Path | str = REGIME_DB_PATH) -> None:
    """Bootstrap a fresh regime.db by applying all migrations.

    Idempotent: re-running on an existing DB is a no-op (apply.py honors
    PRAGMA user_version).
    """
    from .migrations.apply import apply_pending  # local import to avoid cycle
    apply_pending(db_path)


def ensure_schema_current(db_path: Path | str = REGIME_DB_PATH) -> None:
    """Guard: raise if PRAGMA user_version != SCHEMA_VERSION.

    Call this at process startup of any regime stage.
    """
    conn = connect(db_path)
    try:
        actual = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    if actual != SCHEMA_VERSION:
        raise RuntimeError(
            f"regime.db schema mismatch: PRAGMA user_version={actual} "
            f"but code SCHEMA_VERSION={SCHEMA_VERSION}. "
            f"Run: python -m CostView.src.regime.migrations.apply"
        )


def list_migrations() -> list[Path]:
    """Return migration files sorted by from-version."""
    return sorted(_MIGRATIONS_DIR.glob("v*_to_v*.sql"))

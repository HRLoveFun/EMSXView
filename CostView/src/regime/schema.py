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

from DataPipeline.src.storage.connection import ConnectionManager

# Pinned schema version. Bump → add new migrations/vN_to_vN+1.sql + apply.py runs it.
SCHEMA_VERSION: int = 3

# Repo-relative DB path. Caller MAY override via env / explicit path.
_THIS = Path(__file__).resolve()
_COSTVIEW_ROOT = _THIS.parents[2]                           # CostView/
REGIME_DB_PATH: Path = _COSTVIEW_ROOT / "data" / "regime.db"

_MIGRATIONS_DIR: Path = _THIS.parent / "migrations"


def connect(db_path: Path | str = REGIME_DB_PATH) -> sqlite3.Connection:
    """Open a regime.db connection with project-standard pragmas."""
    overrides = {"regime": Path(db_path)} if db_path != REGIME_DB_PATH else None
    mgr = ConnectionManager(path_overrides=overrides) if overrides else ConnectionManager()
    conn = mgr.get_admin_connection("regime")
    conn.row_factory = sqlite3.Row
    return conn


def create_all(db_path: Path | str = REGIME_DB_PATH) -> None:
    """Bootstrap a fresh regime.db by applying all migrations.

    Idempotent: re-running on an existing DB is a no-op (apply.py honors
    PRAGMA user_version).

    Delegates to the consolidated migration runner in DataPipeline.
    """
    from DataPipeline.src.storage.schema.migrations.apply import apply_pending  # noqa: PLC0415
    apply_pending(db_path)


def ensure_schema_current(db_path: Path | str = REGIME_DB_PATH) -> None:
    """Guard: raise if PRAGMA user_version != SCHEMA_VERSION.

    Call this at process startup of any regime stage.

    Delegates to the consolidated migration runner in DataPipeline.
    """
    from DataPipeline.src.storage.schema.migrations.apply import apply_pending  # noqa: PLC0415
    final = apply_pending(db_path)
    if final != SCHEMA_VERSION:
        raise RuntimeError(
            f"regime.db schema mismatch: PRAGMA user_version={final} "
            f"but code SCHEMA_VERSION={SCHEMA_VERSION}. "
            f"Run: python -m DataPipeline.src.storage.schema.migrations.apply"
        )


def list_migrations() -> list[Path]:
    """Return migration files sorted by from-version."""
    return sorted(_MIGRATIONS_DIR.glob("v*_to_v*.sql"))

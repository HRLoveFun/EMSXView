"""Regime database schema — path resolution and connection management.

Provides REGIME_DB_PATH and a connect() function for the regime database,
mirroring the old CostView.src.regime.schema interface.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from DataPipeline.config import Config

logger = logging.getLogger(__name__)

REGIME_DB_PATH: Path = Config.DATA_DIR / "regime.db"


def connect(
    db_path: Optional[Path] = None,
) -> sqlite3.Connection:
    """Open a direct sqlite3 connection to the regime database.

    Parameters
    ----------
    db_path : Path, optional
        Path to the regime database file. Defaults to REGIME_DB_PATH.

    Returns
    -------
    sqlite3.Connection
        A raw connection with standard pragmas applied.
    """
    path = db_path or REGIME_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout = {Config.SQLITE_BUSY_TIMEOUT_MS}")
    logger.debug(f"Connected to regime database: {path}")
    return conn

"""
audit_pipeline_runs helper — context-manager that journals every stage execution.

Usage:
    with run_journal("vol_regime", config_version="v0_default",
                     start="2026-04-01", end="2026-04-27") as run:
        rows = vol_regime.classify("2026-04-01", "2026-04-27")
        run.set_rows(rows)
"""
from __future__ import annotations

import datetime as dt
import socket
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from CostView.src.regime.schema import REGIME_DB_PATH, SCHEMA_VERSION, connect


class _RunRecord:
    """Mutable record passed back to the caller from run_journal()."""

    def __init__(self) -> None:
        self.rows_written: int = 0
        self.rows_updated: int = 0
        self.config_version: Optional[str] = None

    def set_rows(self, written: int, updated: int = 0) -> None:
        self.rows_written = int(written)
        self.rows_updated = int(updated)

    def set_config(self, version: str) -> None:
        self.config_version = version


@contextmanager
def run_journal(
    stage_name: str,
    *,
    config_version: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    db_path: Path = REGIME_DB_PATH,
) -> Iterator[_RunRecord]:
    """Journal a stage execution to audit_pipeline_runs."""
    started = dt.datetime.now()
    record = _RunRecord()
    record.config_version = config_version
    host = socket.gethostname()

    conn = connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO audit_pipeline_runs (
                stage_name, config_version, target_start_date, target_end_date,
                rows_written, rows_updated, status, error_message,
                run_started_at, run_finished_at, duration_sec, host, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, 'running', NULL, ?, NULL, NULL, ?, ?)""",
            (stage_name, config_version, start, end, 0, 0, started.isoformat(timespec="seconds"),
             host, SCHEMA_VERSION),
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    try:
        yield record
    except Exception as e:
        finished = dt.datetime.now()
        msg = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}"
        _finalize(db_path, run_id, "failed", record, started, finished, msg)
        raise
    else:
        finished = dt.datetime.now()
        _finalize(db_path, run_id, "success", record, started, finished, None)


def _finalize(db_path: Path, run_id: int, status: str, rec: _RunRecord,
              started: dt.datetime, finished: dt.datetime, err: Optional[str]) -> None:
    duration = (finished - started).total_seconds()
    conn = connect(db_path)
    try:
        conn.execute(
            """UPDATE audit_pipeline_runs
               SET status=?, error_message=?, rows_written=?, rows_updated=?,
                   config_version=COALESCE(?, config_version),
                   run_finished_at=?, duration_sec=?
               WHERE run_id=?""",
            (status, err, rec.rows_written, rec.rows_updated, rec.config_version,
             finished.isoformat(timespec="seconds"), duration, run_id),
        )
        conn.commit()
    finally:
        conn.close()

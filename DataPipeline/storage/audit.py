"""Non-blocking database access audit logger.

Records all database operations (READ/WRITE) to a JSON-lines audit log
with caller context, SQL preview, timing, and row counts. Uses an
in-memory buffer with periodic batch flush to avoid I/O impact on
hot query paths.

Usage::

    from DataPipeline.storage.audit import get_audit_logger
    audit = get_audit_logger()
    audit.log(AuditEntry(database="processed_fills", access_tier="READ", ...))

Integrate with ConnectionManager by patching get_connection() to wrap
AccessControlledConnection.execute() with audit hooks.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from DataPipeline.config import Config

logger = logging.getLogger(__name__)

AUDIT_BATCH_SIZE = 100
AUDIT_FLUSH_INTERVAL_SEC = 5.0
AUDIT_LOG_FILENAME = "audit.jsonl"


@dataclass
class AuditEntry:
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    database: str = ""
    access_tier: str = ""
    caller_module: str = ""
    sql_preview: str = ""
    row_count: int = 0
    duration_ms: float = 0.0
    user: str = "system"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.timestamp,
            "db": self.database,
            "tier": self.access_tier,
            "module": self.caller_module,
            "sql": self.sql_preview[:200],
            "rows": self.row_count,
            "dur_ms": round(self.duration_ms, 3),
            "user": self.user,
        }


class AuditLogger:
    def __init__(
        self,
        log_path: Optional[Path] = None,
        batch_size: int = AUDIT_BATCH_SIZE,
        flush_interval_sec: float = AUDIT_FLUSH_INTERVAL_SEC,
    ) -> None:
        cfg = Config()
        self._log_path = log_path or (cfg.LOGGING_DIR / AUDIT_LOG_FILENAME)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._batch_size = batch_size
        self._flush_interval = flush_interval_sec
        self._buffer: deque[AuditEntry] = deque()
        self._lock = threading.Lock()
        self._last_flush = time.monotonic()
        self._internal_logger = logging.getLogger("emsxview.audit")

    def log(self, entry: AuditEntry) -> None:
        with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self._batch_size:
                self._flush()
                self._last_flush = time.monotonic()
                return

        # Non-blocking time-based flush check inside lock for safety
        if time.monotonic() - self._last_flush > self._flush_interval:
            with self._lock:
                if self._buffer and time.monotonic() - self._last_flush > self._flush_interval:
                    self._flush()
                    self._last_flush = time.monotonic()

    def _flush(self) -> None:
        entries: List[AuditEntry] = []
        while self._buffer and len(entries) < self._batch_size:
            entries.append(self._buffer.popleft())

        if not entries:
            return

        lines = [json.dumps(e.to_dict()) for e in entries]
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            self._internal_logger.exception("Audit write failed")
        self._last_flush = time.monotonic()

    def force_flush(self) -> None:
        with self._lock:
            while self._buffer:
                self._flush()

    def query(
        self,
        db_name: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        if not self._log_path.exists():
            return results
        with open(self._log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if db_name and entry.get("db") != db_name:
                    continue
                if start and entry.get("ts", "") < start:
                    continue
                if end and entry.get("ts", "") > end:
                    continue
                results.append(entry)
        return results

    def stats(self, db_name: Optional[str] = None, hours: int = 24) -> Dict[str, Any]:
        """Aggregate audit statistics for a time window."""
        cutoff = datetime.now(timezone.utc).isoformat()
        entries = self.query(db_name=db_name)
        recent = [e for e in entries if e.get("ts", "") >= cutoff[:16]]
        read_count = sum(1 for e in recent if e.get("tier") == "READ")
        write_count = sum(1 for e in recent if e.get("tier") == "WRITE")
        total_rows = sum(e.get("rows", 0) for e in recent)
        durations = [e.get("dur_ms", 0) for e in recent if e.get("dur_ms")]
        return {
            "total_operations": len(recent),
            "read_operations": read_count,
            "write_operations": write_count,
            "total_rows_affected": total_rows,
            "avg_duration_ms": round(sum(durations) / len(durations), 3) if durations else 0,
            "max_duration_ms": round(max(durations), 3) if durations else 0,
            "window_hours": hours,
        }


_audit_logger: Optional[AuditLogger] = None
_audit_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        with _audit_lock:
            if _audit_logger is None:
                _audit_logger = AuditLogger()
    return _audit_logger


def shutdown_audit_logger() -> None:
    global _audit_logger
    if _audit_logger is not None:
        _audit_logger.force_flush()

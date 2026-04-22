"""Persistent tombstones for tickers that should be skipped by market fetch stages."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)

_FILE_LOCK = threading.Lock()


def _normalize_ticker(ticker: str) -> str:
    return str(ticker).strip()


def _resolve_path(file_path: Optional[Path] = None) -> Path:
    return Path(file_path or Config.OUTDATED_TICKERS_FILE)


def load_outdated_ticker_records(file_path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    path = _resolve_path(file_path)
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to read outdated ticker tombstones from {path}: {exc}")
        return {}

    if isinstance(payload, dict) and isinstance(payload.get("tickers"), dict):
        payload = payload["tickers"]

    if not isinstance(payload, dict):
        logger.warning(f"Unexpected outdated ticker tombstone format in {path}; ignoring")
        return {}

    return {
        _normalize_ticker(ticker): record
        for ticker, record in payload.items()
        if _normalize_ticker(ticker)
    }


def load_outdated_ticker_set(file_path: Optional[Path] = None) -> set[str]:
    return set(load_outdated_ticker_records(file_path).keys())


def record_outdated_ticker(
    ticker: str,
    reason: str,
    *,
    detail: Optional[str] = None,
    file_path: Optional[Path] = None,
) -> dict[str, Any]:
    normalized_ticker = _normalize_ticker(ticker)
    if not normalized_ticker:
        raise ValueError("ticker must not be empty")

    path = _resolve_path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()

    with _FILE_LOCK:
        records = load_outdated_ticker_records(path)
        existing = records.get(normalized_ticker, {})
        entry = {
            "equ_ticker": normalized_ticker,
            "reason": reason,
            "detail": detail or existing.get("detail"),
            "first_seen_at": existing.get("first_seen_at", now),
            "last_seen_at": now,
            "hit_count": int(existing.get("hit_count", 0)) + 1,
        }
        records[normalized_ticker] = entry

        payload = {
            "updated_at": now,
            "tickers": dict(sorted(records.items())),
        }

        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        temp_path.replace(path)

    return entry
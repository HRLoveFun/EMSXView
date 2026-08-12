"""永久空缺交易日 tombstone — 标记无法从 Bloomberg 拉取的工作日。

背景：Bloomberg EMSX History 对历史数据有保留窗口（与 BDIB 类似，
约 1 个月左右）。超出保留窗口的日期返回空数据，无法回填。
被标记为永久空缺的日期将被 ``determine_fetch_range`` 的缺口扫描剔除，
不再每次运行都告警、也不再反复尝试拉取。
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from DataPipeline.config import Config

logger = logging.getLogger(__name__)

_FILE_LOCK = threading.Lock()


def _normalize_date(date_str: str) -> str:
    """归一化 YYYY-MM-DD / YYYYMMDD 为 YYYYMMDD。"""
    value = str(date_str).strip()
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        return value.replace("-", "")
    if len(value) == 8 and value.isdigit():
        return value
    raise ValueError(f"Invalid date: {date_str!r} (expected YYYYMMDD or YYYY-MM-DD)")


def _resolve_path(file_path: Optional[Path] = None) -> Path:
    return Path(file_path or Config.PERMANENT_GAP_DATES_FILE)


def load_permanent_gap_records(file_path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """读取全部永久空缺交易日记录（key 为 YYYYMMDD）。"""
    path = _resolve_path(file_path)
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to read permanent gap records from {path}: {exc}")
        return {}

    if isinstance(payload, dict) and isinstance(payload.get("dates"), dict):
        payload = payload["dates"]

    if not isinstance(payload, dict):
        logger.warning(f"Unexpected permanent gap format in {path}; ignoring")
        return {}

    return {d: record for d, record in payload.items() if d}


def load_permanent_gap_set(file_path: Optional[Path] = None) -> set[str]:
    """返回永久空缺交易日集合（YYYYMMDD）。"""
    return set(load_permanent_gap_records(file_path).keys())


def record_permanent_gap(
    date_str: str,
    reason: str,
    *,
    detail: Optional[str] = None,
    file_path: Optional[Path] = None,
) -> dict[str, Any]:
    """将某日期标记为永久空缺（幂等，重复标记仅更新 last_seen_at）。"""
    normalized = _normalize_date(date_str)
    path = _resolve_path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()

    with _FILE_LOCK:
        records = load_permanent_gap_records(path)
        existing = records.get(normalized, {})
        entry = {
            "date": normalized,
            "reason": reason,
            "detail": detail or existing.get("detail"),
            "first_seen_at": existing.get("first_seen_at", now),
            "last_seen_at": now,
            "record_count": int(existing.get("record_count", 0)) + 1,
        }
        records[normalized] = entry

        payload = {
            "updated_at": now,
            "dates": dict(sorted(records.items())),
        }

        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        temp_path.replace(path)

    return entry


def remove_permanent_gap(date_str: str, file_path: Optional[Path] = None) -> bool:
    """移除某日期的永久空缺标记（数据恢复后可用）。"""
    try:
        normalized = _normalize_date(date_str)
    except ValueError:
        return False
    path = _resolve_path(file_path)
    with _FILE_LOCK:
        records = load_permanent_gap_records(path)
        if normalized not in records:
            return False
        del records[normalized]
        payload = {
            "updated_at": datetime.now().isoformat(),
            "dates": dict(sorted(records.items())),
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        temp_path.replace(path)
    return True
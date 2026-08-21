"""Bloomberg 额度爆满暂停标记 tombstone — 跨进程持久化。

005-bloomberg-quota-pause: 额度受限时 Bloomberg 可能返回空响应或额度类错误，
若被当作"已拉取"会导致缺数据且不重拉。命中额度信号时 set_quota_pause 置位，
各拉取入口 (fill / BDIB / 日频 / FX / regime) 短路跳过；下一次 fetch 本身
作为探测，成功后 clear_quota_pause，缺口扫描随后自动重拉。

与 permanent_gap_dates 语义区别:
- permanent_gap_dates: 永久空缺（保留窗口已过），永不重拉
- quota_pause: 临时暂停（额度恢复后自动重拉）
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


def _resolve_path(file_path: Optional[Path] = None) -> Path:
    return Path(file_path or Config.QUOTA_PAUSE_FILE)


def load_quota_pause(file_path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """读取暂停标记记录；不存在/解析失败返回 None。"""
    path = _resolve_path(file_path)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to read quota pause marker from {path}: {exc}")
        return None

    if isinstance(payload, dict) and payload.get("quota_paused") is True:
        return payload
    return None


def is_quota_paused(file_path: Optional[Path] = None) -> bool:
    """当前是否处于额度暂停状态。"""
    return load_quota_pause(file_path) is not None


def set_quota_pause(
    reason: str,
    *,
    detail: Optional[str] = None,
    file_path: Optional[Path] = None,
) -> dict[str, Any]:
    """置位暂停标记（幂等，重复置位仅更新 last_seen_at / hit_count）。

    返回写入的记录 dict。
    """
    path = _resolve_path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()

    with _FILE_LOCK:
        existing = load_quota_pause(path) or {}
        entry = {
            "quota_paused": True,
            "reason": reason,
            "detail": detail or existing.get("detail"),
            "first_seen_at": existing.get("first_seen_at", now),
            "last_seen_at": now,
            "hit_count": int(existing.get("hit_count", 0)) + 1,
        }

        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(entry, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        temp_path.replace(path)

    logger.warning(
        "Quota pause SET (reason=%s%s, hit_count=%d)",
        reason, f", detail={detail}" if detail else "", entry["hit_count"],
    )
    return entry


def clear_quota_pause(file_path: Optional[Path] = None) -> bool:
    """清除暂停标记（额度恢复）。返回是否实际清除。"""
    path = _resolve_path(file_path)
    with _FILE_LOCK:
        if not path.exists():
            return False
        try:
            path.unlink()
        except OSError:
            return False
    logger.info("Quota pause CLEARED")
    return True

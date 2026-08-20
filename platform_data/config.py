"""Platform data configuration — environment-driven settings.

Reads from environment variables with sensible defaults for
both single-process (development) and multi-process (production) modes.
"""
from __future__ import annotations

import os

# Backend for handoff exchange: "memory" (default) or "redis".
# Set EMSXVIEW_HANDOFF_BACKEND=redis to enable cross-process handoff.
_HANDOFF_BACKENDS = frozenset({"memory", "redis"})


def _validated_handoff_backend() -> str:
    """读取并校验 HANDOFF_BACKEND 白名单 (M6)。

    非法值启动即抛 ValueError — 拼写错误 (如 "memroy") 不得静默降级 memory,
    否则微服务模式下跨进程交接静默失效且无告警。
    """
    value = os.getenv("EMSXVIEW_HANDOFF_BACKEND", "memory").strip().lower()
    if value not in _HANDOFF_BACKENDS:
        raise ValueError(
            f"EMSXVIEW_HANDOFF_BACKEND 非法值: {value!r} "
            f"(允许: {', '.join(sorted(_HANDOFF_BACKENDS))})"
        )
    return value


HANDOFF_BACKEND: str = _validated_handoff_backend()

# Redis connection URL (only used when HANDOFF_BACKEND=redis).
REDIS_URL: str = os.getenv("EMSXVIEW_REDIS_URL", "redis://localhost:6379/0")

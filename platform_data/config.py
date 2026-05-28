"""Platform data configuration — environment-driven settings.

Reads from environment variables with sensible defaults for
both single-process (development) and multi-process (production) modes.
"""
from __future__ import annotations

import os

# Backend for handoff exchange: "memory" (default) or "redis".
# Set EMSXVIEW_HANDOFF_BACKEND=redis to enable cross-process handoff.
HANDOFF_BACKEND: str = os.getenv("EMSXVIEW_HANDOFF_BACKEND", "memory").lower()

# Redis connection URL (only used when HANDOFF_BACKEND=redis).
REDIS_URL: str = os.getenv("EMSXVIEW_REDIS_URL", "redis://localhost:6379/0")

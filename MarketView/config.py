"""MarketView standalone service configuration."""
from __future__ import annotations

import os

# Handoff backend: "redis" (cross-process) or "memory" (single-process).
# In standalone mode, always "redis" to communicate with the main EMSX service.
os.environ.setdefault("EMSXVIEW_HANDOFF_BACKEND", "redis")
os.environ.setdefault("EMSXVIEW_REDIS_URL", "redis://localhost:6379/0")

HOST: str = os.getenv("MARKETVIEW_HOST", "0.0.0.0")
PORT: int = int(os.getenv("MARKETVIEW_PORT", "8001"))

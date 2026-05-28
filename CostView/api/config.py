"""CostView standalone service configuration."""
from __future__ import annotations

import os

# Handoff backend: "redis" (cross-process) or "memory" (single-process).
os.environ.setdefault("EMSXVIEW_HANDOFF_BACKEND", "redis")
os.environ.setdefault("EMSXVIEW_REDIS_URL", "redis://localhost:6379/0")

HOST: str = os.getenv("COSTVIEW_HOST", "0.0.0.0")
PORT: int = int(os.getenv("COSTVIEW_PORT", "8002"))

# Data directory for SQLite databases (CostView data)
DATA_DIR: str = os.getenv("EMSXVIEW_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))

"""
Extract OpenAPI schema from the FastAPI app without starting the server.

Usage:
    cd backend/api
    python ../../scripts/extract-openapi.py > ../../frontend/src/shared/api-types/openapi.json

This avoids the need for a running server when regenerating types.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the backend/api directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "api"))

from main import app  # noqa: E402

openapi_spec = app.openapi()
print(json.dumps(openapi_spec, indent=2, default=str))

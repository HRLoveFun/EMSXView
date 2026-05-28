"""Path utilities for the API backend.

platform_data is now installed as a pip package (emsxview-platform-data)
via `pip install -e ../../platform_data` from requirements.txt.

PROJECT_ROOT is retained for reference but sys.path manipulation is
no longer necessary — platform_data is importable as a regular package.
"""
from __future__ import annotations

from pathlib import Path

# PROJECT_ROOT points to the EMSX monorepo root (for file-system operations only).
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

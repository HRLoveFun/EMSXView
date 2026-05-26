"""Path and sys.path setup for the API backend.

Provides PROJECT_ROOT and ensures the project root is on sys.path
so that platform_data and other root-level packages are importable.
"""
from __future__ import annotations

import sys
from pathlib import Path

# PROJECT_ROOT points to the EMSX monorepo root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

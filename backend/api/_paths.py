"""Path and sys.path setup for the API backend.

Provides PROJECT_ROOT and ensures the project root is on sys.path
so that platform_data and other root-level packages are importable.

DEPRECATED: This sys.path hack is kept for backward compatibility only.
Packages should be installed via pyproject.toml dependencies or editable
installs (pip install -e ../../platform_data, etc.).

Once all packages declare formal inter-package dependencies, this file
can be removed. See P1 refactoring in the project plan.
"""
from __future__ import annotations

import sys
from pathlib import Path
import warnings

# PROJECT_ROOT points to the EMSX monorepo root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    warnings.warn(
        "_paths.py sys.path hack is deprecated. "
        "Install packages via pyproject.toml dependencies instead.",
        DeprecationWarning,
        stacklevel=2,
    )

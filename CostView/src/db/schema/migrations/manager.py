"""
DEPRECATED — MigrationManager moved to DataPipeline.src.storage.schema.migrations.manager.

This module re-exports ``MigrationManager`` for backward compatibility.
New code should import from:
    DataPipeline.src.storage.schema.migrations.manager
"""

import warnings

from DataPipeline.src.storage.schema.migrations.manager import (  # noqa: F401
    EXPECTED_VERSIONS,
    MigrationManager,
)

warnings.warn(
    "CostView.src.db.schema.migrations.manager is deprecated — "
    "import from DataPipeline.src.storage.schema.migrations.manager instead.",
    DeprecationWarning,
    stacklevel=2,
)

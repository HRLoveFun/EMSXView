"""
DEPRECATED — Facade moved to DataPipeline.src.storage.facade.

This module re-exports for backward compatibility.
New code: ``from DataPipeline.src.storage.facade import DatabaseFacade``
"""

import warnings

from DataPipeline.src.storage.facade import DatabaseFacade, CostViewDatabase  # noqa: F401

warnings.warn(
    "CostView.src.db.facade is deprecated — import from DataPipeline.src.storage.facade instead.",
    DeprecationWarning,
    stacklevel=2,
)

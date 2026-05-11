"""
DEPRECATED — processed_fills_db package.

All functionality has been migrated to DataPipeline.src.storage.repositories.
Use SqliteFillReadRepository / SqliteFillWriteRepository instead.

This stub re-exports only init_processed_fills_schema (still needed for
schema bootstrap). All other imports will emit a DeprecationWarning.
"""

import warnings as _w

from ..repositories._schema import init_processed_fills_schema  # noqa: F401 — re-exported for legacy callers

_w.warn(
    "processed_fills_db package is deprecated. "
    "Use DataPipeline.src.storage.repositories.fills_read / fills_write "
    "or the CostViewDatabase facade instead.",
    DeprecationWarning,
    stacklevel=2,
)
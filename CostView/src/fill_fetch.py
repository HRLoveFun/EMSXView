"""RE-EXPORT STUB — migrated to DataPipeline.

This file is a backward-compatibility re-export.
All code has been migrated to DataPipeline/src/ingestion/fill_fetch.py.
"""

import warnings as _w

_w.warn(
    "CostView.src.fill_fetch has been migrated to DataPipeline.src.ingestion.fill_fetch. "
    "Update your import: 'from DataPipeline.src.ingestion.fill_fetch import ...'",
    DeprecationWarning,
    stacklevel=2,
)

from DataPipeline.src.ingestion.fill_fetch import *  # noqa: F401, E402, F403

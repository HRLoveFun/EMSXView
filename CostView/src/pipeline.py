"""
Pipeline — re-export stub.

Migrated to DataPipeline/src/orchestration/pipeline.py.
This stub forwards imports for backward compatibility.
"""

import warnings as _w

_w.warn(
    "CostView.src.pipeline has been migrated to DataPipeline.src.orchestration.pipeline. "
    "Update your import: 'from DataPipeline.src.orchestration.pipeline import ...'",
    DeprecationWarning,
    stacklevel=2,
)

from DataPipeline.src.orchestration.pipeline import *  # noqa: F401, E402, F403

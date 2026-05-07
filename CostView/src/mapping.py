"""RE-EXPORT STUB — migrated to DataPipeline.

This file is a backward-compatibility re-export.
All code has been migrated to DataPipeline/src/common/mapping.py.
"""

import warnings as _w

_w.warn(
    "CostView.src.mapping has been migrated to DataPipeline.src.common.mapping. "
    "Update your import: 'from DataPipeline.src.common.mapping import ...'",
    DeprecationWarning,
    stacklevel=2,
)

from DataPipeline.src.common.mapping import *  # noqa: F401, E402, F403
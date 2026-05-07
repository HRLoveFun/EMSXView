"""RE-EXPORT STUB — migrated to DataPipeline.

This file is a backward-compatibility re-export.
All code has been migrated to DataPipeline/src/common/schema.py.
"""

import warnings as _w

_w.warn(
    "CostView.src.schema has been migrated to DataPipeline.src.common.schema. "
    "Update your import: 'from DataPipeline.src.common.schema import ...'",
    DeprecationWarning,
    stacklevel=2,
)

from DataPipeline.src.common.schema import *  # noqa: F401, E402, F403
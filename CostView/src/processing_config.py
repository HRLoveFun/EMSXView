"""RE-EXPORT STUB — migrated to DataPipeline.

This file is a backward-compatibility re-export.
All code has been migrated to DataPipeline/src/common/processing_config.py.
"""

import warnings as _w

_w.warn(
    "CostView.src.processing_config has been migrated to DataPipeline.src.common.processing_config. "
    "Update your import: 'from DataPipeline.src.common.processing_config import ...'",
    DeprecationWarning,
    stacklevel=2,
)

from DataPipeline.src.common.processing_config import *  # noqa: F401, E402, F403
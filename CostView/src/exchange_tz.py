"""RE-EXPORT STUB — migrated to DataPipeline.

This file is a backward-compatibility re-export.
All code has been migrated to DataPipeline/src/common/exchange_tz.py.
"""

import warnings as _w

_w.warn(
    "CostView.src.exchange_tz has been migrated to DataPipeline.src.common.exchange_tz. "
    "Update your import: 'from DataPipeline.src.common.exchange_tz import ...'",
    DeprecationWarning,
    stacklevel=2,
)

from DataPipeline.src.common.exchange_tz import *  # noqa: F401, E402, F403
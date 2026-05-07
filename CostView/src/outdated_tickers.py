"""RE-EXPORT STUB — migrated to DataPipeline.

This file is a backward-compatibility re-export.
All code has been migrated to DataPipeline/src/common/outdated_tickers.py.
"""

import warnings as _w

_w.warn(
    "CostView.src.outdated_tickers has been migrated to DataPipeline.src.common.outdated_tickers. "
    "Update your import: 'from DataPipeline.src.common.outdated_tickers import ...'",
    DeprecationWarning,
    stacklevel=2,
)

from DataPipeline.src.common.outdated_tickers import *  # noqa: F401, E402, F403
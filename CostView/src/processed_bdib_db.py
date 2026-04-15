"""
Backward-compatible alias for FillBDIBDB.

This module was renamed to fill_bdib_db.py to match D:\\Evaluation convention:
  - processed_bdib (old name) → fill_bdib.db (new name)

The class ProcessedBDIBDB is now an alias for FillBDIBDB.
All new code should import from fill_bdib_db instead.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependency at module load time
def __getattr__(name: str):
    if name == "ProcessedBDIBDB":
        from .fill_bdib_db import FillBDIBDB
        logger.warning(
            "ProcessedBDIBDB is deprecated; import FillBDIBDB from "
            ".fill_bdib_db instead. This backward-compatible alias will be "
            "removed in a future version."
        )
        return FillBDIBDB
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""
Pipeline execution context — shared state, config, and DB access for stages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from DataPipeline.storage.connection import ConnectionManager
from DataPipeline.storage.facade import DatabaseFacade

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Pipeline context — shared state, config, and DB connections across stages."""

    target_dates: List[str] = field(default_factory=list)
    force: bool = False
    excel_dir: Optional[Path] = None
    config: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    is_successful: bool = True
    errors: List[Dict[str, Any]] = field(default_factory=list)

    # Databases (lazy-init: ConnectionManager + DatabaseFacade created on first access)
    _db: Optional[DatabaseFacade] = field(default=None, init=False, repr=False)
    _cm: Optional[ConnectionManager] = field(default=None, init=False, repr=False)

    @property
    def connection_manager(self) -> ConnectionManager:
        """Shared ConnectionManager (lazy-init)."""
        if self._cm is None:
            self._cm = ConnectionManager()
        return self._cm

    @property
    def db(self) -> DatabaseFacade:
        """Unified database access facade (lazy-init)."""
        if self._db is None:
            self._db = DatabaseFacade(self.connection_manager)
        return self._db

    def log_error(self, stage_name: str, error: Exception) -> None:
        """Record a stage error and mark the context as failed."""
        self.errors.append({"stage": stage_name, "error": str(error)})
        self.is_successful = False
        logger.error(f"Error in stage '{stage_name}': {error}", exc_info=True)

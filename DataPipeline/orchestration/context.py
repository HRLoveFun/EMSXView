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
    """流水线上下文，在各个处理阶段之间共享状态、配置和数据库连接。"""

    target_dates: List[str] = field(default_factory=list)
    force: bool = False
    excel_dir: Optional[Path] = None
    config: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    is_successful: bool = True
    errors: List[Dict[str, Any]] = field(default_factory=list)

    # 数据库（懒初始化，首次访问时创建 ConnectionManager + DatabaseFacade）
    _db: Optional[DatabaseFacade] = field(default=None, init=False, repr=False)
    _cm: Optional[ConnectionManager] = field(default=None, init=False, repr=False)

    @property
    def connection_manager(self) -> ConnectionManager:
        """共享的 ConnectionManager（懒初始化）。"""
        if self._cm is None:
            self._cm = ConnectionManager()
        return self._cm

    @property
    def db(self) -> DatabaseFacade:
        """统一的数据库访问入口（懒初始化）。"""
        if self._db is None:
            self._db = DatabaseFacade(self.connection_manager)
        return self._db

    def log_error(self, stage_name: str, error: Exception) -> None:
        """记录阶段性错误并将上下文标记为失败。"""
        self.errors.append({"stage": stage_name, "error": str(error)})
        self.is_successful = False
        logger.error(f"Error in stage '{stage_name}': {error}", exc_info=True)

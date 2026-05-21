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
    """流水线上下文，用于在各个处理阶段之间共享状态、配置和数据源连接。"""

    # 基础配置
    target_dates: List[str] = field(default_factory=list)
    force: bool = False
    excel_dir: Optional[Path] = None
    config: Dict[str, Any] = field(default_factory=dict)

    # 数据库子系统统一入口
    _db: Optional[DatabaseFacade] = field(default=None, init=False, repr=False)

    # 数据库连接管理器
    connection_manager: Optional[ConnectionManager] = None

    # 流水线阶段性产出结果
    summary: Dict[str, Any] = field(default_factory=dict)

    # 状态与错误追踪
    is_successful: bool = True
    errors: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def db(self) -> DatabaseFacade:
        """统一的数据库访问入口（懒初始化）。

        所有新的 Repository 访问应通过此属性获取，例如:
            context.db.fills_read.get_fills_for_date("20260408")
            context.db.market_data_write.upsert_bdib_data(df)
        """
        if self._db is None:
            self._db = DatabaseFacade(self.get_connection_manager())
        return self._db

    def get_connection_manager(self) -> ConnectionManager:
        """Get or lazily create the ConnectionManager singleton."""
        if self.connection_manager is None:
            self.connection_manager = ConnectionManager()
        return self.connection_manager

    def log_error(self, stage_name: str, error: Exception) -> None:
        """记录阶段性错误并将上下文标记为失败。"""
        self.errors.append({"stage": stage_name, "error": str(error)})
        self.is_successful = False
        logger.error(f"Error in stage '{stage_name}': {error}", exc_info=True)

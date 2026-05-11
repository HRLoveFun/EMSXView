"""
Pipeline execution context — shared state, config, and DB access for stages.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from DataPipeline.src.storage.connection import ConnectionManager
from DataPipeline.src.storage.fill_bdib_db import FillBDIBDB
from DataPipeline.src.storage.processed_raw_bdib_db import ProcessedRawBDIBDB
from DataPipeline.src.storage.raw_bdib_db import RawBDIBDB
from DataPipeline.src.storage.raw_fills_db import RawFillsDB
from DataPipeline.src.storage.facade import CostViewDatabase

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """流水线上下文，用于在各个处理阶段之间共享状态、配置和数据源连接。"""

    # 基础配置
    target_dates: List[str] = field(default_factory=list)
    force: bool = False
    excel_dir: Optional[Path] = None
    config: Dict[str, Any] = field(default_factory=dict)

    # 数据库子系统统一入口（迭代 1 新增）
    _db: Optional[CostViewDatabase] = field(default=None, init=False, repr=False)

    # 数据库连接管理器（Phase 1 新增：统一连接生命周期）
    connection_manager: Optional[ConnectionManager] = None

    # 数据库连接单例（保留向后兼容，逐步迁移到 context.db）
    raw_db: Optional[RawFillsDB] = None
    raw_bdib_db: Optional[RawBDIBDB] = None
    processed_raw_bdib_db: Optional[ProcessedRawBDIBDB] = None
    proc_bdib_db: Optional[FillBDIBDB] = None

    # 流水线阶段性产出结果 (用于记录或供下游阶段使用)
    summary: Dict[str, Any] = field(default_factory=dict)

    # 状态与错误追踪
    is_successful: bool = True
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        """Warn if legacy DB fields are set directly."""
        legacy_fields = {
            "raw_db": self.raw_db,
            "raw_bdib_db": self.raw_bdib_db,
            "processed_raw_bdib_db": self.processed_raw_bdib_db,
            "proc_bdib_db": self.proc_bdib_db,
        }
        used = [name for name, val in legacy_fields.items() if val is not None]
        if used:
            warnings.warn(
                f"PipelineContext legacy fields {used} are deprecated. "
                "Use context.db (CostViewDatabase facade) instead. "
                "See docs/spec/data-domain.md for the Data Platform extraction roadmap.",
                DeprecationWarning,
                stacklevel=2,
            )

    @property
    def db(self) -> CostViewDatabase:
        """统一的数据库访问入口（懒初始化）。

        所有新的 Repository 访问应通过此属性获取，例如:
            context.db.fills_read.get_fills_for_date("20260408")
            context.db.market_data_write.upsert_bdib_data(df)
        """
        if self._db is None:
            self._db = CostViewDatabase(self.get_connection_manager())
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

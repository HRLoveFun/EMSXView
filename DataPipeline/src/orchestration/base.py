"""
Abstract base stage and utility helpers for the pipeline framework.
"""

from __future__ import annotations

import abc
import logging
from typing import Optional

from .context import PipelineContext

logger = logging.getLogger(__name__)


class BaseStage(abc.ABC):
    """流水线处理阶段的抽象基类。"""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """返回当前阶段的名称。"""
        pass

    def execute(self, context: PipelineContext) -> bool:
        """
        执行阶段逻辑，包含标准的日志记录和顶层错误捕获。
        返回 True 表示成功，返回 False 表示发生致命错误。
        """
        logger.info("=" * 60)
        logger.info(f"==> Starting Stage: {self.name}")
        logger.info("=" * 60)
        try:
            return self.process(context)
        except Exception as e:
            context.log_error(self.name, e)
            return False

    @abc.abstractmethod
    def process(self, context: PipelineContext) -> bool:
        """
        核心业务逻辑实现方法。必须由子类实现。
        如果返回 False，则中断后续流水线执行。
        """
        pass


def _to_iso_safe(d: str) -> Optional[str]:
    """Convert 'YYYYMMDD' or 'YYYY-MM-DD' → 'YYYY-MM-DD'; None on bad input."""
    if not d or not isinstance(d, str):
        return None
    s = d.strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None

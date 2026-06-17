"""重试策略 — S1 外部数据摄入专用。

支持指数退避和降级处理，外部 API 调用失败时自动重试。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from DataPipeline.config import Config

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RetryConfig:
    """重试策略配置"""

    # 最大重试次数
    max_retries: int = 3
    # 基础延迟（秒）
    base_delay_seconds: float = 1.0
    # 指数退避因子
    backoff_factor: float = 2.0

    @classmethod
    def from_config(cls, config: Config) -> RetryConfig:
        """从 Config 实例创建重试配置"""
        return cls(
            max_retries=config.GUARDRAIL_RETRY_MAX,
            base_delay_seconds=1.0,
            backoff_factor=2.0,
        )


@dataclass
class RetryResult:
    """重试执行结果"""

    # 是否最终成功
    success: bool
    # 实际结果（成功时）
    result: Any = None
    # 总重试次数
    attempts: int = 0
    # 总耗时（秒）
    total_delay_seconds: float = 0.0
    # 最后一次错误（失败时）
    last_error: str | None = None


class RetryPolicy:
    """S1 外部数据摄入的重试策略。

    支持指数退避：第 n 次重试延迟 = base_delay * backoff_factor^(n-1)
    超过重试上限后返回降级结果。

    用法::

        policy = RetryPolicy(RetryConfig(max_retries=3))
        result = policy.execute_with_retry(my_async_func)
    """

    def __init__(self, config: RetryConfig) -> None:
        self._config = config

    def execute_with_retry_sync(
        self,
        fn: Callable[[], T],
        context: dict[str, Any] | None = None,
    ) -> RetryResult:
        """同步版本的重试执行包装器。

        Args:
            fn: 可调用对象（如 Bloomberg API 调用）
            context: 可选的上下文信息（用于日志）

        Returns:
            RetryResult: 包含结果或错误信息
        """
        ctx_str = f" (context={context})" if context else ""
        total_delay = 0.0

        for attempt in range(self._config.max_retries + 1):
            try:
                result = fn()
                if attempt > 0:
                    logger.info(
                        "重试成功: 第 %d 次尝试%s，总延迟 %.1fs",
                        attempt + 1,
                        ctx_str,
                        total_delay,
                    )
                return RetryResult(
                    success=True,
                    result=result,
                    attempts=attempt + 1,
                    total_delay_seconds=total_delay,
                )
            except Exception as e:
                if attempt < self._config.max_retries:
                    delay = self._config.base_delay_seconds * (
                        self._config.backoff_factor ** attempt
                    )
                    total_delay += delay
                    logger.warning(
                        "重试 %d/%d: 第 %d 次尝试失败%s，%s 后重试 (error=%s)",
                        attempt + 1,
                        self._config.max_retries,
                        attempt + 1,
                        ctx_str,
                        f"{delay:.1f}s",
                        e,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "重试耗尽: 全部 %d 次尝试失败%s (last_error=%s)",
                        self._config.max_retries + 1,
                        ctx_str,
                        e,
                    )
                    return RetryResult(
                        success=False,
                        attempts=attempt + 1,
                        total_delay_seconds=total_delay,
                        last_error=str(e),
                    )

        return RetryResult(
            success=False,
            attempts=self._config.max_retries + 1,
            total_delay_seconds=total_delay,
            last_error="未知错误",
        )

    async def execute_with_retry(
        self,
        fn: Callable[[], Any],
        context: dict[str, Any] | None = None,
    ) -> RetryResult:
        """异步版本的重试执行包装器。

        Args:
            fn: 异步可调用对象
            context: 可选的上下文信息

        Returns:
            RetryResult: 包含结果或错误信息
        """
        ctx_str = f" (context={context})" if context else ""
        total_delay = 0.0

        for attempt in range(self._config.max_retries + 1):
            try:
                result = await fn()  # type: ignore[misc]
                if attempt > 0:
                    logger.info(
                        "重试成功: 第 %d 次尝试%s，总延迟 %.1fs",
                        attempt + 1,
                        ctx_str,
                        total_delay,
                    )
                return RetryResult(
                    success=True,
                    result=result,
                    attempts=attempt + 1,
                    total_delay_seconds=total_delay,
                )
            except Exception as e:
                if attempt < self._config.max_retries:
                    delay = self._config.base_delay_seconds * (
                        self._config.backoff_factor ** attempt
                    )
                    total_delay += delay
                    logger.warning(
                        "重试 %d/%d: %s 后重试 (error=%s)",
                        attempt + 1,
                        self._config.max_retries,
                        f"{delay:.1f}s",
                        e,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "重试耗尽: 全部 %d 次尝试失败 (last_error=%s)",
                        self._config.max_retries + 1,
                        e,
                    )
                    return RetryResult(
                        success=False,
                        attempts=attempt + 1,
                        total_delay_seconds=total_delay,
                        last_error=str(e),
                    )

        return RetryResult(
            success=False,
            attempts=self._config.max_retries + 1,
            total_delay_seconds=total_delay,
            last_error="未知错误",
        )

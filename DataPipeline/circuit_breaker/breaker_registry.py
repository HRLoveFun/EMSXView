"""熔断器注册表 — 按 run_id 隔离。

每个 PipelineRun 独立维护一组熔断器实例，不同日期的管道运行互不影响。
"""

from __future__ import annotations

import logging

from DataPipeline.circuit_breaker.breaker import CircuitBreaker
from DataPipeline.config import Config

logger = logging.getLogger(__name__)


class CircuitBreakerRegistry:
    """按 run_id 隔离的熔断器注册表。

    用法::

        registry = CircuitBreakerRegistry(config=Config)
        breaker = registry.get_or_create("20260616-001", "S2")
        breaker.record_failure(SeverityLevel.ERROR, "校验失败")
    """

    def __init__(self, config: Config | None = None) -> None:
        self._config = config or Config()
        # 内部存储: {run_id: {stage_name: CircuitBreaker}}
        self._breakers: dict[str, dict[str, CircuitBreaker]] = {}

    def get_or_create(self, run_id: str, stage_name: str) -> CircuitBreaker:
        """获取或创建指定运行和阶段的熔断器实例。

        Args:
            run_id: 管道运行 ID
            stage_name: 阶段名称

        Returns:
            CircuitBreaker 实例
        """
        if run_id not in self._breakers:
            self._breakers[run_id] = {}

        if stage_name not in self._breakers[run_id]:
            breaker = CircuitBreaker(
                run_id=run_id,
                stage_name=stage_name,
                max_failures=self._config.GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD,
            )
            self._breakers[run_id][stage_name] = breaker
            logger.debug(
                "创建熔断器: run_id=%s, stage=%s, threshold=%d",
                run_id,
                stage_name,
                self._config.GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD,
            )

        return self._breakers[run_id][stage_name]

    def get(self, run_id: str, stage_name: str) -> CircuitBreaker | None:
        """获取现有的熔断器实例（不自动创建）。

        Args:
            run_id: 管道运行 ID
            stage_name: 阶段名称

        Returns:
            CircuitBreaker 实例或 None
        """
        return self._breakers.get(run_id, {}).get(stage_name)

    def get_all_for_run(self, run_id: str) -> dict[str, CircuitBreaker]:
        """获取指定运行的所有熔断器实例"""
        return dict(self._breakers.get(run_id, {}))

    def any_open(self, run_id: str) -> bool:
        """检查指定运行是否存在处于 OPEN 状态的熔断器"""
        return any(
            breaker.is_open
            for breaker in self._breakers.get(run_id, {}).values()
        )

    def reset_all(self, run_id: str) -> None:
        """重置指定运行的所有熔断器"""
        for breaker in self._breakers.get(run_id, {}).values():
            breaker.reset()

    def cleanup(self, run_id: str) -> None:
        """清理指定运行的熔断器实例（管道完成后释放内存）"""
        if run_id in self._breakers:
            del self._breakers[run_id]
            logger.debug("清理熔断器注册表: run_id=%s", run_id)

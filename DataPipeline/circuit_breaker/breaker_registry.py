"""熔断器注册表 — 按 run_id 隔离, 失败计数跨 run 持久 (M8)。

每个 PipelineRun 独立维护一组熔断器实例，不同日期的管道运行互不影响。
但阶段失败计数在 run 结束后保留: 单次 run 内每阶段仅执行一次,
若计数随 run 销毁, Error 阈值 (默认 3) 永远不可达, 熔断器形同虚设。
跨 run 累计使"连续 N 次运行失败"真实触发熔断; OPEN 状态在 run 结束时
转为 HALF_OPEN, 下一次运行作为探测。
"""

from __future__ import annotations

import logging

from DataPipeline.circuit_breaker.breaker import CircuitBreaker
from DataPipeline.config import Config

logger = logging.getLogger(__name__)


class CircuitBreakerRegistry:
    """按 run_id 隔离、失败计数跨 run 持久的熔断器注册表。

    用法::

        registry = CircuitBreakerRegistry(config=Config)
        breaker = registry.get_or_create("20260616-001", "S2")
        breaker.record_failure(SeverityLevel.ERROR, "校验失败")
    """

    def __init__(self, config: Config | None = None) -> None:
        self._config = config or Config()
        # 内部存储: {run_id: {stage_name: CircuitBreaker}}
        self._breakers: dict[str, dict[str, CircuitBreaker]] = {}
        # M8: 跨 run 持久状态 — {stage_name: CircuitBreaker}, 保留失败计数
        self._persistent: dict[str, CircuitBreaker] = {}

    def get_or_create(self, run_id: str, stage_name: str) -> CircuitBreaker:
        """获取或创建指定运行和阶段的熔断器实例。

        若存在跨 run 持久实例, 复用其失败计数 (仅更新 run_id 归属),
        使 Error 阈值在多次运行间可累积达成。

        Args:
            run_id: 管道运行 ID
            stage_name: 阶段名称

        Returns:
            CircuitBreaker 实例
        """
        if run_id not in self._breakers:
            self._breakers[run_id] = {}

        if stage_name not in self._breakers[run_id]:
            persisted = self._persistent.get(stage_name)
            if persisted is not None:
                # 复用跨 run 计数 (M8)
                persisted.run_id = run_id
                self._breakers[run_id][stage_name] = persisted
                logger.debug(
                    "复用跨 run 熔断器: stage=%s, 失败计数=%d, 状态=%s",
                    stage_name, persisted.failure_count, persisted.state.value,
                )
            else:
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
        """结束运行时持久化失败计数, 释放运行级引用 (M8)。

        - OPEN 状态转为 HALF_OPEN: 下一运行作为探测, 成功后自动恢复 CLOSED
        - 其余状态 (CLOSED 累积计数 / HALF_OPEN) 原样保留
        """
        if run_id not in self._breakers:
            return
        for stage_name, breaker in self._breakers[run_id].items():
            if breaker.is_open:
                breaker.reset()  # OPEN → HALF_OPEN (跨 run 探测)
            self._persistent[stage_name] = breaker
        del self._breakers[run_id]
        logger.debug("清理熔断器注册表: run_id=%s (计数已持久化)", run_id)

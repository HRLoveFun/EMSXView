"""熔断器三态状态机 — 按管道运行实例隔离。

实现闭合（CLOSED）→ 断开（OPEN）→ 半开（HALF_OPEN）三态转移，
支持三级严重等级（Info/Error/Critical）的差异化熔断策略。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from DataPipeline.validation.enums import BreakerState, SeverityLevel

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """按管道运行实例隔离的熔断器。

    状态转移逻辑：
    - CLOSED → (连续失败>=阈值) → OPEN
    - CLOSED → (Critical 异常) → OPEN
    - OPEN → (手动重置) → HALF_OPEN
    - HALF_OPEN → (探测成功) → CLOSED
    - HALF_OPEN → (探测失败) → OPEN
    """

    def __init__(
        self,
        run_id: str,
        stage_name: str,
        max_failures: int = 3,
        alert_callback: Callable[..., None] | None = None,
    ) -> None:
        """初始化熔断器。

        Args:
            run_id: 所属管道运行 ID
            stage_name: 被监控的阶段名称
            max_failures: 连续失败触发熔断的阈值
            alert_callback: 告警回调函数（可选）
        """
        self.run_id = run_id
        self.stage_name = stage_name
        self._state: BreakerState = BreakerState.CLOSED
        self.failure_count: int = 0
        self.max_failures: int = max_failures
        self._alert_callback = alert_callback
        # 熔断触发时间
        self.triggered_at: datetime | None = None
        # 触发原因
        self.trigger_reason: str | None = None
        # 最近一次失败的详情
        self.last_failure_detail: str | None = None
        # 重置时间
        self.reset_at: datetime | None = None

    @property
    def state(self) -> BreakerState:
        """当前熔断状态"""
        return self._state

    @property
    def is_open(self) -> bool:
        """熔断器是否处于断开（阻断）状态"""
        return self._state == BreakerState.OPEN

    def before_stage(self) -> bool:
        """阶段执行前检查。

        Returns:
            True 表示允许执行，False 表示阻断
        """
        if self._state == BreakerState.OPEN:
            logger.warning(
                "熔断阻断: run_id=%s, stage=%s, reason=%s",
                self.run_id,
                self.stage_name,
                self.trigger_reason or "未知",
            )
            return False
        if self._state == BreakerState.HALF_OPEN:
            logger.info(
                "半开探测: run_id=%s, stage=%s",
                self.run_id,
                self.stage_name,
            )
        return True

    def record_success(self) -> None:
        """记录执行成功，重置失败计数。

        仅当状态为 CLOSED 时调用。HALF_OPEN 状态成功后应转为 CLOSED。
        """
        if self._state == BreakerState.HALF_OPEN:
            logger.info(
                "探测成功: run_id=%s, stage=%s, 状态恢复 CLOSED",
                self.run_id,
                self.stage_name,
            )
            self._state = BreakerState.CLOSED
            self.failure_count = 0
            self.trigger_reason = None
            self.triggered_at = None
            return

        self.failure_count = 0
        self.last_failure_detail = None

    def record_failure(self, severity: SeverityLevel, reason: str = "") -> bool:
        """记录执行失败。

        按严重等级分路由：
        - Critical: 立即设 OPEN（即使在 HALF_OPEN 也立即熔断）
        - Error: 累加失败计数，达阈值设 OPEN；HALF_OPEN 状态下单次 ERROR 即回退到 OPEN
        - Info: 仅记录不触发熔断

        Args:
            severity: 失败严重等级
            reason: 失败原因描述

        Returns:
            True 表示触发了熔断（状态变为 OPEN），False 表示未触发
        """
        self.last_failure_detail = reason

        # HALF_OPEN 探测模式下任何非 INFO 失败都应回退到 OPEN
        if self._state == BreakerState.HALF_OPEN and severity in (SeverityLevel.ERROR, SeverityLevel.CRITICAL):
            self._transition_to_open(f"探测失败（HALF_OPEN 回退）: {reason}")
            return True

        if severity == SeverityLevel.CRITICAL:
            # Critical 异常立即熔断
            self._transition_to_open(f"Critical 异常: {reason}")
            return True

        if severity == SeverityLevel.ERROR:
            self.failure_count += 1
            logger.warning(
                "阶段 %s 失败 (第 %d/%d 次): %s",
                self.stage_name,
                self.failure_count,
                self.max_failures,
                reason,
            )
            if self.failure_count >= self.max_failures:
                self._transition_to_open(
                    f"连续失败 {self.failure_count} 次（阈值 {self.max_failures}）"
                )
                return True

        # Info 级不触发熔断
        if severity == SeverityLevel.INFO:
            logger.info(
                "阶段 %s Info 级异常: %s (不计入熔断计数)",
                self.stage_name,
                reason,
            )

        return False

    def reset(self) -> None:
        """手动重置熔断状态 → HALF_OPEN 探测模式"""
        old_state = self._state
        self._state = BreakerState.HALF_OPEN
        self.reset_at = datetime.now(timezone.utc)
        logger.info(
            "手动重置熔断: run_id=%s, stage=%s, %s → HALF_OPEN",
            self.run_id,
            self.stage_name,
            old_state.value,
        )

    # ── 私有辅助方法 ──

    def _transition_to_open(self, reason: str) -> None:
        """将状态转移到 OPEN（熔断阻断）"""
        self._state = BreakerState.OPEN
        self.triggered_at = datetime.now(timezone.utc)
        self.trigger_reason = reason
        logger.error(
            "熔断触发: run_id=%s, stage=%s, reason=%s",
            self.run_id,
            self.stage_name,
            reason,
        )
        # 调用告警回调
        if self._alert_callback:
            try:
                self._alert_callback(self)
            except Exception as e:
                logger.error("告警回调执行失败: %s", e)

"""告警通知机制 — 结构化日志输出 + 扩展点。

初期以结构化日志形式输出告警，保留外部通知渠道（邮件/Webhook/SMS）扩展点。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from DataPipeline.circuit_breaker.breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# 告警级别映射
ALERT_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
}


@dataclass
class AlertEvent:
    """告警事件数据结构"""

    # 告警标题
    title: str
    # 告警描述
    message: str
    # 告警级别
    level: str = "error"
    # 相关运行 ID
    run_id: str = ""
    # 相关阶段名称
    stage_name: str = ""
    # 额外元数据
    metadata: dict[str, str] = field(default_factory=dict)
    # 告警发生时间
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def send_alert(
    title: str,
    message: str,
    level: str = "error",
    run_id: str = "",
    stage_name: str = "",
    **metadata: str,
) -> AlertEvent:
    """发送告警通知。

    初期以结构化日志形式输出，保留外部通知渠道扩展点。

    Args:
        title: 告警标题
        message: 告警详细描述
        level: 告警级别（critical/error/warning）
        run_id: 相关运行 ID
        stage_name: 相关阶段名称
        **metadata: 额外元数据

    Returns:
        AlertEvent: 创建的告警事件实例
    """
    event = AlertEvent(
        title=title,
        message=message,
        level=level,
        run_id=run_id,
        stage_name=stage_name,
        metadata=dict(metadata),
    )

    log_level = ALERT_LEVELS.get(level, logging.ERROR)
    logger.log(
        log_level,
        "[ALERT:%s] %s | run_id=%s stage=%s | %s | meta=%s",
        level.upper(),
        title,
        run_id,
        stage_name,
        message,
        metadata,
    )

    # 扩展点：在此处添加邮件/Webhook/SMS 通知渠道
    # _send_email_notification(event)
    # _send_webhook_notification(event)

    return event


def alert_callback(breaker: CircuitBreaker) -> AlertEvent:
    """熔断器告警回调函数。

    由 CircuitBreaker 在熔断触发时调用。

    Args:
        breaker: 触发熔断的 CircuitBreaker 实例

    Returns:
        AlertEvent: 告警事件
    """
    return send_alert(
        title=f"管道熔断: {breaker.stage_name}",
        message=f"阶段 {breaker.stage_name} 触发熔断: {breaker.trigger_reason}",
        level="critical",
        run_id=breaker.run_id,
        stage_name=breaker.stage_name,
        state=breaker.state.value,
        failure_count=str(breaker.failure_count),
    )

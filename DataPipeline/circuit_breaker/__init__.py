"""熔断机制 — 管道异常自动阻断与告警。

实现按运行 ID 隔离的三态熔断器（闭合/半开/断开），支持三级严重等级
（Info/Error/Critical），以及 S1 阶段专用重试策略。
"""

from DataPipeline.circuit_breaker.breaker import CircuitBreaker
from DataPipeline.circuit_breaker.breaker_registry import CircuitBreakerRegistry
from DataPipeline.circuit_breaker.retry_policy import RetryConfig, RetryPolicy
from DataPipeline.circuit_breaker.alert import AlertEvent, send_alert

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "RetryConfig",
    "RetryPolicy",
    "AlertEvent",
    "send_alert",
]

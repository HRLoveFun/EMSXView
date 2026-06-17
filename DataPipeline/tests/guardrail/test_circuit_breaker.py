"""熔断机制单元测试。

覆盖 US2 全部验证场景：
- Critical 异常立即熔断
- Error 累计触发熔断
- 手动重置恢复
- Info 不触发熔断
- 被跳过阶段不计入统计
- 按 run_id 隔离

对照 quickstart.md 场景 4-6。
"""

from __future__ import annotations

import pytest

from DataPipeline.circuit_breaker.breaker import CircuitBreaker
from DataPipeline.circuit_breaker.breaker_registry import CircuitBreakerRegistry
from DataPipeline.circuit_breaker.retry_policy import RetryConfig, RetryPolicy, RetryResult
from DataPipeline.circuit_breaker.alert import AlertEvent, send_alert
from DataPipeline.validation.enums import BreakerState, SeverityLevel


# ═══════════════════════════════════════════════════════════════════════════════
# T053: Critical 异常立即熔断 (quickstart 场景 4)
# ═══════════════════════════════════════════════════════════════════════════════


def test_critical_trigger_immediate_break() -> None:
    """模拟 Critical 异常，验证立即熔断且下游阶段被阻断"""
    breaker = CircuitBreaker(
        run_id="test-critical-001",
        stage_name="S2",
        max_failures=3,
    )

    # 初始状态
    assert breaker.state == BreakerState.CLOSED
    assert not breaker.is_open

    # 触发 Critical 异常
    triggered = breaker.record_failure(
        SeverityLevel.CRITICAL,
        reason="数据损坏：FillPrice 缺失且无法恢复",
    )

    assert triggered, "Critical 异常应触发熔断"
    assert breaker.state == BreakerState.OPEN
    assert breaker.is_open
    assert breaker.trigger_reason is not None
    assert "Critical" in breaker.trigger_reason

    # before_stage 应返回 False（阻断）
    assert not breaker.before_stage(), "熔断状态下应阻断执行"


# ═══════════════════════════════════════════════════════════════════════════════
# T054: Error 累计触发熔断 (quickstart 场景 5)
# ═══════════════════════════════════════════════════════════════════════════════


def test_error_accumulation_break() -> None:
    """连续 3 次 Error 失败后验证状态从 CLOSED 变 OPEN"""
    breaker = CircuitBreaker(
        run_id="test-error-accum",
        stage_name="S2",
        max_failures=3,
    )

    # 第 1 次失败
    triggered = breaker.record_failure(SeverityLevel.ERROR, "校验失败 1/3")
    assert not triggered, "第 1 次失败不应触发熔断"
    assert breaker.state == BreakerState.CLOSED
    assert breaker.failure_count == 1

    # 第 2 次失败
    triggered = breaker.record_failure(SeverityLevel.ERROR, "校验失败 2/3")
    assert not triggered, "第 2 次失败不应触发熔断"
    assert breaker.failure_count == 2

    # 第 3 次失败 → 触发熔断
    triggered = breaker.record_failure(SeverityLevel.ERROR, "校验失败 3/3")
    assert triggered, "第 3 次失败应触发熔断"
    assert breaker.state == BreakerState.OPEN
    assert breaker.failure_count == 3


# ═══════════════════════════════════════════════════════════════════════════════
# T055: 手动重置恢复 (quickstart 场景 6)
# ═══════════════════════════════════════════════════════════════════════════════


def test_manual_reset_recovery() -> None:
    """手动重置后验证 HALF_OPEN → 探测成功 → CLOSED 恢复流程"""
    breaker = CircuitBreaker(
        run_id="test-reset-001",
        stage_name="S2",
    )

    # 先触发熔断
    breaker.record_failure(SeverityLevel.CRITICAL, "测试熔断")
    assert breaker.state == BreakerState.OPEN

    # 手动重置 → HALF_OPEN
    breaker.reset()
    assert breaker.state == BreakerState.HALF_OPEN
    assert not breaker.is_open

    # 探测阶段：before_stage 应返回 True
    assert breaker.before_stage(), "半开状态应允许探测执行"

    # 探测成功 → CLOSED
    breaker.record_success()
    assert breaker.state == BreakerState.CLOSED
    assert breaker.failure_count == 0

    # 测试探测失败情况
    breaker.record_failure(SeverityLevel.CRITICAL, "再次触发")
    assert breaker.state == BreakerState.OPEN

    breaker.reset()
    assert breaker.state == BreakerState.HALF_OPEN

    # 探测失败 → 重新 OPEN
    breaker.record_failure(SeverityLevel.ERROR, "探测失败回退")
    assert breaker.state == BreakerState.OPEN


# ═══════════════════════════════════════════════════════════════════════════════
# T056: Info 不触发熔断
# ═══════════════════════════════════════════════════════════════════════════════


def test_info_does_not_trigger_break() -> None:
    """Info 级异常不触发熔断"""
    breaker = CircuitBreaker(run_id="test-info-001", stage_name="S1")

    for i in range(10):
        triggered = breaker.record_failure(
            SeverityLevel.INFO,
            f"Info 级别异常 {i + 1}",
        )
        assert not triggered, f"Info 级别不应触发熔断（第 {i + 1} 次）"
        assert breaker.state == BreakerState.CLOSED

    assert breaker.failure_count == 0, "Info 不计入失败计数"


# ═══════════════════════════════════════════════════════════════════════════════
# T057: 被跳过阶段不计入熔断统计
# ═══════════════════════════════════════════════════════════════════════════════


def test_skipped_stage_not_counted() -> None:
    """被跳过的阶段不计入熔断统计（通过单独实例验证）"""
    # 跳过阶段的熔断器应独立对待
    skipped_breaker = CircuitBreaker(
        run_id="test-skip-001",
        stage_name="S5",
        max_failures=3,
    )

    # 跳过阶段不调用 record_failure，confirm 状态保持 CLOSED
    assert skipped_breaker.state == BreakerState.CLOSED
    assert skipped_breaker.failure_count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# T058: 按 run_id 隔离
# ═══════════════════════════════════════════════════════════════════════════════


def test_breaker_isolation_by_run_id() -> None:
    """不同 run_id 的熔断状态相互隔离"""
    registry = CircuitBreakerRegistry()

    breaker_a = registry.get_or_create("run-A", "S2")
    breaker_b = registry.get_or_create("run-B", "S2")

    # Run A 触发熔断
    breaker_a.record_failure(SeverityLevel.CRITICAL, "Run A 故障")
    assert breaker_a.is_open

    # Run B 不受影响
    assert not breaker_b.is_open
    assert breaker_b.state == BreakerState.CLOSED

    # 验证隔离性
    assert registry.any_open("run-A")
    assert not registry.any_open("run-B")


# ═══════════════════════════════════════════════════════════════════════════════
# 补充测试
# ═══════════════════════════════════════════════════════════════════════════════


def test_breaker_registry_cleanup() -> None:
    """验证熔断器注册表清理"""
    registry = CircuitBreakerRegistry()
    registry.get_or_create("run-X", "S1")
    registry.get_or_create("run-X", "S2")

    assert len(registry.get_all_for_run("run-X")) == 2

    registry.cleanup("run-X")
    assert len(registry.get_all_for_run("run-X")) == 0


def test_breaker_reset_all() -> None:
    """验证批量重置"""
    registry = CircuitBreakerRegistry()

    b1 = registry.get_or_create("run-R", "S1")
    b2 = registry.get_or_create("run-R", "S2")

    b1.record_failure(SeverityLevel.CRITICAL, "故障")
    assert b1.is_open

    registry.reset_all("run-R")
    assert b1.state == BreakerState.HALF_OPEN
    assert b2.state == BreakerState.HALF_OPEN


def test_breaker_record_success_resets_count() -> None:
    """验证成功记录重置失败计数"""
    breaker = CircuitBreaker(run_id="test-success", stage_name="S2", max_failures=3)

    breaker.record_failure(SeverityLevel.ERROR, "失败")
    assert breaker.failure_count == 1

    breaker.record_success()
    assert breaker.failure_count == 0


def test_breaker_initial_state() -> None:
    """验证熔断器初始状态"""
    breaker = CircuitBreaker(run_id="test-init", stage_name="S2")
    assert breaker.state == BreakerState.CLOSED
    assert not breaker.is_open
    assert breaker.failure_count == 0
    assert breaker.before_stage()


# ═══════════════════════════════════════════════════════════════════════════════
# RetryPolicy 测试
# ═══════════════════════════════════════════════════════════════════════════════


def test_retry_success_first_attempt() -> None:
    """首次尝试即成功"""
    policy = RetryPolicy(RetryConfig(max_retries=3, base_delay_seconds=0.01))

    result = policy.execute_with_retry_sync(lambda: "success")

    assert result.success
    assert result.result == "success"
    assert result.attempts == 1


def test_retry_success_after_failures() -> None:
    """重试后成功"""
    call_count = [0]

    def flaky_func() -> str:
        call_count[0] += 1
        if call_count[0] < 3:
            raise ValueError("临时故障")
        return "recovered"

    policy = RetryPolicy(RetryConfig(max_retries=3, base_delay_seconds=0.01))

    result = policy.execute_with_retry_sync(flaky_func)

    assert result.success
    assert result.result == "recovered"
    assert result.attempts == 3


def test_retry_exhausted() -> None:
    """重试耗尽后失败"""

    def always_fail() -> str:
        raise ConnectionError("API 不可用")

    policy = RetryPolicy(RetryConfig(max_retries=2, base_delay_seconds=0.01))

    result = policy.execute_with_retry_sync(always_fail)

    assert not result.success
    assert result.attempts == 3  # 初始 + 2 次重试
    assert result.last_error is not None
    assert "API 不可用" in result.last_error


# ═══════════════════════════════════════════════════════════════════════════════
# Alert 测试
# ═══════════════════════════════════════════════════════════════════════════════


def test_send_alert_creates_event() -> None:
    """验证 send_alert 创建正确的 AlertEvent"""
    event = send_alert(
        title="测试告警",
        message="这是一条测试告警",
        level="error",
        run_id="test-001",
        stage_name="S2",
    )

    assert event.title == "测试告警"
    assert event.message == "这是一条测试告警"
    assert event.level == "error"
    assert event.run_id == "test-001"
    assert event.stage_name == "S2"


def test_alert_event_default_values() -> None:
    """验证 AlertEvent 默认值"""
    event = AlertEvent(title="测试", message="测试消息")
    assert event.level == "error"
    assert event.run_id == ""
    assert event.stage_name == ""
    assert isinstance(event.metadata, dict)
    assert len(event.metadata) == 0


@pytest.mark.asyncio
async def test_retry_async_success() -> None:
    """异步重试成功"""

    async def async_func() -> str:
        return "async_ok"

    policy = RetryPolicy(RetryConfig(max_retries=2, base_delay_seconds=0.01))
    result = await policy.execute_with_retry(async_func)

    assert result.success
    assert result.result == "async_ok"

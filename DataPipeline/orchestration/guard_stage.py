"""GuardStage 阶段包装器 — 为管道阶段注入护栏行为。

包装单个阶段的执行，注入以下护栏钩子：
- Pre-execution: 输入预检、熔断检查
- Post-execution: 输出校验
- 全程日志记录
"""

from __future__ import annotations

import logging
import time
from typing import Any

from DataPipeline.circuit_breaker.breaker import CircuitBreaker
from DataPipeline.monitoring.run_logger import PipelineRunLogger
from DataPipeline.validation.enums import SeverityLevel, StageStatus, ValidationPolicy
from DataPipeline.validation.results import GuardStageResult, ValidationResult
from DataPipeline.validation.schema_registry import SchemaRegistry
from DataPipeline.validation.validator import Validator
from DataPipeline.validation.violation import ValidationViolation

logger = logging.getLogger(__name__)


class GuardStage:
    """阶段护栏包装器 — 为原始阶段注入校验、熔断和日志行为。

    Attributes:
        name: 阶段名称（与原始阶段相同）
        _stage: 被包装的原始阶段实例
        _validator: 数据校验器
        _breaker: 熔断器实例（可选）
        _logger: 日志记录器（可选）
        _policy: 校验策略
    """

    def __init__(
        self,
        stage: Any,
        validator: Validator,
        breaker: CircuitBreaker | None = None,
        run_logger: PipelineRunLogger | None = None,
        policy: ValidationPolicy = ValidationPolicy.STRICT,
        short_name: str | None = None,
    ) -> None:
        """初始化阶段护栏包装器。

        Args:
            stage: 被包装的原始阶段（需有 name 属性和 execute(context) 方法）
            validator: 数据校验器
            breaker: 熔断器实例（可选）
            run_logger: 日志记录器（可选）
            policy: 校验策略（默认 STRICT）
            short_name: 阶段短名（如 "S2", 用于 Schema 注册表查询; 缺省从 name 提取）
        """
        self.name: str = getattr(stage, "name", stage.__class__.__name__)
        self._stage = stage
        self._validator = validator
        self._breaker = breaker
        self._run_logger = run_logger
        self._policy = policy
        self._short_name = short_name or self._extract_short_name(self.name)

    def execute(self, context: Any, run_id: str = "") -> GuardStageResult:
        """执行阶段并注入护栏行为。

        执行流程:
        1. 熔断检查（如 OPEN 则跳过）
        2. 阶段执行
        3. 输出校验
        4. 日志记录
        5. 返回结果

        Args:
            context: 管道上下文（PipelineContext 或 Mock）
            run_id: 运行 ID

        Returns:
            GuardStageResult: 包含执行状态和校验结果
        """
        start_time = time.perf_counter()

        # 1. 熔断检查
        if self._breaker and not self._breaker.before_stage():
            result = GuardStageResult(
                stage_name=self.name,
                status=StageStatus.CIRCUIT_BROKEN,
                skipped=False,
                duration_ms=0.0,
                severity=SeverityLevel.CRITICAL,
            )
            if self._run_logger:
                self._run_logger.log_circuit_break(
                    self.name, self._breaker.trigger_reason or "未知原因"
                )
            return result

        # 2. 阶段执行日志入口
        if self._run_logger:
            # 尝试获取输入记录数
            input_count = getattr(context, "current_input_count", None)
            self._run_logger.start_stage(self.name, input_count=input_count)

        # 3. 执行原始阶段
        stage_success = False
        stage_exception: Exception | None = None

        try:
            stage_success = self._stage.execute(context)
        except Exception as e:
            stage_exception = e
            logger.exception("阶段 %s 执行异常: %s", self.name, e)
            if self._run_logger:
                self._run_logger.log_exception(self.name, e)

        # 4. 输出校验
        validation_result = self._validate_output(context, run_id)

        # 5. 确定阶段状态
        if stage_exception:
            status = StageStatus.FAILED
            severity = SeverityLevel.ERROR
        elif not stage_success:
            status = StageStatus.FAILED
            severity = SeverityLevel.ERROR
        elif validation_result.failed > 0:
            # 校验有问题但阶段执行成功
            status = StageStatus.FAILED if validation_result.failed > 0 else StageStatus.SUCCESS
            severity = SeverityLevel.ERROR
        else:
            status = StageStatus.SUCCESS
            severity = None

        duration_ms = (time.perf_counter() - start_time) * 1000

        # 6. 记录失败到熔断器
        if self._breaker and status == StageStatus.FAILED:
            breaker_severity = SeverityLevel.CRITICAL if stage_exception else severity or SeverityLevel.ERROR
            reason = str(stage_exception) if stage_exception else f"校验失败 {validation_result.failed} 条"
            self._breaker.record_failure(breaker_severity, reason)
        elif self._breaker and status == StageStatus.SUCCESS:
            self._breaker.record_success()

        # 7. 阶段结束日志
        if self._run_logger:
            self._run_logger.end_stage(
                self.name,
                status,
                validation_result.total if status == StageStatus.SUCCESS else None,
                validation_result.passed,
                validation_result.failed,
                duration_ms,
            )
            # 记录违规详情
            for violation in validation_result.violations:
                self._run_logger.log_violation(self.name, violation)

        # 8. 构建结果
        return GuardStageResult(
            stage_name=self.name,
            status=status,
            input_count=getattr(context, "current_input_count", None),
            output_count=validation_result.total,
            validation_passed=validation_result.passed,
            validation_failed=validation_result.failed,
            violations=list(validation_result.violations),
            duration_ms=duration_ms,
            severity=severity,
            skipped=False,
        )

    def _validate_output(self, context: Any, run_id: str) -> ValidationResult:
        """执行阶段输出校验。

        从上下文获取输出数据，调用 Validator 执行 Pydantic 模式校验。
        """
        # 尝试从上下文中获取输出数据
        output_records = getattr(context, "_last_output_records", None)
        if output_records is None:
            # 尝试从 context 获取 stage output
            output_records = getattr(context, "output_records", None)

        if output_records is None:
            # 尝试调用 stage 的 get_output 方法
            if hasattr(self._stage, "get_output"):
                try:
                    output_records = self._stage.get_output()
                except Exception:
                    pass

        if output_records is None:
            logger.debug("阶段 %s: 无输出数据可校验", self.name)
            return ValidationResult(passed=0, failed=0)

        # M1: 用短名查询 Schema (注册表按 "S2" 等短名注册)
        return self._validator.validate_output(
            self._short_name, output_records, run_id=run_id
        )

    @staticmethod
    def _extract_short_name(stage_name: str) -> str:
        """从完整阶段名称提取短名称（如 "2. Process Raw Fills" → "S2"）。

        与 GuardPipeline._extract_short_name 保持一致。
        """
        parts = stage_name.split(".")
        if parts and parts[0].strip().isdigit():
            return f"S{parts[0].strip()}"
        return stage_name

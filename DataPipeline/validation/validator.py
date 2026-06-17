"""数据校验执行器。

在阶段输出写入 DB 后和输入读取 DB 前执行 Pydantic 模式校验，
捕获 ValidationError 并转换为 ValidationViolation 实例。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import ValidationError

from DataPipeline.config import Config
from DataPipeline.validation.enums import SeverityLevel, ValidationPolicy, ViolationType
from DataPipeline.validation.results import ValidationResult
from DataPipeline.validation.schema_registry import SchemaRegistry
from DataPipeline.validation.violation import ValidationViolation

logger = logging.getLogger(__name__)


class Validator:
    """数据校验执行器。

    对阶段输入/输出记录执行 Pydantic model_validate() 校验，
    根据阶段策略（STRICT/RELAXED）决定拦截行为。

    用法::

        validator = Validator(schema_registry)
        result = validator.validate_output("S2", records)
        if result.failed > 0:
            print(f"校验失败 {result.failed} 条记录")
    """

    def __init__(
        self,
        schema_registry: SchemaRegistry,
        config: Config | None = None,
    ) -> None:
        self._registry = schema_registry
        self._config = config or Config()

    def validate_output(
        self,
        stage_name: str,
        records: list[dict[str, Any]],
        run_id: str = "",
    ) -> ValidationResult:
        """阶段输出校验 — 在阶段写 DB 后、下游读 DB 前执行。

        对记录列表逐条执行 Pydantic model_validate()，捕获 ValidationError
        并转换为 ValidationViolation 实例。根据阶段策略决定拦截行为。

        Args:
            stage_name: 阶段名称（如 "S2"）
            records: 待校验的记录列表
            run_id: 运行 ID

        Returns:
            ValidationResult: 包含通过/失败记录数和违规详情
        """
        schema = self._registry.get_output_schema(stage_name)
        if schema is None:
            logger.warning("阶段 %s 未注册输出 Schema，跳过校验", stage_name)
            return ValidationResult(passed=len(records))

        policy = self._registry.get_policy(stage_name)
        bypass_on_error = self._config.GUARDRAIL_VALIDATION_BYPASS_ON_ERROR

        # 处理空数据集
        if not records:
            return self._handle_empty_dataset(stage_name, run_id, bypass_on_error)

        start_time = time.perf_counter()
        violations: list[ValidationViolation] = []
        passed_count = 0

        for idx, record in enumerate(records):
            try:
                schema.model_validate(record)
                passed_count += 1
            except ValidationError as e:
                record_identifier = self._extract_identifier(record, idx)
                record_violations = self._convert_validation_error(
                    e, stage_name, run_id, record_identifier, policy
                )
                violations.extend(record_violations)

        duration_ms = (time.perf_counter() - start_time) * 1000
        failed_count = len(records) - passed_count

        result = ValidationResult(
            passed=passed_count,
            failed=failed_count,
            violations=violations,
            duration_ms=duration_ms,
        )

        logger.info(
            "阶段 %s 输出校验完成: %d 通过 / %d 失败 (%.1fms)",
            stage_name,
            passed_count,
            failed_count,
            duration_ms,
        )

        # 降级模式：仅记录日志，数据仍然放行
        if bypass_on_error and failed_count > 0:
            logger.warning(
                "阶段 %s: 降级模式启用，%d 条违规记录被放行入库",
                stage_name,
                failed_count,
            )
            # 降级模式下重置为全部通过
            return ValidationResult(
                passed=len(records),
                failed=0,
                violations=violations,
                duration_ms=duration_ms,
            )

        return result

    def validate_input(
        self,
        stage_name: str,
        records: list[dict[str, Any]],
        run_id: str = "",
    ) -> ValidationResult:
        """阶段输入预检 — 在下游阶段读 DB 后、处理前执行。

        确认数据格式和必填字段符合预期。

        Args:
            stage_name: 当前阶段名称
            records: 从 DB 读取的输入记录列表
            run_id: 运行 ID

        Returns:
            ValidationResult: 包含预检结果
        """
        schema = self._registry.get_input_schema(stage_name)
        if schema is None:
            logger.debug("阶段 %s 未注册输入 Schema，跳过输入预检", stage_name)
            return ValidationResult(passed=len(records))

        if not records:
            logger.debug("阶段 %s 输入为空，跳过输入预检", stage_name)
            return ValidationResult(passed=0)

        start_time = time.perf_counter()
        violations: list[ValidationViolation] = []
        passed_count = 0

        for idx, record in enumerate(records):
            try:
                schema.model_validate(record)
                passed_count += 1
            except ValidationError as e:
                record_identifier = self._extract_identifier(record, idx)
                # 输入预检使用严格模式（不根据策略降级）
                record_violations = self._convert_validation_error(
                    e, stage_name, run_id, record_identifier, ValidationPolicy.STRICT
                )
                violations.extend(record_violations)

        duration_ms = (time.perf_counter() - start_time) * 1000
        failed_count = len(records) - passed_count

        return ValidationResult(
            passed=passed_count,
            failed=failed_count,
            violations=violations,
            duration_ms=duration_ms,
        )

    # ── 私有辅助方法 ──

    def _handle_empty_dataset(
        self, stage_name: str, run_id: str, bypass_on_error: bool
    ) -> ValidationResult:
        """处理空数据集情况，根据 GUARDRAIL_EMPTY_DATASET_POLICY 决定是否通过"""
        policy = self._config.GUARDRAIL_EMPTY_DATASET_POLICY
        if policy == "accept" or bypass_on_error:
            logger.info("阶段 %s: 空数据集被接受（策略=%s）", stage_name, policy)
            return ValidationResult(passed=0)
        else:
            violation = ValidationViolation(
                run_id=run_id,
                stage_name=stage_name,
                field_name="__dataset__",
                expected_constraint="非空数据集",
                actual_value="空列表",
                severity=SeverityLevel.ERROR,
                violation_type=ViolationType.CUSTOM_CONSTRAINT,
                record_identifier=None,
            )
            logger.warning("阶段 %s: 空数据集被拒绝", stage_name)
            return ValidationResult(
                passed=0,
                failed=1,
                violations=[violation],
                duration_ms=0.0,
            )

    def _convert_validation_error(
        self,
        error: ValidationError,
        stage_name: str,
        run_id: str,
        record_identifier: str | None,
        policy: ValidationPolicy,
    ) -> list[ValidationViolation]:
        """将 Pydantic ValidationError 转换为 ValidationViolation 列表。

        根据策略过滤违规等级：
        - STRICT: 所有违规记录
        - RELAXED: 仅类型不匹配违规
        """
        violations: list[ValidationViolation] = []

        for err in error.errors():
            field_name = str(err.get("loc", [""])[0]) if err.get("loc") else "unknown"
            error_type = err.get("type", "")
            error_msg = err.get("msg", "")

            # 映射到 ViolationType
            violation_type = self._map_error_to_violation_type(error_type)

            # RELAXED 策略仅拦截类型不匹配
            if policy == ValidationPolicy.RELAXED and violation_type != ViolationType.TYPE_MISMATCH:
                logger.debug(
                    "阶段 %s (RELAXED): 跳过非类型违规 %s (%s)",
                    stage_name,
                    field_name,
                    violation_type.value,
                )
                continue

            # 映射到 SeverityLevel
            severity = self._map_violation_to_severity(violation_type, policy)

            violations.append(
                ValidationViolation(
                    run_id=run_id,
                    stage_name=stage_name,
                    field_name=field_name,
                    expected_constraint=error_msg,
                    actual_value=err.get("input", "N/A"),
                    severity=severity,
                    violation_type=violation_type,
                    record_identifier=record_identifier,
                )
            )

        return violations

    @staticmethod
    def _map_error_to_violation_type(error_type: str) -> ViolationType:
        """将 Pydantic 错误类型映射到 ViolationType"""
        type_mapping: dict[str, ViolationType] = {
            "missing": ViolationType.MISSING_REQUIRED,
            "missing_field": ViolationType.MISSING_REQUIRED,
            "type_error": ViolationType.TYPE_MISMATCH,
            "string_type": ViolationType.TYPE_MISMATCH,
            "int_type": ViolationType.TYPE_MISMATCH,
            "float_type": ViolationType.TYPE_MISMATCH,
            "bool_type": ViolationType.TYPE_MISMATCH,
            "less_than": ViolationType.RANGE_VIOLATION,
            "greater_than": ViolationType.RANGE_VIOLATION,
            "less_than_equal": ViolationType.RANGE_VIOLATION,
            "greater_than_equal": ViolationType.RANGE_VIOLATION,
            "multiple_of": ViolationType.RANGE_VIOLATION,
            "enum": ViolationType.ENUM_VIOLATION,
            "string_too_short": ViolationType.RANGE_VIOLATION,
            "value_error": ViolationType.CUSTOM_CONSTRAINT,
        }
        return type_mapping.get(error_type, ViolationType.CUSTOM_CONSTRAINT)

    @staticmethod
    def _map_violation_to_severity(
        violation_type: ViolationType, policy: ValidationPolicy
    ) -> SeverityLevel:
        """根据违规类型和策略映射严重等级"""
        if violation_type == ViolationType.MISSING_REQUIRED and policy == ValidationPolicy.RELAXED:
            return SeverityLevel.INFO
        if violation_type == ViolationType.RANGE_VIOLATION:
            return SeverityLevel.ERROR
        return SeverityLevel.ERROR

    @staticmethod
    def _extract_identifier(record: dict[str, Any], index: int) -> str | None:
        """从记录中提取标识符（优先 FillId，其次行号）"""
        if "FillId" in record:
            return f"FillId={record['FillId']}"
        if "OrderId" in record:
            return f"OrderId={record['OrderId']}"
        return f"RowIndex={index}"

"""核心结果类型定义。

包含 ValidationResult、GuardStageResult、GuardRunResult 三个结果数据类，
对应 contracts/guard-pipeline-api.md 中 StageExecution Result 章节。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from DataPipeline.validation.enums import RunStatus, SeverityLevel, StageStatus
from DataPipeline.validation.violation import ValidationViolation


@dataclass
class ValidationResult:
    """单次校验执行的结果。

    Attributes:
        passed: 通过校验的记录数
        failed: 未通过校验的记录数
        violations: 违规详情列表
        duration_ms: 校验耗时（毫秒）
    """

    passed: int = 0
    failed: int = 0
    violations: list[ValidationViolation] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def failure_rate(self) -> float:
        """校验失败率（0.0 ~ 1.0）"""
        total = self.passed + self.failed
        return self.failed / total if total > 0 else 0.0

    @property
    def total(self) -> int:
        """参与校验的记录总数"""
        return self.passed + self.failed


@dataclass
class GuardStageResult:
    """单个阶段的护栏执行结果。

    Attributes:
        stage_name: 阶段名称（如 "S2"）
        status: 阶段执行状态
        input_count: 输入记录数
        output_count: 输出记录数
        validation_passed: 校验通过记录数
        validation_failed: 校验失败记录数
        violations: 违规详情列表
        duration_ms: 阶段执行耗时（毫秒）
        severity: 异常严重等级（仅异常时设置）
        skipped: 阶段是否被跳过
    """

    stage_name: str
    status: StageStatus
    input_count: int | None = None
    output_count: int | None = None
    validation_passed: int = 0
    validation_failed: int = 0
    violations: list[ValidationViolation] = field(default_factory=list)
    duration_ms: float = 0.0
    severity: SeverityLevel | None = None
    skipped: bool = False


@dataclass
class GuardRunResult:
    """管道护栏执行结果。

    Attributes:
        run_id: 运行唯一标识
        status: 管道运行状态
        started_at: 管道开始执行时间
        ended_at: 管道结束执行时间
        stages: 各阶段护栏执行结果列表
        summary: 执行概要（total_stages/completed/failed/skipped/duration_ms）
        log_path: 日志文件路径
    """

    run_id: str
    status: RunStatus
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    stages: list[GuardStageResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    log_path: str | None = None

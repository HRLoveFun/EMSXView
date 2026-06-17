"""阶段级日志辅助模块。

封装阶段级日志条目的构建和写入逻辑。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from DataPipeline.validation.enums import StageStatus
from DataPipeline.validation.violation import ValidationViolation


class StageLogger:
    """阶段级日志条目构建器。

    负责构建 STAGE_START、STAGE_END、VIOLATION 等日志条目字典，
    由 PipelineRunLogger 在阶段边界调用并写入日志文件。
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    def build_stage_start(
        self,
        stage_name: str,
        input_count: int | None = None,
    ) -> dict[str, Any]:
        """构建 STAGE_START 日志条目"""
        return {
            "run_id": self.run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": "STAGE_START",
            "stage": stage_name,
            "input_count": input_count,
        }

    def build_stage_end(
        self,
        stage_name: str,
        status: StageStatus,
        output_count: int | None,
        passed: int,
        failed: int,
        duration_ms: float,
    ) -> dict[str, Any]:
        """构建 STAGE_END 日志条目"""
        return {
            "run_id": self.run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": "STAGE_END",
            "stage": stage_name,
            "status": status.value,
            "output_count": output_count,
            "passed": passed,
            "failed": failed,
            "duration_ms": round(duration_ms, 2),
        }

    def build_violation(
        self,
        stage_name: str,
        violation: ValidationViolation,
    ) -> dict[str, Any]:
        """构建 VIOLATION 日志条目"""
        return {
            "run_id": self.run_id,
            "ts": violation.violated_at.isoformat(),
            "level": "VIOLATION",
            "stage": stage_name,
            "field": violation.field_name,
            "type": violation.violation_type.value,
            "expected": violation.expected_constraint,
            "actual": str(violation.actual_value),
            "record": violation.record_identifier or "N/A",
            "severity": violation.severity.value,
        }

    def build_exception(
        self,
        stage_name: str,
        exc: Exception,
    ) -> dict[str, Any]:
        """构建异常日志条目"""
        return {
            "run_id": self.run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": "EXCEPTION",
            "stage": stage_name,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }

    def build_circuit_break(
        self,
        stage_name: str,
        reason: str,
    ) -> dict[str, Any]:
        """构建 CIRCUIT_BREAK 日志条目"""
        return {
            "run_id": self.run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": "CIRCUIT_BREAK",
            "stage": stage_name,
            "reason": reason,
            "state": "OPEN",
        }

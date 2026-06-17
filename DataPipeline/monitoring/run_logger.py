"""管道运行级结构化日志记录器。

为每次管道执行提供完整的 JSONL 格式日志记录，
包含 RUN_START、各阶段 STAGE_START/STAGE_END、违规记录和 RUN_END 条目。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from DataPipeline.config import Config
from DataPipeline.monitoring.stage_logger import StageLogger
from DataPipeline.validation.enums import StageStatus
from DataPipeline.validation.results import GuardRunResult
from DataPipeline.validation.violation import ValidationViolation

logger = logging.getLogger(__name__)


class PipelineRunLogger:
    """管道运行级结构化日志记录器。

    维护内存缓冲区中的日志条目列表，在 flush() 时批量写入 JSONL 文件。
    日志文件路径: {log_dir}/{run_id}.jsonl

    用法::

        log = PipelineRunLogger("20260616-001", Path("./logs"))
        log.start_run("2026-06-15", ["S1", "S2", "S3"])
        log.start_stage("S1", input_count=100)
        log.end_stage("S1", StageStatus.SUCCESS, 100, 100, 0, 2100.0)
        log.finish_run(result)
        log.flush()
    """

    def __init__(
        self,
        run_id: str,
        log_dir: Path | None = None,
    ) -> None:
        """初始化日志记录器。

        Args:
            run_id: 管道运行唯一标识
            log_dir: 日志目录（不提供则使用 Config.GUARDRAIL_LOG_DIR）
        """
        self.run_id = run_id
        self._log_dir = log_dir or Config.GUARDRAIL_LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._entries: list[dict[str, Any]] = []
        self._stage_logger = StageLogger(run_id)

    @property
    def log_path(self) -> Path:
        """获取日志文件路径"""
        return self._log_dir / f"{self.run_id}.jsonl"

    def start_run(self, target_date: str, stages: list[str]) -> None:
        """记录 RUN_START 条目。

        Args:
            target_date: 目标数据日期（YYYY-MM-DD）
            stages: 计划执行的阶段名称列表
        """
        entry = {
            "run_id": self.run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": "RUN_START",
            "target_date": target_date,
            "stages": stages,
        }
        self._entries.append(entry)
        logger.info("管道运行开始: run_id=%s, 日期=%s, 阶段=%s", self.run_id, target_date, ",".join(stages))

    def start_stage(self, stage_name: str, input_count: int | None = None) -> None:
        """记录 STAGE_START 条目。

        Args:
            stage_name: 阶段名称
            input_count: 输入记录数（S1 外部摄入时为 None）
        """
        entry = self._stage_logger.build_stage_start(stage_name, input_count)
        self._entries.append(entry)

    def end_stage(
        self,
        stage_name: str,
        status: StageStatus,
        output_count: int | None,
        passed: int,
        failed: int,
        duration_ms: float,
    ) -> None:
        """记录 STAGE_END 条目。

        Args:
            stage_name: 阶段名称
            status: 阶段执行状态
            output_count: 输出记录数
            passed: 校验通过数
            failed: 校验失败数
            duration_ms: 阶段耗时（毫秒）
        """
        entry = self._stage_logger.build_stage_end(
            stage_name, status, output_count, passed, failed, duration_ms
        )
        self._entries.append(entry)

    def log_violation(self, stage_name: str, violation: ValidationViolation) -> None:
        """记录 VIOLATION 条目。

        Args:
            stage_name: 发生违规的阶段名称
            violation: 违规记录实例
        """
        entry = self._stage_logger.build_violation(stage_name, violation)
        self._entries.append(entry)

    def log_exception(self, stage_name: str, exc: Exception) -> None:
        """记录 EXCEPTION 条目。

        Args:
            stage_name: 发生异常的阶段名称
            exc: 异常实例
        """
        entry = self._stage_logger.build_exception(stage_name, exc)
        self._entries.append(entry)
        logger.exception("阶段 %s 异常: %s", stage_name, exc)

    def log_circuit_break(self, stage_name: str, reason: str) -> None:
        """记录 CIRCUIT_BREAK 条目。

        Args:
            stage_name: 触发熔断的阶段名称
            reason: 熔断原因
        """
        entry = self._stage_logger.build_circuit_break(stage_name, reason)
        self._entries.append(entry)
        logger.error("管道熔断: stage=%s, reason=%s", stage_name, reason)

    def finish_run(self, result: GuardRunResult) -> None:
        """记录 RUN_END 条目。

        汇总整条管道的执行状态和数据流转统计。

        Args:
            result: 管道护栏执行结果
        """
        summary = result.summary
        entry = {
            "run_id": self.run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": "RUN_END",
            "status": result.status.value,
            "total_stages": summary.get("total_stages", 0),
            "completed": summary.get("completed", 0),
            "failed": summary.get("failed", 0),
            "skipped": summary.get("skipped", 0),
            "duration_ms": round(summary.get("total_duration_ms", 0), 2),
        }
        self._entries.append(entry)

    def flush(self) -> None:
        """将内存中的日志批量写入文件。

        以 JSONL 格式（每行一条 JSON 记录）写入日志文件。
        """
        if not self._entries:
            return

        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                for entry in self._entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.info("日志已写入: %s (%d 条记录)", self.log_path, len(self._entries))
        except OSError as e:
            logger.error("日志写入失败: %s", e)

    def get_entries(self) -> list[dict[str, Any]]:
        """获取当前内存中的日志条目列表（仅供测试使用）"""
        return list(self._entries)

"""管道执行概要生成器。

汇总整条管道的执行状态和数据流转统计，支持格式化文本输出。
"""

from __future__ import annotations

from typing import Any

from DataPipeline.validation.enums import RunStatus, StageStatus
from DataPipeline.validation.results import GuardRunResult, GuardStageResult


def generate_summary(
    run_id: str,
    status: RunStatus,
    stages: list[GuardStageResult],
    total_duration_ms: float,
) -> dict[str, Any]:
    """生成管道执行概要数据。

    Args:
        run_id: 运行 ID
        status: 管道运行状态
        stages: 各阶段执行结果列表
        total_duration_ms: 总执行耗时（毫秒）

    Returns:
        包含统计信息的概要字典
    """
    completed = sum(1 for s in stages if s.status == StageStatus.SUCCESS)
    failed = sum(1 for s in stages if s.status == StageStatus.FAILED)
    skipped = sum(1 for s in stages if s.status == StageStatus.SKIPPED or s.skipped)
    circuit_broken = sum(1 for s in stages if s.status == StageStatus.CIRCUIT_BROKEN)

    total_violations = sum(len(s.violations) for s in stages)

    return {
        "run_id": run_id,
        "status": status.value,
        "total_stages": len(stages),
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "circuit_broken": circuit_broken,
        "total_duration_ms": round(total_duration_ms, 2),
        "total_violations": total_violations,
    }


def format_summary_text(result: GuardRunResult) -> str:
    """格式化管道执行概要为可读文本。

    Args:
        result: 管道护栏执行结果

    Returns:
        格式化的概要文本
    """
    summary = result.summary
    lines = [
        "=" * 60,
        f"管道执行概要: {result.run_id}",
        "=" * 60,
        f"状态: {summary.get('status', 'N/A')}",
        f"阶段总数: {summary.get('total_stages', 0)}",
        f"成功: {summary.get('completed', 0)}",
        f"失败: {summary.get('failed', 0)}",
        f"跳过: {summary.get('skipped', 0)}",
        f"熔断: {summary.get('circuit_broken', 0)}",
        f"总违规数: {summary.get('total_violations', 0)}",
        f"总耗时: {summary.get('total_duration_ms', 0):.0f}ms",
        "=" * 60,
    ]

    # 追加各阶段详情
    for stage in result.stages:
        violation_count = len(stage.violations)
        status_marker = {
            StageStatus.SUCCESS: "✓",
            StageStatus.FAILED: "✗",
            StageStatus.SKIPPED: "-",
            StageStatus.CIRCUIT_BROKEN: "⚠",
        }.get(stage.status, "?")

        lines.append(
            f"  {status_marker} {stage.stage_name}: "
            f"{stage.status.value} "
            f"({stage.duration_ms:.0f}ms, "
            f"通过={stage.validation_passed}, "
            f"失败={stage.validation_failed}"
            + (f", 违规={violation_count}" if violation_count > 0 else "")
            + ")"
        )

    lines.append("=" * 60)
    return "\n".join(lines)

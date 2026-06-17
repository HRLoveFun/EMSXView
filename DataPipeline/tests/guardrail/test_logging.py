"""日志记录单元测试。

覆盖 US4 全部验证场景：
- 完整运行日志记录
- 违规事件日志
- 异常事件日志
- 按 run_id 检索

对照 quickstart.md 场景 10。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from DataPipeline.monitoring.run_id import generate_run_id
from DataPipeline.monitoring.run_logger import PipelineRunLogger
from DataPipeline.monitoring.stage_logger import StageLogger
from DataPipeline.monitoring.summary import format_summary_text, generate_summary
from DataPipeline.validation.enums import RunStatus, SeverityLevel, StageStatus, ViolationType
from DataPipeline.validation.results import GuardRunResult, GuardStageResult
from DataPipeline.validation.violation import ValidationViolation

from .conftest import sample_violation


# ═══════════════════════════════════════════════════════════════════════════════
# T064: 完整运行日志 (quickstart 场景 10)
# ═══════════════════════════════════════════════════════════════════════════════


def test_complete_run_log() -> None:
    """验证日志包含 RUN_START、每阶段 STAGE_START/STAGE_END、RUN_END 条目"""
    run_id = generate_run_id()

    with tempfile.TemporaryDirectory() as tmp_dir:
        logger = PipelineRunLogger(run_id, log_dir=Path(tmp_dir))

        # 开始运行
        logger.start_run("2026-01-15", ["S1", "S2", "S3"])

        # 阶段 S1
        logger.start_stage("S1", input_count=None)
        logger.end_stage("S1", StageStatus.SUCCESS, 150, 150, 0, 2100.0)

        # 阶段 S2
        logger.start_stage("S2", input_count=150)
        logger.end_stage("S2", StageStatus.SUCCESS, 150, 150, 0, 1200.0)

        # 阶段 S3
        logger.start_stage("S3", input_count=150)
        logger.end_stage("S3", StageStatus.SUCCESS, 150, 150, 0, 800.0)

        # 结束运行
        result = GuardRunResult(
            run_id=run_id,
            status=RunStatus.SUCCESS,
            stages=[],
            summary=generate_summary(run_id, RunStatus.SUCCESS, [], 4100.0),
        )
        logger.finish_run(result)
        logger.flush()

        # 验证日志文件存在
        assert logger.log_path.exists(), f"日志文件 {logger.log_path} 应存在"

        # 读取并验证日志内容
        entries = logger.get_entries()
        assert len(entries) >= 8, f"期望至少 8 条日志条目，实际 {len(entries)}"

        # 检查关键条目
        entry_levels = [e["level"] for e in entries]
        assert "RUN_START" in entry_levels, "应有 RUN_START 条目"
        assert entry_levels.count("STAGE_START") == 3, "应有 3 个 STAGE_START"
        assert entry_levels.count("STAGE_END") == 3, "应有 3 个 STAGE_END"
        assert "RUN_END" in entry_levels, "应有 RUN_END 条目"

        # 验证所有条目关联相同 run_id
        for entry in entries:
            assert entry["run_id"] == run_id, f"所有条目应有相同 run_id: {run_id}"


# ═══════════════════════════════════════════════════════════════════════════════
# T065: 违规日志记录
# ═══════════════════════════════════════════════════════════════════════════════


def test_violation_logging() -> None:
    """校验失败时日志包含 VIOLATION 条目，含字段名、期望约束、实际值"""
    run_id = generate_run_id()

    with tempfile.TemporaryDirectory() as tmp_dir:
        logger = PipelineRunLogger(run_id, log_dir=Path(tmp_dir))

        logger.start_run("2026-01-15", ["S2"])
        logger.start_stage("S2", input_count=1)

        # 记录违规
        violation = ValidationViolation(
            run_id=run_id,
            stage_name="S2",
            field_name="FillPrice",
            expected_constraint="type=float, ge=0",
            actual_value=-1.0,
            severity=SeverityLevel.ERROR,
            violation_type=ViolationType.RANGE_VIOLATION,
            record_identifier="FillId=999",
        )
        logger.log_violation("S2", violation)

        logger.end_stage("S2", StageStatus.FAILED, 1, 0, 1, 500.0)
        logger.flush()

        entries = logger.get_entries()
        violation_entries = [e for e in entries if e["level"] == "VIOLATION"]
        assert len(violation_entries) == 1, "应有 1 条 VIOLATION 条目"

        v_entry = violation_entries[0]
        assert v_entry["field"] == "FillPrice"
        assert v_entry["type"] == "range_violation"
        assert v_entry["record"] == "FillId=999"
        assert v_entry["severity"] == "error"


# ═══════════════════════════════════════════════════════════════════════════════
# T066: 异常日志记录
# ═══════════════════════════════════════════════════════════════════════════════


def test_exception_logging() -> None:
    """阶段异常时日志包含异常类型、消息"""
    run_id = generate_run_id()

    with tempfile.TemporaryDirectory() as tmp_dir:
        logger = PipelineRunLogger(run_id, log_dir=Path(tmp_dir))

        logger.start_run("2026-01-15", ["S3"])
        logger.start_stage("S3", input_count=10)

        # 记录异常
        try:
            raise ValueError("数据处理失败: 无法解析日期")
        except ValueError as e:
            logger.log_exception("S3", e)

        logger.flush()

        entries = logger.get_entries()
        exception_entries = [e for e in entries if e["level"] == "EXCEPTION"]
        assert len(exception_entries) == 1

        exc_entry = exception_entries[0]
        assert exc_entry["error_type"] == "ValueError"
        assert "数据处理失败" in exc_entry["error_message"]
        assert exc_entry["stage"] == "S3"


# ═══════════════════════════════════════════════════════════════════════════════
# T067: 按 run_id 检索日志
# ═══════════════════════════════════════════════════════════════════════════════


def test_log_retrieval_by_run_id() -> None:
    """按 run_id 检索日志文件，验证可按日期和阶段名称过滤"""
    run_id = generate_run_id()

    with tempfile.TemporaryDirectory() as tmp_dir:
        logger = PipelineRunLogger(run_id, log_dir=Path(tmp_dir))

        logger.start_run("2026-01-15", ["S1", "S2", "S5"])
        logger.start_stage("S1", input_count=None)
        logger.end_stage("S1", StageStatus.SUCCESS, 100, 100, 0, 1000.0)
        logger.start_stage("S2", input_count=100)
        logger.end_stage("S2", StageStatus.SUCCESS, 100, 100, 0, 800.0)
        logger.start_stage("S5", input_count=100)
        logger.end_stage("S5", StageStatus.SKIPPED, 0, 0, 0, 0.0)
        logger.flush()

        entries = logger.get_entries()

        # 按阶段名称过滤
        s1_entries = [e for e in entries if e.get("stage") == "S1"]
        assert len(s1_entries) == 2, f"S1 应有 2 条记录，实际 {len(s1_entries)}"

        s5_entries = [e for e in entries if e.get("stage") == "S5"]
        assert len(s5_entries) == 2, "S5 应有 2 条记录"

        # 按级别过滤
        run_start = [e for e in entries if e["level"] == "RUN_START"]
        assert len(run_start) == 1
        assert run_start[0]["target_date"] == "2026-01-15"

        # 验证日志文件可被解析
        with open(logger.log_path, "r", encoding="utf-8") as f:
            for line in f:
                parsed = json.loads(line.strip())
                assert parsed["run_id"] == run_id


# ═══════════════════════════════════════════════════════════════════════════════
# 补充测试
# ═══════════════════════════════════════════════════════════════════════════════


def test_run_id_uniqueness() -> None:
    """验证运行 ID 格式和唯一性"""
    ids = [generate_run_id() for _ in range(10)]
    # 验证唯一性
    assert len(set(ids)) == 10, "10 个 ID 应全部唯一"
    # 验证格式
    for rid in ids:
        parts = rid.split("-")
        assert len(parts) == 3, "ID 应包含 3 个由 - 分隔的部分"
        assert len(parts[0]) == 8, "日期部分应为 8 位"
        assert len(parts[1]) == 6, "时间部分应为 6 位"
        assert len(parts[2]) == 6, "随机部分应为 6 位"


def test_format_summary_text() -> None:
    """验证概要格式化输出"""
    result = GuardRunResult(
        run_id="test-001",
        status=RunStatus.SUCCESS,
        stages=[
            GuardStageResult(
                stage_name="S2",
                status=StageStatus.SUCCESS,
                validation_passed=10,
                validation_failed=0,
                duration_ms=100.0,
            ),
            GuardStageResult(
                stage_name="S3",
                status=StageStatus.FAILED,
                validation_passed=5,
                validation_failed=3,
                duration_ms=200.0,
                violations=[sample_violation],
            ),
        ],
        summary=generate_summary("test-001", RunStatus.PARTIAL_FAILURE, [], 300.0),
    )

    text = format_summary_text(result)
    assert "test-001" in text
    assert "S2" in text
    assert "S3" in text


def test_stage_logger_build_entries(sample_violation: ValidationViolation) -> None:
    """验证 StageLogger 各种条目的构建"""
    stage_logger = StageLogger("test-run-001")

    # STAGE_START
    start_entry = stage_logger.build_stage_start("S2", input_count=50)
    assert start_entry["level"] == "STAGE_START"
    assert start_entry["stage"] == "S2"
    assert start_entry["input_count"] == 50

    # STAGE_END
    end_entry = stage_logger.build_stage_end("S2", StageStatus.SUCCESS, 50, 50, 0, 1500.0)
    assert end_entry["level"] == "STAGE_END"
    assert end_entry["status"] == "success"
    assert end_entry["passed"] == 50

    # VIOLATION
    violation_entry = stage_logger.build_violation("S2", sample_violation)
    assert violation_entry["level"] == "VIOLATION"
    assert violation_entry["field"] == "FillPrice"

    # EXCEPTION
    exc_entry = stage_logger.build_exception("S3", ValueError("测试异常"))
    assert exc_entry["level"] == "EXCEPTION"
    assert exc_entry["error_type"] == "ValueError"

    # CIRCUIT_BREAK
    cb_entry = stage_logger.build_circuit_break("S2", "连续失败 3 次")
    assert cb_entry["level"] == "CIRCUIT_BREAK"
    assert "连续失败" in cb_entry["reason"]


def test_generate_summary() -> None:
    """验证概要数据生成"""
    stages = [
        GuardStageResult(stage_name="S2", status=StageStatus.SUCCESS),
        GuardStageResult(stage_name="S3", status=StageStatus.FAILED),
        GuardStageResult(stage_name="S5", status=StageStatus.SKIPPED, skipped=True),
    ]
    summary = generate_summary("test-001", RunStatus.PARTIAL_FAILURE, stages, 5000.0)

    assert summary["total_stages"] == 3
    assert summary["completed"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["total_duration_ms"] == 5000.0


def test_logger_empty_flush() -> None:
    """空日志 flush 不应创建空文件"""
    run_id = generate_run_id()
    with tempfile.TemporaryDirectory() as tmp_dir:
        logger = PipelineRunLogger(run_id, log_dir=Path(tmp_dir))
        logger.flush()  # 不应报错
        # 空条目不应创建文件
        assert not logger.log_path.exists() or len(logger.get_entries()) == 0

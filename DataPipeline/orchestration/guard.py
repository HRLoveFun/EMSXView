"""GuardPipeline 编排器 — 包装 FinancialPipeline，注入护栏机制。

提供带护栏保护的管道执行能力：生成运行 ID、创建独立熔断器注册表、
顺序执行阶段并注入校验/熔断/日志钩子、输出执行概要。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from DataPipeline.circuit_breaker.alert import alert_callback, send_alert
from DataPipeline.circuit_breaker.breaker import CircuitBreaker
from DataPipeline.circuit_breaker.breaker_registry import CircuitBreakerRegistry
from DataPipeline.config import Config
from DataPipeline.monitoring.run_id import generate_run_id
from DataPipeline.monitoring.run_logger import PipelineRunLogger
from DataPipeline.monitoring.summary import generate_summary
from DataPipeline.orchestration.guard_stage import GuardStage
from DataPipeline.pipeline_guards.schema_drift_guard import run_schema_drift_check
from DataPipeline.validation.enums import RunStatus, SeverityLevel, StageStatus, ValidationPolicy
from DataPipeline.validation.results import GuardRunResult, GuardStageResult
from DataPipeline.validation.schema_registry import SchemaRegistry
from DataPipeline.validation.validator import Validator

logger = logging.getLogger(__name__)


class GuardPipeline:
    """FinancialPipeline 的包装器，提供带护栏保护的管道执行能力。

    作为独立编排层包装现有 FinancialPipeline，对 PipelineContext 和各 Stage
    类保持零侵入。所有新增功能通过包装模式注入。

    用法::

        pipeline = PipelineFactory.create_daily_e2e_pipeline()
        schemas = SchemaRegistry()
        # 注册各阶段 Schema...

        guard = GuardPipeline(pipeline, schemas=schemas)
        result = guard.run(context)
    """

    def __init__(
        self,
        pipeline: Any,
        *,
        schemas: SchemaRegistry,
        breaker_registry: CircuitBreakerRegistry | None = None,
        run_logger: PipelineRunLogger | None = None,
        config: Config | None = None,
    ) -> None:
        """初始化 GuardPipeline。

        Args:
            pipeline: 被包装的 FinancialPipeline 实例（需有 stages 属性和 run 方法）
            schemas: 阶段输入/输出模式注册表
            breaker_registry: 熔断器注册表（不提供则自动创建）
            run_logger: 日志记录器（不提供则在 run() 时创建）
            config: 配置实例（不提供则使用全局 Config）
        """
        self._pipeline = pipeline
        self._schemas = schemas
        self._breaker_registry = breaker_registry or CircuitBreakerRegistry()
        self._run_logger = run_logger
        self._config = config or Config()
        self._validator = Validator(schemas, config=self._config)

    def run(self, context: Any) -> GuardRunResult:
        """执行带护栏保护的管道。

        执行流程:
        1. 生成唯一 run_id
        2. 创建独立的熔断器注册表
        3. 记录 RUN_START 日志
        4. 顺序执行每个阶段（注入校验/熔断/日志钩子）
        5. 生成执行概要
        6. 记录 RUN_END 日志
        7. 返回 GuardRunResult

        Args:
            context: 管道上下文（PipelineContext 或其子类）

        Returns:
            GuardRunResult: 包含管道执行结果和护栏报告
        """
        started_at = time.time()

        # 1. 生成运行 ID
        run_id = generate_run_id()
        logger.info("管道护栏运行开始: run_id=%s", run_id)

        # 2. 创建日志记录器（如未提供）
        if self._run_logger is None:
            self._run_logger = PipelineRunLogger(run_id)

        # 3. 获取原始管道阶段列表
        stages = getattr(self._pipeline, "stages", [])
        if not stages:
            stages = getattr(self._pipeline, "_stages", [])

        stage_names = [getattr(s, "name", s.__class__.__name__) for s in stages]

        # 4. 记录 RUN_START
        # target_dates 可能为空列表（无增量日期，如 fill fetch 失败后重跑），
        # 直接 [0] 会抛 IndexError 导致 GuardPipeline 崩溃回退原生管道
        target_dates = getattr(context, "target_dates", [])
        target_date = target_dates[0] if target_dates else ""
        self._run_logger.start_run(
            target_date=target_date,
            stages=stage_names,
        )

        # 4.5 PR-3: Schema drift pre-flight 静态检查
        # 在执行任何阶段前扫描 DDL 与代码层写入路径的不一致
        # 仅检查 + 告警，不自动修复；白名单中的已知漂移降级为 INFO
        drift_result, drift_violations = run_schema_drift_check(
            run_id=run_id, stage_name="S0_PreFlight",
        )
        for v in drift_violations:
            self._run_logger.log_violation("S0_PreFlight", v)

        # 统计 ERROR 级别漂移（新发现的、非白名单的）
        error_drifts = [v for v in drift_violations if v.severity == SeverityLevel.ERROR]
        if error_drifts:
            logger.error(
                "Schema drift 检测到 %d 条未白名单漂移（ERROR 级别），阻断管道执行:",
                len(error_drifts),
            )
            for v in error_drifts:
                logger.error("  - %s: %s", v.field_name, v.expected_constraint)
            send_alert(
                title="Schema drift detected",
                message=f"Pipeline 启动阻断：检测到 {len(error_drifts)} 条 schema 漂移（ERROR 级别）",
                level="critical",
                run_id=run_id,
                stage_name="S0_PreFlight",
            )
            # 阻断：返回 CIRCUIT_BROKEN 结果，不执行任何阶段
            broken_result = GuardStageResult(
                stage_name="S0_PreFlight",
                status=StageStatus.CIRCUIT_BROKEN,
                severity=SeverityLevel.CRITICAL,
                violations=list(drift_violations),
            )
            result = GuardRunResult(
                run_id=run_id,
                status=RunStatus.CIRCUIT_BROKEN,
                stages=[broken_result],
                summary={"reason": "schema_drift", "drift_count": len(error_drifts)},
                log_path=str(self._run_logger.log_path),
            )
            self._run_logger.finish_run(result)
            self._run_logger.flush()
            return result

        if drift_result.has_drift:
            logger.warning(
                "Schema drift 检测到 %d 条已知漂移（白名单降级为 INFO）",
                len(drift_violations),
            )

        # 5. 执行各阶段
        stage_results: list[GuardStageResult] = []
        pipeline_success = True
        circuit_broken = False

        # 检查跳过配置
        skip_config = getattr(context, "config", {}).get("skip", {}) if hasattr(context, "config") else {}
        known_skip_stages = {
            "S1": skip_config.get("skip_ingest", False),
            "S5": skip_config.get("skip_bdib", False),
        }

        for i, stage in enumerate(stages):
            stage_name = stage_names[i] if i < len(stage_names) else f"Stage-{i}"

            # 提取短名称用于策略查找
            short_name = self._extract_short_name(stage_name)

            # 检查阶段是否被配置跳过
            is_skipped = False
            for key, skipped in known_skip_stages.items():
                if key in stage_name:
                    is_skipped = skipped
                    break

            if is_skipped:
                # 被跳过的阶段完全排除在护栏之外
                skipped_result = GuardStageResult(
                    stage_name=stage_name,
                    status=StageStatus.SKIPPED,
                    skipped=True,
                )
                stage_results.append(skipped_result)
                logger.info("阶段 %s 被配置跳过，不执行护栏校验", stage_name)
                continue

            # 获取或创建熔断器
            breaker = self._breaker_registry.get_or_create(run_id, short_name)

            # 检查熔断状态
            if breaker.is_open:
                logger.warning("阶段 %s 被熔断阻断", stage_name)
                broken_result = GuardStageResult(
                    stage_name=stage_name,
                    status=StageStatus.CIRCUIT_BROKEN,
                    severity=SeverityLevel.CRITICAL,
                )
                stage_results.append(broken_result)
                self._run_logger.log_circuit_break(stage_name, breaker.trigger_reason or "熔断阻断")
                circuit_broken = True
                break

            # 获取阶段策略
            policy = self._schemas.get_policy(short_name)

            # 创建 GuardStage 包装器并执行
            guard_stage = GuardStage(
                stage=stage,
                validator=self._validator,
                breaker=breaker,
                run_logger=self._run_logger,
                policy=policy,
                short_name=short_name,
            )

            # 将输出记录数注入上下文（供 GuardStage 校验使用）
            if hasattr(stage, "get_output"):
                try:
                    context.output_records = stage.get_output()  # type: ignore[attr-defined]
                except Exception:
                    pass

            stage_result = guard_stage.execute(context, run_id=run_id)
            stage_results.append(stage_result)

            # 处理失败
            if stage_result.status == StageStatus.FAILED:
                pipeline_success = False

                # S1 宽松策略：校验失败触发告警但不阻断
                if policy == ValidationPolicy.RELAXED:
                    logger.warning(
                        "阶段 %s (RELAXED): 校验失败 %d 条，数据放行继续",
                        stage_name,
                        stage_result.validation_failed,
                    )
                    continue

                # S2-S10: 按等级处理
                if stage_result.severity == SeverityLevel.CRITICAL:
                    circuit_broken = True
                    send_alert(
                        title=f"管道熔断: {stage_name}",
                        message=f"阶段 {stage_name} Critical 异常: {len(stage_result.violations)} 条违规",
                        level="critical",
                        run_id=run_id,
                        stage_name=stage_name,
                    )
                    break
            elif stage_result.status == StageStatus.CIRCUIT_BROKEN:
                circuit_broken = True
                break

        # 6. 确定最终状态
        if circuit_broken:
            final_status = RunStatus.CIRCUIT_BROKEN
        elif pipeline_success:
            final_status = RunStatus.SUCCESS
        else:
            final_status = RunStatus.PARTIAL_FAILURE

        total_duration_ms = (time.time() - started_at) * 1000

        # 7. 生成概要
        summary = generate_summary(run_id, final_status, stage_results, total_duration_ms)

        # 8. 创建结果
        result = GuardRunResult(
            run_id=run_id,
            status=final_status,
            stages=stage_results,
            summary=summary,
            log_path=str(self._run_logger.log_path),
        )

        # 9. 记录 RUN_END
        self._run_logger.finish_run(result)
        self._run_logger.flush()

        # 10. 清理熔断器注册表
        self._breaker_registry.cleanup(run_id)

        logger.info(
            "管道护栏运行完成: run_id=%s, status=%s, stages=%d, duration=%.0fms",
            run_id,
            final_status.value,
            len(stage_results),
            total_duration_ms,
        )

        return result

    @staticmethod
    def _extract_short_name(stage_name: str) -> str:
        """从完整阶段名称提取短名称（如 "2. Process Raw Fills" → "S2"）"""
        # 匹配 "2. Process Raw Fills" 格式
        parts = stage_name.split(".")
        if parts and parts[0].strip().isdigit():
            return f"S{parts[0].strip()}"
        # 回退：直接返回原名
        return stage_name

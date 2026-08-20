"""
Pipeline orchestrator and factory — assemble and run stage sequences.
"""

from __future__ import annotations

import logging
import warnings

import pandas as pd
from typing import List

from .base import BaseStage
from .context import PipelineContext
from .stages_ingest import (
    IngestExcelStage, ProcessRawFillsStage,
    AggregateFillsStage, GenerateOrderLabelsStage,
)
from .stages_process import (
    IntegrateBDIBStage, WriteManifestStage, CalculateDailyMetricsStage, ComputeRouteMetricsStage,
)
from .stages_analysis import (
    RegimeDailyFeaturesStage, RegimeFillTaggerStage, AttributionMetricsStage,
)
from DataPipeline.config import Config

logger = logging.getLogger(__name__)


class FinancialPipeline:
    """Orchestrator that manages and executes stage sequences in order."""

    def __init__(self, name: str = "Default-Comprehensive"):
        self.name = name
        self._stages: List[BaseStage] = []

    def add_stage(self, stage: BaseStage) -> 'FinancialPipeline':
        """Add a processing stage, supports chaining."""
        self._stages.append(stage)
        return self

    def run(self, context: PipelineContext) -> PipelineContext:
        """Execute all stages sequentially."""
        logger.info("=" * 60)
        logger.info(f"EMSX Pipeline Execution: [{self.name}]")
        logger.info("=" * 60)

        Config.initialize_directories()

        marker_name = str(context.config.get("stage_marker_name", "")).strip()
        marker_start = int(context.config.get("stage_marker_start", 0))
        marker_end = int(context.config.get("stage_marker_end", 100))
        total_stages = max(1, len(self._stages))

        for index, stage in enumerate(self._stages):
            if marker_name:
                stage_progress = marker_start + int(
                    max(0, marker_end - marker_start) * (index + 1) / total_stages
                )
                print(f"[STAGE] {marker_name} {min(100, max(0, stage_progress))}", flush=True)
            success = stage.execute(context)
            if not success:
                logger.error(f"Pipeline halted at stage: {stage.name}")
                break

        logger.info("=" * 60)
        if context.is_successful:
            # 构建可读的完成摘要
            proc = context.summary.get("processing", {})
            agg = context.summary.get("aggregation", {})
            labels = context.summary.get("order_labels", {})
            ingest = context.summary.get("ingestion", {})
            bdib = context.summary.get("bdib", {})

            parts = []
            if proc.get("rows_processed", 0) > 0:
                parts.append(f"processed {proc['rows_processed']} rows")
            if agg.get("dates", 0) > 0:
                parts.append(f"aggregated {agg['dates']} dates")
            if labels.get("orders", 0) > 0:
                parts.append(f"labeled {labels['orders']} orders")
            if bdib.get("raw_bdib_rows", 0) > 0:
                parts.append(f"BDIB {bdib['raw_bdib_rows']} bars")
            if ingest.get("skipped"):
                parts.append("ingestion skipped")
            if bdib.get("skipped"):
                parts.append("BDIB skipped")

            if parts:
                detail = "; ".join(parts)
            elif proc.get("rows_processed") == 0:
                detail = "Already up to date — no new data to process"
            else:
                detail = "Completed"

            if marker_name:
                print(f"[STAGE] completion 100 {detail}", flush=True)
            logger.info(f"Pipeline completed SUCCESSFULLY: {context.summary}")
        else:
            logger.warning(f"Pipeline completed with ERRORS: {len(context.errors)} issues found.")
        logger.info("=" * 60)

        return context


class PipelineFactory:
    """Pipeline factory — provides daily end-to-end processing pipelines."""

    @staticmethod
    def create_daily_e2e_pipeline(skip_ingest: bool = True, skip_bdib: bool = True) -> FinancialPipeline:
        """Daily end-to-end orchestration."""
        pipeline = FinancialPipeline("E2E-FullChain-DailyBatch")

        if not skip_ingest:
            logger.warning(
                "IngestExcelStage is DEPRECATED and will be removed in v2.0. "
                "Data must be ingested from Bloomberg API via fill_fetch.py, not from Excel. "
                "Consider keeping skip_ingest=True and using the active Bloomberg path."
            )
            pipeline.add_stage(IngestExcelStage())

        pipeline.add_stage(ProcessRawFillsStage())
        pipeline.add_stage(AggregateFillsStage())
        pipeline.add_stage(GenerateOrderLabelsStage())

        if not skip_bdib:
            pipeline.add_stage(IntegrateBDIBStage())
            pipeline.add_stage(ComputeRouteMetricsStage())
            pipeline.add_stage(CalculateDailyMetricsStage())


        pipeline.add_stage(WriteManifestStage())
        return pipeline


# ═══════════════════════════════════════════════════════════════════════
# Legacy backward-compatibility runner functions
# ═══════════════════════════════════════════════════════════════════════

from DataPipeline.storage.facade import DatabaseFacade

_log = logging.getLogger(__name__)


def run_ingest(excel_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Legacy compatibility: Ingest Excel files.

    .. deprecated::
        `run_ingest()` is deprecated and will be removed in v2.0.
        Data must be ingested from Bloomberg API via `fill_fetch.py`, not from Excel.
    """
    warnings.warn(
        "run_ingest() is deprecated and will be removed in v2.0. "
        "Data must be ingested from Bloomberg API via fill_fetch.py, not from Excel.",
        DeprecationWarning,
        stacklevel=2,
    )
    ctx = PipelineContext(excel_dir=excel_dir)
    pipe = FinancialPipeline("Ingest-HistoricalExcel").add_stage(IngestExcelStage())
    pipe.run(ctx)
    return ctx.summary.get("ingestion", {}).get("results", [])


def run_process(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> pd.DataFrame:
    """Legacy compatibility: Process raw fills."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipe = FinancialPipeline("Process-CoreModel").add_stage(ProcessRawFillsStage())
    pipe.run(ctx)
    return pd.DataFrame()


def run_aggregate(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> None:
    """Legacy compatibility: Aggregate fills."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipe = FinancialPipeline("Aggregate-OrderRoute").add_stage(AggregateFillsStage())
    pipe.run(ctx)


def run_order_labels(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> pd.DataFrame:
    """Legacy compatibility: Generate order labels."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipe = FinancialPipeline("Label-GlobalOrder").add_stage(GenerateOrderLabelsStage())
    pipe.run(ctx)
    return ctx.db.fills_read.get_order_labels()


def run_bdib_integration(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> None:
    """Legacy compatibility: Integrate BDIB data."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipe = FinancialPipeline("Integrate-BDIB-TCA").add_stage(IntegrateBDIBStage())
    pipe.run(ctx)


def run_full_pipeline(
    excel_dir: Optional[Path] = None,
    dates: Optional[List[str]] = None,
    force: bool = False,
    skip_bdib: bool = True,
    skip_ingest: bool = True,
    stage_marker_name: Optional[str] = None,
    stage_marker_start: int = 0,
    stage_marker_end: int = 100,
) -> Dict[str, Any]:
    ctx = PipelineContext(
        target_dates=dates or [], force=force, excel_dir=excel_dir,
        config={"stage_marker_name": stage_marker_name,
                "stage_marker_start": stage_marker_start,
                "stage_marker_end": stage_marker_end},
    )
    pipe = PipelineFactory.create_daily_e2e_pipeline(skip_ingest=skip_ingest, skip_bdib=skip_bdib)
    if skip_ingest:
        ctx.summary["ingestion"] = {"skipped": True}
    if skip_bdib:
        ctx.summary["bdib"] = {"skipped": True}

    # ── 护栏机制接入（GuardPipeline 包装）──
    if _should_use_guarded_run(ctx):
        try:
            return _run_with_guardrail(pipe, ctx)
        except Exception as guard_err:
            _log.warning("GuardPipeline 执行异常，回退到原生管道: %s", guard_err)
            pipe.run(ctx)
            return ctx.summary

    pipe.run(ctx)
    return ctx.summary


def _should_use_guarded_run(ctx: PipelineContext) -> bool:
    """判断是否应使用 GuardPipeline 包装执行。

    条件：
    1. GUARDRAIL_ENABLED 配置为 True
    2. 非 skip_ingest 流程（仅 S1 场景需要额外处理，当前 skip_ingest=True 为默认）
    """
    if not Config.GUARDRAIL_ENABLED:
        return False
    skip_config = ctx.config.get("skip", {})
    # 当所有阶段都被跳过时，不需要护栏
    if skip_config.get("skip_ingest", True) and skip_config.get("skip_bdib", True):
        return True  # 常规增量流程（S2-S4 + S6），仍然启用护栏日志和异常捕获
    return True


def _run_with_guardrail(pipe: FinancialPipeline, ctx: PipelineContext) -> Dict[str, Any]:
    """使用 GuardPipeline 包装执行管道，提供异常捕获、日志记录和熔断保护。

    与原生 FinancialPipeline.run() 的区别：
    - 捕获每个阶段的异常并记录到结构化日志中
    - 为异常提供 SeverityLevel 分级（Info/Error/Critical）
    - 生成 run_id + JSONL 运行日志
    - 阶段失败不再中断整个管道（S2-S4 失败仅跳过当前阶段）
    """
    from DataPipeline.orchestration.guard import GuardPipeline
    from DataPipeline.validation.enums import RunStatus
    from DataPipeline.validation.schema_registry import SchemaRegistry
    from DataPipeline.validation.enums import ValidationPolicy
    from DataPipeline.validation.schemas import (
        RawFillsSchema,
        ProcessedFillsSchema,
        AggregateFillsSchema,
        OrderLabelsSchema,
        FillBdibSchema,
        DailyMetricsSchema,
        RegimeSchema,
        AttributionSchema,
    )

    schemas = SchemaRegistry()
    # M1: 生产路径注册各阶段输出 Schema (此前为空注册, 输出校验臂恒跳过)。
    # 使用 RELAXED 策略 — 仅拦截类型不匹配违规, 避免历史数据值域差异误伤管道。
    schemas.register("S1", "output", RawFillsSchema, policy=ValidationPolicy.RELAXED)
    schemas.register("S2", "output", ProcessedFillsSchema, policy=ValidationPolicy.RELAXED)
    schemas.register("S3", "output", AggregateFillsSchema, policy=ValidationPolicy.RELAXED)
    schemas.register("S4", "output", OrderLabelsSchema, policy=ValidationPolicy.RELAXED)
    schemas.register("S5", "output", FillBdibSchema, policy=ValidationPolicy.RELAXED)
    schemas.register("S7", "output", DailyMetricsSchema, policy=ValidationPolicy.RELAXED)
    schemas.register("S8", "output", RegimeSchema, policy=ValidationPolicy.RELAXED)
    schemas.register("S10", "output", AttributionSchema, policy=ValidationPolicy.RELAXED)

    guard = GuardPipeline(pipe, schemas=schemas)
    result = guard.run(ctx)

    # 将护栏运行信息注入 summary 供调用方使用
    ctx.summary["_guardrail"] = {
        "run_id": result.run_id,
        "status": result.status.value,
        "log_path": result.log_path,
    }

    if result.status == RunStatus.CIRCUIT_BROKEN:
        _log.error("护栏熔断: run_id=%s, 管道已阻断", result.run_id)
        ctx.summary["_guardrail"]["circuit_broken"] = True
    elif result.status == RunStatus.PARTIAL_FAILURE:
        _log.warning("护栏运行完成（部分失败）: run_id=%s", result.run_id)
    else:
        _log.info("护栏运行完成: run_id=%s", result.run_id)

    return ctx.summary


def run_incremental(
    excel_dir: Optional[Path] = None,
    skip_bdib: bool = True,
    stage_marker_name: Optional[str] = None,
    stage_marker_start: int = 0,
    stage_marker_end: int = 100,
) -> Dict[str, Any]:
    return run_full_pipeline(
        excel_dir=excel_dir, dates=None, force=False,
        skip_bdib=skip_bdib, skip_ingest=True,
        stage_marker_name=stage_marker_name,
        stage_marker_start=stage_marker_start,
        stage_marker_end=stage_marker_end,
    )


def get_pipeline_status() -> Dict[str, Any]:
    """Get current status of the processing pipeline."""
    status: Dict[str, Any] = {}
    db = DatabaseFacade()
    try:
        status["raw_fills"] = {
            "total_rows": db.raw_fills_read.get_row_count(),
            "dates": db.raw_fills_read.get_all_source_dates(),
            "date_counts": db.raw_fills_read.get_date_row_counts(),
        }
    except Exception as e:
        status["raw_fills"] = {"error": str(e)}
    return status

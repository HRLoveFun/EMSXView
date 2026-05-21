"""
Pipeline orchestrator and factory — assemble and run stage sequences.
"""

from __future__ import annotations

import logging
from typing import List

from .base import BaseStage
from .context import PipelineContext
from .stages_ingest import (
    IngestExcelStage, ProcessRawFillsStage,
    AggregateFillsStage, GenerateOrderLabelsStage,
)
from .stages_process import (
    IntegrateBDIBStage, WriteManifestStage, CalculateDailyMetricsStage,
)
from .stages_analysis import (
    RegimeDailyFeaturesStage, RegimeFillTaggerStage, AttributionMetricsStage,
)
from DataPipeline.config import Config

logger = logging.getLogger(__name__)


class FinancialPipeline:
    """管理和按顺序执行所有处理阶段的调度器。"""

    def __init__(self, name: str = "默认-综合处理流水线"):
        self.name = name
        self._stages: List[BaseStage] = []

    def add_stage(self, stage: BaseStage) -> 'FinancialPipeline':
        """添加一个新的处理阶段，支持链式调用。"""
        self._stages.append(stage)
        return self

    def run(self, context: PipelineContext) -> PipelineContext:
        """顺序执行所有阶段。"""
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
            logger.info(f"Pipeline completed SUCCESSFULLY: {context.summary}")
        else:
            logger.warning(f"Pipeline completed with ERRORS: {len(context.errors)} issues found.")
        logger.info("=" * 60)

        return context


class PipelineFactory:
    """流水线工厂 — 提供每日端到端处理流水线。"""

    @staticmethod
    def create_daily_e2e_pipeline(skip_ingest: bool = True, skip_bdib: bool = True) -> FinancialPipeline:
        """每日端到端总控调度"""
        pipeline = FinancialPipeline("端到端全链路-日终批处理")

        if not skip_ingest:
            pipeline.add_stage(IngestExcelStage())

        pipeline.add_stage(ProcessRawFillsStage())
        pipeline.add_stage(AggregateFillsStage())
        pipeline.add_stage(GenerateOrderLabelsStage())

        if not skip_bdib:
            pipeline.add_stage(IntegrateBDIBStage())
            pipeline.add_stage(CalculateDailyMetricsStage())

        pipeline.add_stage(WriteManifestStage())
        return pipeline


# ═══════════════════════════════════════════════════════════════════════
# Legacy backward-compatibility runner functions
# ═══════════════════════════════════════════════════════════════════════

from DataPipeline.storage.facade import DatabaseFacade

_log = logging.getLogger(__name__)


def run_ingest(excel_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Legacy compatibility: Ingest Excel files."""
    ctx = PipelineContext(excel_dir=excel_dir)
    pipe = FinancialPipeline("数据同步-历史Excel流水").add_stage(IngestExcelStage())
    pipe.run(ctx)
    return ctx.summary.get("ingestion", {}).get("results", [])


def run_process(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> pd.DataFrame:
    """Legacy compatibility: Process raw fills."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipe = FinancialPipeline("数据清洗与加工-交易核心模型").add_stage(ProcessRawFillsStage())
    pipe.run(ctx)
    return pd.DataFrame()


def run_aggregate(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> None:
    """Legacy compatibility: Aggregate fills."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipe = FinancialPipeline("降频聚合-订单路由视角(单阶段)").add_stage(AggregateFillsStage())
    pipe.run(ctx)


def run_order_labels(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> pd.DataFrame:
    """Legacy compatibility: Generate order labels."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipe = FinancialPipeline("特征提取-全局订单标签(单阶段)").add_stage(GenerateOrderLabelsStage())
    pipe.run(ctx)
    return ctx.db.fills_read.get_order_labels()


def run_bdib_integration(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> None:
    """Legacy compatibility: Integrate BDIB data."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipe = FinancialPipeline("多源融合-TCA成本分析").add_stage(IntegrateBDIBStage())
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
    pipe.run(ctx)
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

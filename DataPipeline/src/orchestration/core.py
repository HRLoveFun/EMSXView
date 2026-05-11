"""
Pipeline orchestrator and factory — assemble and run stage sequences.
"""

from __future__ import annotations

import logging
from typing import List

from .base import BaseStage
from .context import PipelineContext
from .stages import (
    IngestExcelStage, ProcessRawFillsStage, AggregateFillsStage,
    GenerateOrderLabelsStage, IntegrateBDIBStage, WriteManifestStage,
    CalculateDailyMetricsStage, RegimeDailyFeaturesStage,
    RegimeFillTaggerStage, AttributionMetricsStage,
)
from DataPipeline.src.common.processing_config import ProcessingConfig as Config

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
    """流水线工厂类，使用'功能描述-业务领域'规范命名并装配流水线。"""

    @staticmethod
    def create_data_sync_legacy() -> FinancialPipeline:
        """创建【数据同步-历史Excel流水】流水线"""
        return FinancialPipeline("数据同步-历史Excel流水").add_stage(IngestExcelStage())

    @staticmethod
    def create_data_processing_trade_model() -> FinancialPipeline:
        """创建【数据清洗与加工-交易核心模型】流水线"""
        return FinancialPipeline("数据清洗与加工-交易核心模型").add_stage(ProcessRawFillsStage())

    @staticmethod
    def create_aggregation_order_route() -> FinancialPipeline:
        """创建【降频聚合与特征提取-订单路由视角】流水线"""
        return (FinancialPipeline("降频聚合与特征提取-订单路由视角")
                .add_stage(AggregateFillsStage())
                .add_stage(GenerateOrderLabelsStage()))

    @staticmethod
    def create_integration_tca_analysis() -> FinancialPipeline:
        """创建【多源融合-TCA成本分析】流水线"""
        return FinancialPipeline("多源融合-TCA成本分析").add_stage(IntegrateBDIBStage())

    @staticmethod
    def create_contract_downstream() -> FinancialPipeline:
        """创建【契约分发-下游行情依赖】流水线"""
        return FinancialPipeline("契约分发-下游行情依赖").add_stage(WriteManifestStage())

    @staticmethod
    def create_daily_e2e_pipeline(skip_ingest: bool = True, skip_bdib: bool = True) -> FinancialPipeline:
        """每日端到端总控调度 (组合多个子Pipeline的阶段)"""
        pipeline = FinancialPipeline("端到端全链路-日终批处理")

        if not skip_ingest:
            pipeline.add_stage(IngestExcelStage())

        pipeline.add_stage(ProcessRawFillsStage())
        pipeline.add_stage(AggregateFillsStage())
        pipeline.add_stage(GenerateOrderLabelsStage())

        if not skip_bdib:
            pipeline.add_stage(IntegrateBDIBStage())
            pipeline.add_stage(CalculateDailyMetricsStage())  # Stage 7: ADV + volatility

        pipeline.add_stage(WriteManifestStage())
        return pipeline

    @staticmethod
    def create_regime_classification(skip_fetch: bool = False) -> FinancialPipeline:
        """Regime layer: market_index → vol/liq/trend → fill labels."""
        pipeline = FinancialPipeline("行情分类与标签-Regime层")
        pipeline.add_stage(RegimeDailyFeaturesStage())
        pipeline.add_stage(RegimeFillTaggerStage())
        return pipeline

    @staticmethod
    def create_attribution() -> FinancialPipeline:
        """Attribution layer: per-fill IS/VWAP/reversal metrics."""
        pipeline = FinancialPipeline("绩效归因-Attribution层")
        pipeline.add_stage(AttributionMetricsStage())
        return pipeline

"""Pipeline orchestration — stage-based processing framework and scheduler.

Convenience exports for the most common symbols.  For a complete listing
see core.py, stages_ingest.py, stages_process.py, stages_analysis.py.
"""

from .context import PipelineContext
from .base import BaseStage
from .stages_ingest import (
    IngestExcelStage, ProcessRawFillsStage,
    AggregateFillsStage, GenerateOrderLabelsStage,
)
from .stages_process import (
    IntegrateBDIBStage, WriteManifestStage, CalculateDailyMetricsStage,
    ComputeRouteMetricsStage,
)
from .stages_analysis import (
    RegimeDailyFeaturesStage, RegimeFillTaggerStage, AttributionMetricsStage,
)
from .core import (
    FinancialPipeline, PipelineFactory,
    run_ingest, run_process, run_aggregate, run_order_labels,
    run_bdib_integration, run_full_pipeline, run_incremental,
    get_pipeline_status,
)

__all__ = [
    "PipelineContext", "BaseStage",
    "IngestExcelStage", "ProcessRawFillsStage",
    "AggregateFillsStage", "GenerateOrderLabelsStage",
    "IntegrateBDIBStage", "WriteManifestStage", "CalculateDailyMetricsStage",
    "ComputeRouteMetricsStage",
    "RegimeDailyFeaturesStage", "RegimeFillTaggerStage", "AttributionMetricsStage",
    "FinancialPipeline", "PipelineFactory",
    "run_ingest", "run_process", "run_aggregate", "run_order_labels",
    "run_bdib_integration", "run_full_pipeline", "run_incremental",
    "get_pipeline_status",
]

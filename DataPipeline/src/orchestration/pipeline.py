"""
Pipeline framework â€” re-export facade for backward compatibility.

IMPORTANT: New code should import from sub-modules directly:
  from DataPipeline.src.orchestration.context import PipelineContext
  from DataPipeline.src.orchestration.base import BaseStage
  from DataPipeline.src.orchestration.stages import IngestExcelStage
  from DataPipeline.src.orchestration.core import FinancialPipeline, PipelineFactory
  from DataPipeline.src.orchestration.runners import run_full_pipeline

For a transition period, all public symbols are re-exported here.
"""

import warnings as _w

_w.warn(
    "DataPipeline.src.orchestration.pipeline is deprecated. "
    "Import from sub-modules directly: context, base, stages, core, runners",
    DeprecationWarning,
    stacklevel=2,
)

from .context import PipelineContext
from .base import BaseStage, _to_iso_safe
from .stages import (
    IngestExcelStage, ProcessRawFillsStage, AggregateFillsStage,
    GenerateOrderLabelsStage, IntegrateBDIBStage, WriteManifestStage,
    CalculateDailyMetricsStage, RegimeDailyFeaturesStage,
    RegimeFillTaggerStage, AttributionMetricsStage,
)
from .core import FinancialPipeline, PipelineFactory
from .runners import (
    run_ingest, run_process, run_aggregate, run_order_labels,
    run_bdib_integration, run_full_pipeline, run_incremental,
    get_pipeline_status,
)

__all__ = [
    # context
    "PipelineContext",
    # base
    "BaseStage", "_to_iso_safe",
    # stages
    "IngestExcelStage", "ProcessRawFillsStage", "AggregateFillsStage",
    "GenerateOrderLabelsStage", "IntegrateBDIBStage", "WriteManifestStage",
    "CalculateDailyMetricsStage", "RegimeDailyFeaturesStage",
    "RegimeFillTaggerStage", "AttributionMetricsStage",
    # core
    "FinancialPipeline", "PipelineFactory",
    # runners
    "run_ingest", "run_process", "run_aggregate", "run_order_labels",
    "run_bdib_integration", "run_full_pipeline", "run_incremental",
    "get_pipeline_status",
]
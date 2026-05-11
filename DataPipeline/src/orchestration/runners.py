"""
Legacy backward-compatibility runner functions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .context import PipelineContext
from .core import FinancialPipeline, PipelineFactory
from .stages import AggregateFillsStage, GenerateOrderLabelsStage
from DataPipeline.src.storage.facade import CostViewDatabase

logger = logging.getLogger(__name__)


def run_ingest(excel_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Legacy compatibility: Ingest Excel files."""
    ctx = PipelineContext(excel_dir=excel_dir)
    pipeline = PipelineFactory.create_data_sync_legacy()
    pipeline.run(ctx)
    return ctx.summary.get("ingestion", {}).get("results", [])


def run_process(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> pd.DataFrame:
    """Legacy compatibility: Process raw fills."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipeline = PipelineFactory.create_data_processing_trade_model()
    pipeline.run(ctx)

    # Return empty DataFrame as placeholder, caller should query DB directly
    if ctx.proc_db and ctx.target_dates:
        dfs = [ctx.proc_db.get_processed_fills_for_date(d) for d in ctx.target_dates]
        return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    return pd.DataFrame()


def run_aggregate(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> None:
    """Legacy compatibility: Aggregate fills."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    # Note: the factory pipeline also runs OrderLabels, we keep just aggregate for legacy compatibility
    pipeline = FinancialPipeline("降频聚合-订单路由视角(单阶段)").add_stage(AggregateFillsStage())
    pipeline.run(ctx)


def run_order_labels(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> pd.DataFrame:
    """Legacy compatibility: Generate order labels."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipeline = FinancialPipeline("特征提取-全局订单标签(单阶段)").add_stage(GenerateOrderLabelsStage())
    pipeline.run(ctx)
    if ctx.proc_db:
        return ctx.proc_db.get_order_labels()
    return pd.DataFrame()


def run_bdib_integration(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> None:
    """Legacy compatibility: Integrate BDIB data."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipeline = PipelineFactory.create_integration_tca_analysis()
    pipeline.run(ctx)


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
    """
    Run the complete pipeline using the new Object-Oriented Framework.
    """
    ctx = PipelineContext(
        target_dates=dates or [],
        force=force,
        excel_dir=excel_dir,
        config={
            "stage_marker_name": stage_marker_name,
            "stage_marker_start": stage_marker_start,
            "stage_marker_end": stage_marker_end,
        },
    )

    pipeline = PipelineFactory.create_daily_e2e_pipeline(
        skip_ingest=skip_ingest,
        skip_bdib=skip_bdib
    )

    if skip_ingest:
        ctx.summary["ingestion"] = {"skipped": True}
    if skip_bdib:
        ctx.summary["bdib"] = {"skipped": True}

    # 执行流水线
    pipeline.run(ctx)
    return ctx.summary


def run_incremental(
    excel_dir: Optional[Path] = None,
    skip_bdib: bool = True,
    stage_marker_name: Optional[str] = None,
    stage_marker_start: int = 0,
    stage_marker_end: int = 100,
) -> Dict[str, Any]:
    """Run incremental pipeline - only process new/changed data."""
    return run_full_pipeline(
        excel_dir=excel_dir,
        dates=None,
        force=False,
        skip_bdib=skip_bdib,
        skip_ingest=True,
        stage_marker_name=stage_marker_name,
        stage_marker_start=stage_marker_start,
        stage_marker_end=stage_marker_end,
    )


def get_pipeline_status() -> Dict[str, Any]:
    """Get current status of the processing pipeline."""
    status: Dict[str, Any] = {}
    db = CostViewDatabase()

    try:
        raw_db_inst = db.raw_db
        status["raw_fills"] = {
            "total_rows": raw_db_inst.get_row_count(),
            "dates": raw_db_inst.get_all_source_dates(),
            "date_counts": raw_db_inst.get_date_row_counts(),
        }
        fetch_log = raw_db_inst.get_fetch_log_stats()
        status["fetch_log"] = {
            "entries": len(fetch_log),
            "latest": fetch_log[0] if fetch_log else None,
        }
    except Exception as e:
        status["raw_fills"] = {"error": str(e)}

    try:
        proc_db_inst = db.proc_db
        stats = proc_db_inst.get_processing_stats()
        status["processed_fills"] = stats
    except Exception as e:
        status["processed_fills"] = {"error": str(e)}

    # ── BDIB pipeline (3-layer) status ──
    try:
        raw_bdib_inst = db.raw_bdib_db
        status["raw_bdib"] = {
            "total_rows": raw_bdib_inst.get_row_count(),
            "db_path": str(db.connection_manager.get_path("raw_bdib")),
        }
    except Exception as e:
        status["raw_bdib"] = {"error": str(e)}

    try:
        proc_raw_bdib_inst = db.processed_raw_bdib_db
        status["processed_raw_bdib"] = {
            "total_rows": proc_raw_bdib_inst.get_row_count(),
            "db_path": str(db.connection_manager.get_path("processed_raw_bdib")),
        }
    except Exception as e:
        status["processed_raw_bdib"] = {"error": str(e)}

    try:
        fill_bdib_inst = db.fill_bdib_db
        status["fill_bdib"] = {
            "total_rows": fill_bdib_inst.get_row_count(),
            "db_path": str(db.connection_manager.get_path("fill_bdib")),
        }
        # Backward-compatible key for existing consumers
        status["processed_bdib"] = status["fill_bdib"]
    except Exception as e:
        status["fill_bdib"] = {"error": str(e)}
        status["processed_bdib"] = {"error": str(e)}

    return status

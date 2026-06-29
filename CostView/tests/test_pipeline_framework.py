"""Tests for PipelineContext, BaseStage, FinancialPipeline, PipelineFactory.

Uses mock objects and real pipeline classes from DataPipeline.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from DataPipeline.orchestration.context import PipelineContext
from DataPipeline.orchestration.base import BaseStage
from DataPipeline.orchestration.core import FinancialPipeline, PipelineFactory
from DataPipeline.orchestration.stages_ingest import (
    IngestExcelStage, ProcessRawFillsStage,
    AggregateFillsStage, GenerateOrderLabelsStage,
)
from DataPipeline.orchestration.stages_process import (
    IntegrateBDIBStage, WriteManifestStage, CalculateDailyMetricsStage,
)
from DataPipeline.orchestration.stages_analysis import (
    RegimeDailyFeaturesStage, RegimeFillTaggerStage, AttributionMetricsStage,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helper: concrete stage for testing BaseStage
# ═══════════════════════════════════════════════════════════════════════════

class _SuccessStage(BaseStage):
    @property
    def name(self) -> str:
        return "success-stage"

    def process(self, context: PipelineContext) -> bool:
        context.summary["result"] = "ok"
        return True


class _FailStage(BaseStage):
    @property
    def name(self) -> str:
        return "fail-stage"

    def process(self, context: PipelineContext) -> bool:
        raise RuntimeError("stage failure")


class _ReturnFalseStage(BaseStage):
    @property
    def name(self) -> str:
        return "return-false-stage"

    def process(self, context: PipelineContext) -> bool:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# PipelineContext Tests
# ═══════════════════════════════════════════════════════════════════════════

class PipelineContextTest(unittest.TestCase):
    """Tests for PipelineContext data class."""

    def test_default_construction(self):
        """Default field values are correct."""
        ctx = PipelineContext()
        self.assertEqual(ctx.target_dates, [])
        self.assertFalse(ctx.force)
        self.assertEqual(ctx.config, {})
        self.assertEqual(ctx.summary, {})
        self.assertTrue(ctx.is_successful)
        self.assertEqual(ctx.errors, [])

    def test_lazy_db_initialization(self):
        """context.db is created on first access (lazy)."""
        ctx = PipelineContext()
        self.assertIsNone(ctx._db)  # Not initialized yet
        db = ctx.db                  # Triggers initialization
        self.assertIsNotNone(db)
        self.assertIsNotNone(ctx._db)

    def test_log_error(self):
        """log_error sets is_successful=False and records the error."""
        ctx = PipelineContext()
        ctx.log_error("test-stage", ValueError("test error"))
        self.assertFalse(ctx.is_successful)
        self.assertEqual(len(ctx.errors), 1)
        self.assertEqual(ctx.errors[0]["stage"], "test-stage")
        self.assertIn("test error", ctx.errors[0]["error"])

    def test_log_error_multiple(self):
        """Multiple errors are all recorded."""
        ctx = PipelineContext()
        ctx.log_error("stage-1", ValueError("err1"))
        ctx.log_error("stage-2", RuntimeError("err2"))
        self.assertEqual(len(ctx.errors), 2)
        self.assertFalse(ctx.is_successful)

    def test_summary_is_mutable_dict(self):
        """Summary dict is writable and readable."""
        ctx = PipelineContext()
        ctx.summary["key1"] = "value1"
        ctx.summary["key2"] = {"nested": True}
        self.assertEqual(ctx.summary["key1"], "value1")
        self.assertTrue(ctx.summary["key2"]["nested"])

    def test_connection_manager_lazy(self):
        """Connection manager is lazily created."""
        ctx = PipelineContext()
        self.assertIsNone(ctx._cm)
        mgr = ctx.connection_manager
        self.assertIsNotNone(mgr)

    def test_connection_manager_reuses(self):
        """Same ConnectionManager returned from repeated calls."""
        ctx = PipelineContext()
        mgr1 = ctx.connection_manager
        mgr2 = ctx.connection_manager
        self.assertIs(mgr1, mgr2)


# ═══════════════════════════════════════════════════════════════════════════
# BaseStage Tests
# ═══════════════════════════════════════════════════════════════════════════

class BaseStageTest(unittest.TestCase):
    """Tests for abstract BaseStage."""

    def test_execute_calls_process(self):
        """execute() delegates to process()."""
        stage = _SuccessStage()
        ctx = PipelineContext()
        result = stage.execute(ctx)
        self.assertTrue(result)
        self.assertEqual(ctx.summary.get("result"), "ok")

    def test_execute_catches_exception(self):
        """Exception in process() → execute() returns False and logs error."""
        stage = _FailStage()
        ctx = PipelineContext()
        result = stage.execute(ctx)
        self.assertFalse(result)
        self.assertFalse(ctx.is_successful)
        self.assertEqual(len(ctx.errors), 1)

    def test_execute_returns_true_on_success(self):
        """Successful execution returns True."""
        stage = _SuccessStage()
        ctx = PipelineContext()
        self.assertTrue(stage.execute(ctx))

    def test_name_is_abstract(self):
        """Direct BaseStage instantiation raises TypeError."""
        with self.assertRaises(TypeError):
            BaseStage()

    def test_name_property(self):
        """Stage name property returns correct string."""
        stage = _SuccessStage()
        self.assertEqual(stage.name, "success-stage")


# ═══════════════════════════════════════════════════════════════════════════
# FinancialPipeline Tests
# ═══════════════════════════════════════════════════════════════════════════

class FinancialPipelineTest(unittest.TestCase):
    """Tests for FinancialPipeline orchestrator."""

    def test_empty_pipeline(self):
        """No stages → run() returns context."""
        pipeline = FinancialPipeline("empty")
        ctx = PipelineContext()
        result = pipeline.run(ctx)
        self.assertIs(result, ctx)

    def test_single_stage(self):
        """Single stage executes successfully."""
        pipeline = FinancialPipeline("single")
        pipeline.add_stage(_SuccessStage())
        ctx = PipelineContext()
        result = pipeline.run(ctx)
        self.assertTrue(result.is_successful)
        self.assertEqual(result.summary.get("result"), "ok")

    def test_multiple_stages(self):
        """Multiple stages execute in sequence."""
        pipeline = FinancialPipeline("multi")
        pipeline.add_stage(_SuccessStage())
        pipeline.add_stage(_SuccessStage())
        ctx = PipelineContext()
        result = pipeline.run(ctx)
        self.assertTrue(result.is_successful)

    def test_pipeline_stops_on_failure(self):
        """Stage returns False → pipeline stops."""
        pipeline = FinancialPipeline("stop-on-fail")
        pipeline.add_stage(_SuccessStage())
        pipeline.add_stage(_ReturnFalseStage())
        pipeline.add_stage(_SuccessStage())
        ctx = PipelineContext()
        result = pipeline.run(ctx)
        # Third stage should not have been executed
        # We can verify by checking only stages 1 and 2 ran

    def test_add_stage_returns_self(self):
        """add_stage returns self for chaining."""
        pipeline = FinancialPipeline("chain")
        result = pipeline.add_stage(_SuccessStage())
        self.assertIs(result, pipeline)

    def test_stage_markers(self):
        """Stage marker printing works correctly."""
        ctx = PipelineContext(
            config={
                "stage_marker_name": "progress",
                "stage_marker_start": 0,
                "stage_marker_end": 100,
            }
        )
        pipeline = FinancialPipeline("marker-test")
        pipeline.add_stage(_SuccessStage())
        pipeline.add_stage(_SuccessStage())

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            pipeline.run(ctx)

        output = buffer.getvalue()
        self.assertIn("[STAGE] progress 50", output)
        self.assertIn("[STAGE] progress 100", output)

    def test_run_returns_context(self):
        """run() returns the PipelineContext."""
        pipeline = FinancialPipeline("ret-ctx")
        ctx = PipelineContext()
        result = pipeline.run(ctx)
        self.assertIs(result, ctx)

    def test_custom_name(self):
        """Custom pipeline name is stored."""
        pipeline = FinancialPipeline("custom-name")
        self.assertEqual(pipeline.name, "custom-name")


# ═══════════════════════════════════════════════════════════════════════════
# PipelineFactory Tests
# ═══════════════════════════════════════════════════════════════════════════

class PipelineFactoryTest(unittest.TestCase):
    """Tests for PipelineFactory.create_daily_e2e_pipeline."""

    def test_create_daily_e2e_pipeline_default(self):
        """Default E2E pipeline (skip_ingest=True, skip_bdib=True)."""
        pipeline = PipelineFactory.create_daily_e2e_pipeline()
        stages = pipeline._stages
        self.assertEqual(len(stages), 4)  # process + agg + labels + manifest
        self.assertIsInstance(stages[0], ProcessRawFillsStage)
        self.assertIsInstance(stages[1], AggregateFillsStage)
        self.assertIsInstance(stages[2], GenerateOrderLabelsStage)
        self.assertIsInstance(stages[3], WriteManifestStage)

    def test_create_daily_e2e_pipeline_with_bdib(self):
        """E2E pipeline with BDIB includes extra stages."""
        pipeline = PipelineFactory.create_daily_e2e_pipeline(skip_bdib=False)
        stages = pipeline._stages
        self.assertEqual(len(stages), 6)
        self.assertIsInstance(stages[3], IntegrateBDIBStage)
        self.assertIsInstance(stages[4], CalculateDailyMetricsStage)

    def test_create_daily_e2e_pipeline_with_ingest(self):
        """E2E pipeline with ingest includes IngestExcelStage at start."""
        pipeline = PipelineFactory.create_daily_e2e_pipeline(
            skip_ingest=False, skip_bdib=True,
        )
        stages = pipeline._stages
        self.assertEqual(len(stages), 5)
        self.assertIsInstance(stages[0], IngestExcelStage)

    def test_factory_returns_FinancialPipeline(self):
        self.assertIsInstance(
            PipelineFactory.create_daily_e2e_pipeline(), FinancialPipeline)

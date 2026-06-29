"""Tests for all 10 pipeline stages and legacy compatibility functions.

Uses FakePipelineContext and mock objects to isolate stage logic
from database and external dependencies.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pandas as pd

from DataPipeline.orchestration.context import PipelineContext
from DataPipeline.orchestration.base import _to_iso_safe
from DataPipeline.orchestration.core import (
    PipelineFactory,
    run_ingest, run_process, run_aggregate, run_order_labels,
    run_bdib_integration, run_full_pipeline, run_incremental,
)
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
from CostView.tests.testing_helpers import FakePipelineContext


# ═══════════════════════════════════════════════════════════════════════════
# Stage 1: IngestExcelStage
# ═══════════════════════════════════════════════════════════════════════════

class TestIngestExcelStage(unittest.TestCase):
    """Tests for IngestExcelStage."""

    def test_name_returns_correct(self):
        stage = IngestExcelStage()
        self.assertEqual(stage.name, "1. Ingest Excel (Legacy)")

    @patch("DataPipeline.orchestration.stages.ingest_all_excel_files")
    def test_process_calls_ingest_all(self, mock_ingest):
        mock_ingest.return_value = [
            {"new_rows": 10, "skipped": False},
            {"new_rows": 5, "skipped": True},
        ]
        ctx = FakePipelineContext()
        stage = IngestExcelStage()
        result = stage.process(ctx)
        self.assertTrue(result)
        mock_ingest.assert_called_once()

    @patch("DataPipeline.orchestration.stages.ingest_all_excel_files")
    def test_process_populates_summary(self, mock_ingest):
        mock_ingest.return_value = [
            {"new_rows": 10, "skipped": False},
            {"new_rows": 5, "skipped": True},
        ]
        ctx = FakePipelineContext()
        stage = IngestExcelStage()
        stage.process(ctx)
        self.assertIn("ingestion", ctx.summary)
        self.assertEqual(ctx.summary["ingestion"]["files_processed"], 2)
        self.assertEqual(ctx.summary["ingestion"]["new_rows"], 15)
        self.assertEqual(ctx.summary["ingestion"]["skipped"], 1)

    @patch("DataPipeline.orchestration.stages.ingest_all_excel_files")
    def test_process_without_excel_dir(self, mock_ingest):
        mock_ingest.return_value = []
        ctx = FakePipelineContext()
        stage = IngestExcelStage()
        result = stage.process(ctx)
        self.assertTrue(result)
        self.assertEqual(ctx.summary["ingestion"]["files_processed"], 0)


# ═══════════════════════════════════════════════════════════════════════════
# Stage 2: ProcessRawFillsStage
# ═══════════════════════════════════════════════════════════════════════════

class TestProcessRawFillsStage(unittest.TestCase):
    """Tests for ProcessRawFillsStage."""

    def test_name(self):
        stage = ProcessRawFillsStage()
        self.assertEqual(stage.name, "2. Process Raw Fills -> Clean -> Enrich")

    def test_no_raw_dates_returns_early(self):
        ctx = FakePipelineContext()
        ctx._db.raw_fills_read.get_all_source_dates.return_value = []
        stage = ProcessRawFillsStage()
        result = stage.process(ctx)
        self.assertTrue(result)
        self.assertEqual(ctx.summary["processing"]["rows_processed"], 0)

    @patch("DataPipeline.orchestration.stages.process_raw_fills_for_date")
    def test_processes_selected_dates(self, mock_process):
        mock_process.return_value = {
            "success": True, "rows_processed": 10,
            "order_history_rows": 5, "route_history_rows": 3, "route_event_rows": 1,
        }
        ctx = FakePipelineContext(target_dates=["20260408"])
        ctx._db.raw_fills_read.get_all_source_dates.return_value = ["20260408", "20260409"]
        stage = ProcessRawFillsStage()
        result = stage.process(ctx)
        self.assertTrue(result)
        mock_process.assert_called_once()

    @patch("DataPipeline.orchestration.stages.process_raw_fills_for_date")
    def test_error_date_does_not_block_others(self, mock_process):
        mock_process.side_effect = [
            {"success": False, "error": "bad date"},
            {"success": True, "rows_processed": 10,
             "order_history_rows": 0, "route_history_rows": 0, "route_event_rows": 0},
        ]
        ctx = FakePipelineContext(target_dates=["20260408", "20260409"])
        ctx._db.raw_fills_read.get_all_source_dates.return_value = ["20260408", "20260409"]
        stage = ProcessRawFillsStage()
        result = stage.process(ctx)
        self.assertTrue(result)
        self.assertEqual(mock_process.call_count, 2)

    @patch("DataPipeline.orchestration.stages.process_raw_fills_for_date")
    def test_summary_contains_row_counts(self, mock_process):
        mock_process.return_value = {
            "success": True, "rows_processed": 25,
            "order_history_rows": 10, "route_history_rows": 5, "route_event_rows": 2,
        }
        ctx = FakePipelineContext(target_dates=["20260408"])
        ctx._db.raw_fills_read.get_all_source_dates.return_value = ["20260408"]
        stage = ProcessRawFillsStage()
        stage.process(ctx)
        self.assertEqual(ctx.summary["processing"]["rows_processed"], 25)
        self.assertEqual(ctx.summary["processing"]["order_history_rows"], 10)

    def test_no_target_dates_no_force_incremental(self):
        ctx = FakePipelineContext()
        ctx._db.raw_fills_read.get_all_source_dates.return_value = ["20260408"]
        ctx._db.fills_read.get_unprocessed_dates.return_value = []
        ctx._db.fills_read.get_processed_dates.return_value = []
        stage = ProcessRawFillsStage()
        result = stage.process(ctx)
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# Stage 3: AggregateFillsStage
# ═══════════════════════════════════════════════════════════════════════════

class TestAggregateFillsStage(unittest.TestCase):
    """Tests for AggregateFillsStage."""

    def test_name(self):
        stage = AggregateFillsStage()
        self.assertEqual(stage.name, "3. Aggregate (route-level 10s)")

    def test_no_dates_returns_early(self):
        ctx = FakePipelineContext()
        ctx._db.fills_read.get_processed_dates.return_value = []
        ctx._db.fills_read.get_unprocessed_dates.return_value = []
        stage = AggregateFillsStage()
        result = stage.process(ctx)
        self.assertTrue(result)
        self.assertEqual(ctx.summary["aggregation"]["dates"], 0)

    @patch("DataPipeline.orchestration.stages.generate_agg_fills_10s")
    def test_empty_processed_df_skipped(self, mock_gen):
        mock_gen.return_value = pd.DataFrame()
        ctx = FakePipelineContext(target_dates=["20260408"])
        ctx._db.fills_read.get_fills_for_date.return_value = pd.DataFrame()
        stage = AggregateFillsStage()
        result = stage.process(ctx)
        self.assertTrue(result)

    def test_aggregates_single_date(self):
        ctx = FakePipelineContext(target_dates=["20260408"])
        processed_df = pd.DataFrame([{
            "OrderId": "ORD001", "RouteId": "RTE000",
            "order_as_of_date": "20260408", "mkt_timestamp": "09:30:00",
            "FillPrice": 100.0, "FillShares": 100,
        }])
        ctx._db.fills_read.get_fills_for_date.return_value = processed_df

        stage = AggregateFillsStage()
        result = stage.process(ctx)
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# Stage 4: GenerateOrderLabelsStage
# ═══════════════════════════════════════════════════════════════════════════

class TestGenerateOrderLabelsStage(unittest.TestCase):
    """Tests for GenerateOrderLabelsStage."""

    def test_name(self):
        stage = GenerateOrderLabelsStage()
        self.assertEqual(stage.name, "4. Generate Order Labels")

    def test_no_processed_fills_returns_early(self):
        ctx = FakePipelineContext()
        ctx._db.fills_read.get_all_processed_fills.return_value = pd.DataFrame()
        ctx._db.fills_read.get_processed_dates.return_value = []
        stage = GenerateOrderLabelsStage()
        result = stage.process(ctx)
        self.assertTrue(result)
        self.assertEqual(ctx.summary["order_labels"]["orders"], 0)

    @patch("DataPipeline.orchestration.stages.generate_order_label_incremental")
    def test_generates_labels_for_dates(self, mock_gen):
        mock_gen.return_value = pd.DataFrame({"OrderId": ["ORD001"], "order_as_of_date": ["20260408"]})
        ctx = FakePipelineContext(target_dates=["20260408"])
        ctx._db.fills_read.get_fills_for_date.return_value = pd.DataFrame([{
            "OrderId": "ORD001", "RouteId": "RTE000", "FillId": "FILL00001",
            "order_as_of_date": "20260408",
        }])
        ctx._db.fills_read.get_order_labels.return_value = pd.DataFrame()
        stage = GenerateOrderLabelsStage()
        result = stage.process(ctx)
        self.assertTrue(result)
        self.assertEqual(ctx.summary["order_labels"]["orders"], 1)

    @patch("DataPipeline.orchestration.stages.generate_order_label_incremental")
    def test_force_regenerates_all(self, mock_gen):
        mock_gen.return_value = pd.DataFrame()
        ctx = FakePipelineContext(target_dates=["20260408"], force=True)
        ctx._db.fills_read.get_fills_for_date.return_value = pd.DataFrame([{
            "OrderId": "ORD001", "RouteId": "RTE000", "FillId": "FILL00001",
            "order_as_of_date": "20260408",
        }])
        stage = GenerateOrderLabelsStage()
        result = stage.process(ctx)
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# Stage 5: IntegrateBDIBStage
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegrateBDIBStage(unittest.TestCase):
    """Tests for IntegrateBDIBStage."""

    def test_name(self):
        stage = IntegrateBDIBStage()
        self.assertEqual(stage.name, "5. Integrate BDIB Market Data")

    def test_import_error_graceful(self):
        """When bdib_fetcher import fails, stage logs warning and returns True."""
        stage = IntegrateBDIBStage()
        ctx = FakePipelineContext(target_dates=["20260408"])
        result = stage.process(ctx)
        self.assertTrue(result)
        self.assertTrue(ctx.summary.get("bdib", {}).get("skipped", False))

    def test_get_previous_weekday(self):
        """Previous weekday skips Saturday/Sunday."""
        # Friday -> Thursday
        friday = date(2026, 4, 10)  # Friday
        prev = IntegrateBDIBStage._get_previous_weekday(friday)
        self.assertEqual(prev, date(2026, 4, 9))  # Thursday

        # Monday -> Friday
        monday = date(2026, 4, 13)  # Monday
        prev = IntegrateBDIBStage._get_previous_weekday(monday)
        self.assertEqual(prev, date(2026, 4, 10))  # Friday

        # Sunday -> Friday
        sunday = date(2026, 4, 12)  # Sunday
        prev = IntegrateBDIBStage._get_previous_weekday(sunday)
        self.assertEqual(prev, date(2026, 4, 10))  # Friday

    def test_get_latest_safe_bdib_date_cutoff(self):
        """Cut-off time before/after changes safe date."""
        morning = datetime(2026, 4, 22, 9, 26)
        evening = datetime(2026, 4, 22, 18, 30)
        self.assertEqual(
            IntegrateBDIBStage._get_latest_safe_bdib_date(morning),
            date(2026, 4, 20),
        )
        self.assertEqual(
            IntegrateBDIBStage._get_latest_safe_bdib_date(evening),
            date(2026, 4, 21),
        )

    def test_expand_weekdays(self):
        """Weekday expansion generates Mon-Fri only."""
        start = date(2026, 4, 13)  # Monday
        end = date(2026, 4, 19)   # Sunday
        dates = IntegrateBDIBStage._expand_weekdays(start, end)
        self.assertEqual(len(dates), 5)  # Mon-Fri only
        self.assertIn("20260413", dates)
        self.assertIn("20260417", dates)

    def test_expand_weekdays_empty(self):
        """End before start returns empty list."""
        start = date(2026, 4, 13)
        end = date(2026, 4, 10)
        dates = IntegrateBDIBStage._expand_weekdays(start, end)
        self.assertEqual(dates, [])


# ═══════════════════════════════════════════════════════════════════════════
# Stage 6: WriteManifestStage
# ═══════════════════════════════════════════════════════════════════════════

class TestWriteManifestStage(unittest.TestCase):
    """Tests for WriteManifestStage."""

    def test_name(self):
        stage = WriteManifestStage()
        self.assertEqual(stage.name, "6. Write MarketFetch Manifest")

    def test_writes_manifest_fails_gracefully(self):
        """The downstream_interface import is not available — stage handles gracefully."""
        ctx = FakePipelineContext(target_dates=["20260408"])
        stage = WriteManifestStage()
        result = stage.process(ctx)
        self.assertTrue(result)  # Stage does not fail
        # Should have an error or skipped entry in summary
        self.assertIn("manifest", ctx.summary)

    def test_manifest_error_not_fatal(self):
        """Stage returns True even when manifest write fails."""
        ctx = FakePipelineContext(target_dates=["20260408"])
        stage = WriteManifestStage()
        result = stage.process(ctx)
        self.assertTrue(result)  # Stage does not fail
        self.assertIn("manifest", ctx.summary)


# ═══════════════════════════════════════════════════════════════════════════
# Stage 7: CalculateDailyMetricsStage
# ═══════════════════════════════════════════════════════════════════════════

class TestCalculateDailyMetricsStage(unittest.TestCase):
    """Tests for CalculateDailyMetricsStage."""

    def test_name(self):
        stage = CalculateDailyMetricsStage()
        self.assertEqual(stage.name, "7. Calculate Daily Metrics (ADV + Volatility)")

    def test_import_error_graceful(self):
        """ImportError skips stage gracefully."""
        stage = CalculateDailyMetricsStage()
        ctx = FakePipelineContext(target_dates=["20260408"])
        result = stage.process(ctx)
        self.assertTrue(result)
        self.assertTrue(ctx.summary.get("daily_metrics", {}).get("skipped", False))

    def test_no_dates_returns_early(self):
        stage = CalculateDailyMetricsStage()
        ctx = FakePipelineContext()
        ctx._db.fills_read.get_processed_dates.return_value = []
        ctx._db.market_data_read.get_distinct_dates.return_value = []
        result = stage.process(ctx)
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# Stage 8: RegimeDailyFeaturesStage
# ═══════════════════════════════════════════════════════════════════════════

class TestRegimeDailyFeaturesStage(unittest.TestCase):
    """Tests for RegimeDailyFeaturesStage."""

    def test_name(self):
        stage = RegimeDailyFeaturesStage()
        self.assertEqual(stage.name, "8. Regime Daily Features (vol/liq/trend)")

    def test_no_target_dates_skips(self):
        stage = RegimeDailyFeaturesStage()
        ctx = FakePipelineContext()
        result = stage.process(ctx)
        self.assertTrue(result)
        self.assertTrue(ctx.summary.get("regime_daily", {}).get("skipped", False))

    def test_import_error_graceful(self):
        stage = RegimeDailyFeaturesStage()
        ctx = FakePipelineContext(target_dates=["20260408"])
        result = stage.process(ctx)
        self.assertTrue(result)
        self.assertTrue(ctx.summary.get("regime_daily", {}).get("skipped", False))

    def test_iso_date_conversion(self):
        """YYYYMMDD is correctly converted to ISO format."""
        from DataPipeline.orchestration.base import _to_iso_safe
        self.assertEqual(_to_iso_safe("20260408"), "2026-04-08")
        self.assertEqual(_to_iso_safe("2026-04-08"), "2026-04-08")
        self.assertIsNone(_to_iso_safe(""))
        self.assertIsNone(_to_iso_safe(None))
        self.assertIsNone(_to_iso_safe("invalid"))


# ═══════════════════════════════════════════════════════════════════════════
# Stage 9: RegimeFillTaggerStage
# ═══════════════════════════════════════════════════════════════════════════

class TestRegimeFillTaggerStage(unittest.TestCase):
    """Tests for RegimeFillTaggerStage."""

    def test_name(self):
        stage = RegimeFillTaggerStage()
        self.assertEqual(stage.name, "9. Regime Fill Tagger")

    def test_skips_without_dates(self):
        stage = RegimeFillTaggerStage()
        ctx = FakePipelineContext()
        result = stage.process(ctx)
        self.assertTrue(result)

    def test_import_error_graceful(self):
        stage = RegimeFillTaggerStage()
        ctx = FakePipelineContext(target_dates=["20260408"])
        result = stage.process(ctx)
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# Stage 10: AttributionMetricsStage
# ═══════════════════════════════════════════════════════════════════════════

class TestAttributionMetricsStage(unittest.TestCase):
    """Tests for AttributionMetricsStage."""

    def test_name(self):
        stage = AttributionMetricsStage()
        self.assertEqual(stage.name, "10. Attribution Metrics")

    def test_skips_without_dates(self):
        stage = AttributionMetricsStage()
        ctx = FakePipelineContext()
        result = stage.process(ctx)
        self.assertTrue(result)

    def test_import_error_graceful(self):
        stage = AttributionMetricsStage()
        ctx = FakePipelineContext(target_dates=["20260408"])
        result = stage.process(ctx)
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# Helper: _to_iso_safe (used by stages 8-10)
# ═══════════════════════════════════════════════════════════════════════════

class TestToIsoSafe(unittest.TestCase):
    """Tests for _to_iso_safe helper."""

    def test_yyyymmdd_conversion(self):
        self.assertEqual(_to_iso_safe("20260408"), "2026-04-08")

    def test_iso_format_preserved(self):
        self.assertEqual(_to_iso_safe("2026-04-08"), "2026-04-08")

    def test_none_returns_none(self):
        self.assertIsNone(_to_iso_safe(None))

    def test_empty_returns_none(self):
        self.assertIsNone(_to_iso_safe(""))

    def test_invalid_returns_none(self):
        self.assertIsNone(_to_iso_safe("not-a-date"))


# ═══════════════════════════════════════════════════════════════════════════
# Legacy Compatibility Functions
# ═══════════════════════════════════════════════════════════════════════════

class TestLegacyRunners(unittest.TestCase):
    """Tests for legacy backward-compatibility runner functions."""

    def setUp(self):
        self.ingest_patcher = patch(
            "DataPipeline.orchestration.stages.ingest_all_excel_files",
            return_value=[],
        )
        self.process_patcher = patch(
            "DataPipeline.orchestration.stages.process_raw_fills_for_date",
            return_value={"success": True, "rows_processed": 0,
                          "order_history_rows": 0, "route_history_rows": 0,
                          "route_event_rows": 0},
        )
        self.mock_ingest = self.ingest_patcher.start()
        self.mock_process = self.process_patcher.start()

    def tearDown(self):
        self.ingest_patcher.stop()
        self.process_patcher.stop()

    def test_run_ingest(self):
        """run_ingest constructs pipeline and runs."""
        result = run_ingest(excel_dir=Path("/tmp/fake"))
        self.assertIsInstance(result, list)

    def test_run_process(self):
        """run_process returns a DataFrame."""
        with patch.object(PipelineContext, "proc_db", create=True) as mock_proc:
            mock_proc.get_processed_fills_for_date.return_value = pd.DataFrame()
            result = run_process(dates=["20260408"])
            self.assertIsInstance(result, pd.DataFrame)

    def test_run_aggregate(self):
        """run_aggregate does not crash."""
        ctx = PipelineContext(target_dates=["20260408"])
        # AggregateFillsStage will use proc_db from context
        ctx.proc_db = MagicMock()
        ctx.proc_db.get_processed_fills_for_date.return_value = pd.DataFrame()
        ctx.proc_db.get_processed_dates.return_value = ["20260408"]
        ctx.proc_db.get_unprocessed_dates.return_value = []
        # run_aggregate creates its own context, so we need to patch PipelineContext
        with patch("DataPipeline.orchestration.runners.PipelineContext",
                   return_value=ctx):
            run_aggregate(dates=["20260408"])

    def test_run_order_labels(self):
        """run_order_labels returns a DataFrame."""
        ctx = PipelineContext(target_dates=["20260408"])
        ctx.proc_db = MagicMock()
        ctx.proc_db.get_order_labels.return_value = pd.DataFrame()
        ctx.proc_db.get_processed_fills_for_date.return_value = pd.DataFrame()
        ctx.proc_db.get_processed_dates.return_value = ["20260408"]
        ctx.proc_db.get_all_processed_fills.return_value = pd.DataFrame()

        with patch("DataPipeline.orchestration.runners.PipelineContext",
                   return_value=ctx):
            result = run_order_labels(dates=["20260408"])
            self.assertIsInstance(result, pd.DataFrame)

    def test_run_bdib_integration(self):
        """run_bdib_integration does not crash (imports fail gracefully)."""
        run_bdib_integration(dates=["20260408"])

    @patch("DataPipeline.orchestration.runners.PipelineFactory.create_daily_e2e_pipeline")
    def test_run_full_pipeline_default(self, mock_factory):
        """run_full_pipeline with defaults returns summary dict."""
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = PipelineContext()
        mock_factory.return_value = mock_pipeline

        result = run_full_pipeline()
        self.assertIsInstance(result, dict)

    @patch("DataPipeline.orchestration.runners.PipelineFactory.create_daily_e2e_pipeline")
    def test_run_full_pipeline_with_params(self, mock_factory):
        """run_full_pipeline passes parameters through."""
        mock_pipeline = MagicMock()
        mock_ctx = PipelineContext()
        mock_ctx.summary = {"test": "value"}
        mock_pipeline.run.return_value = mock_ctx
        mock_factory.return_value = mock_pipeline

        result = run_full_pipeline(
            excel_dir=Path("/tmp/fake"),
            dates=["20260408"],
            force=True,
            skip_bdib=False,
            skip_ingest=False,
        )
        self.assertIsInstance(result, dict)

    @patch("DataPipeline.orchestration.runners.run_full_pipeline")
    def test_run_incremental_calls_through(self, mock_run):
        """run_incremental delegates to run_full_pipeline."""
        mock_run.return_value = {"incremental": True}
        result = run_incremental()
        self.assertEqual(result.get("incremental"), True)
        mock_run.assert_called_once()

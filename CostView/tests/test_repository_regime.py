"""Tests for SqliteRegimeReadRepository and SqliteRegimeWriteRepository.

Uses real SQLite databases in temp directories.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime

import pandas as pd

from DataPipeline.storage.dto import (
    AttributionRowDTO,
    FillMetricsQueryDTO,
    PipelineRunDTO,
    PipelineRunResultDTO,
)
from DataPipeline.storage.repositories.regime import (
    SqliteRegimeReadRepository,
    SqliteRegimeWriteRepository,
)
from CostView.tests.testing_helpers import create_temp_db


def _make_attribution_rows(num_rows: int = 3, date_iso: str = "2026-04-08",
                            config_version: str = "test-v1") -> list:
    """Create test AttributionRowDTO objects."""
    rows = []
    for i in range(num_rows):
        rows.append(AttributionRowDTO(
            order_id="ORD001",
            route_id=f"RTE{i:03d}",
            fill_id=f"FILL{i:05d}",
            order_as_of_date_iso=date_iso,
            config_version=config_version,
            market_code="US",
            broker="BROKER_A",
            algo="VWAP",
            side=1,
            fill_shares=100.0,
            fill_price=100.0 + i * 0.5,
            route_shares=200.0,
            pct_adv=0.01,
            participation_rate=0.05,
            arrival_px=99.5,
            interval_vwap=100.3,
            mid_at_fill=100.0,
            mid_fill_plus_1m=100.1,
            mid_fill_plus_5m=100.5,
            mid_fill_plus_30m=101.0,
            is_bps=5.0,
            vwap_bps=3.0,
            reversal_1m_bps=-1.0,
            reversal_5m_bps=-5.0,
            reversal_30m_bps=-10.0,
            data_quality_flags=0,
            source_version="1.0",
            ingested_at="2026-04-08T12:00:00",
        ))
    return rows


class SqliteRegimeReadRepositoryTest(unittest.TestCase):
    """Tests for regime read operations."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = create_temp_db("regime", self.tmp_dir.name)
        self.read_repo = SqliteRegimeReadRepository(self.mgr)
        self.write_repo = SqliteRegimeWriteRepository(self.mgr)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _seed_attribution(self, num_rows: int = 3, date_iso: str = "2026-04-08"):
        rows = _make_attribution_rows(num_rows=num_rows, date_iso=date_iso)
        self.write_repo.upsert_attribution_metrics(rows)

    def _seed_regime_config(self, version_id: str = "test-v1", is_active: int = 1):
        """Seed config into audit_regime_config_versions (used by read repo)."""
        conn = self.mgr.get_admin_connection("regime")
        try:
            conn.execute("""
                INSERT INTO audit_regime_config_versions
                    (version_id, description, parameters, is_active, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (version_id, "Test config", '{"key": "value"}', is_active,
                  datetime.now().isoformat()))
            conn.commit()
        finally:
            conn.close()

    def _seed_attr_config(self, version_id: str = "test-v1", is_active: int = 1):
        """Seed config into audit_attribution_config_versions (used by write repo)."""
        conn = self.mgr.get_admin_connection("regime")
        try:
            conn.execute("""
                INSERT INTO audit_attribution_config_versions
                    (version_id, bench_methods, reversal_windows_min,
                     winsor_pct, adv_window_days, bootstrap_n, min_cell_n,
                     is_active, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (version_id, "arrival_mid,interval_vwap", "1,5,30",
                  0.05, 20, 5000, 30, is_active,
                  "Test config", datetime.now().isoformat()))
            conn.commit()
        finally:
            conn.close()

    def test_get_attribution_metrics_via_dto(self):
        """Metrics query via FillMetricsQueryDTO returns rows."""
        self._seed_regime_config("test-v1", is_active=1)
        self._seed_attribution(2, "2026-04-08")
        self._seed_attribution(3, "2026-04-09")
        query = FillMetricsQueryDTO(
            start_date_iso="2026-04-08",
            end_date_iso="2026-04-08",
        )
        df = self.read_repo.get_fill_metrics(query)
        self.assertEqual(len(df), 2)

    def test_get_attribution_metrics_empty(self):
        """Empty DB returns empty DataFrame."""
        self._seed_regime_config("test-v1", is_active=1)
        # Seed a config so get_fill_metrics can find an active config
        query = FillMetricsQueryDTO(
            start_date_iso="2026-04-08",
            end_date_iso="2026-04-09",
        )
        df = self.read_repo.get_fill_metrics(query)
        self.assertTrue(df.empty)

    def test_get_active_config_version(self):
        """Active config version query (reads audit_regime_config_versions)."""
        self._seed_regime_config("v1", is_active=1)
        self._seed_regime_config("v2", is_active=0)
        active = self.read_repo.get_active_config_version()
        self.assertEqual(active, "v1")

    def test_get_active_config_version_none(self):
        """No active config → returns None."""
        active = self.read_repo.get_active_config_version()
        self.assertIsNone(active)

    def test_get_active_config(self):
        """Active config DTO query (reads audit_attribution_config_versions)."""
        self._seed_attr_config("v1", is_active=1)
        config = self.read_repo.get_active_config()
        self.assertIsNotNone(config)
        self.assertEqual(config.version_id, "v1")

    def test_get_active_config_none(self):
        """No active config → returns None."""
        config = self.read_repo.get_active_config()
        self.assertIsNone(config)

    def test_get_regime_distribution(self):
        """Regime distribution query returns data."""
        self._seed_regime_config("test-v1", is_active=1)
        conn = self.mgr.get_admin_connection("regime")
        try:
            conn.execute("""
                INSERT INTO fill_regime_labels
                    (OrderId, RouteId, FillId, order_as_of_date_iso,
                     trade_date, config_version, market_code, vol_regime)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, ("ORD001", "RTE000", "FILL00001", "2026-04-08",
                  "2026-04-08", "test-v1", "US", "high_vol"))
            conn.commit()
        finally:
            conn.close()

        dist = self.read_repo.get_regime_distribution(
            "2026-04-08", "2026-04-08", regime_dim="vol_regime",
        )
        self.assertEqual(len(dist), 1)

    def test_get_regime_distribution_no_config(self):
        """No active config → empty distribution."""
        dist = self.read_repo.get_regime_distribution(
            "2026-04-08", "2026-04-08", regime_dim="vol_regime",
        )
        self.assertEqual(len(dist), 0)

    def test_get_regime_labels(self):
        """Regime labels query."""
        self._seed_regime_config("test-v1", is_active=1)
        conn = self.mgr.get_admin_connection("regime")
        try:
            conn.execute("""
                INSERT INTO fill_regime_labels
                    (OrderId, RouteId, FillId, order_as_of_date_iso,
                     trade_date, config_version, market_code, vol_regime)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, ("ORD001", "RTE000", "FILL00001", "2026-04-08",
                  "2026-04-08", "test-v1", "US", "high_vol"))
            conn.commit()
        finally:
            conn.close()

        labels = self.read_repo.get_regime_labels(
            "2026-04-08", "2026-04-08", "vol_regime",
        )
        self.assertFalse(labels.empty)
        self.assertIn("regime_value", labels.columns)

    def test_compute_snapshot_hash(self):
        """Snapshot hash computation returns non-empty hash."""
        self._seed_attribution(2, "2026-04-08")
        self._seed_regime_config("test-v1", is_active=1)
        h, total = self.read_repo.compute_snapshot_hash(
            "test-v1", "2026-04-08", "2026-04-08",
        )
        self.assertIsInstance(h, str)
        self.assertGreater(len(h), 0)
        self.assertEqual(total, 2)


class SqliteRegimeWriteRepositoryTest(unittest.TestCase):
    """Tests for regime write operations."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = create_temp_db("regime", self.tmp_dir.name)
        self.write_repo = SqliteRegimeWriteRepository(self.mgr)
        self.read_repo = SqliteRegimeReadRepository(self.mgr)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _seed_regime_config(self, version_id: str = "test-v1", is_active: int = 1):
        """Seed config into audit_regime_config_versions (used by read repo)."""
        conn = self.mgr.get_admin_connection("regime")
        try:
            conn.execute("""
                INSERT INTO audit_regime_config_versions
                    (version_id, description, parameters, is_active, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (version_id, "Test config", '{"key": "value"}', is_active,
                  datetime.now().isoformat()))
            conn.commit()
        finally:
            conn.close()

    def test_upsert_attribution_metrics(self):
        """Attribution metrics upserted correctly."""
        rows = _make_attribution_rows(2, "2026-04-08")
        count = self.write_repo.upsert_attribution_metrics(rows)
        self.assertEqual(count, 2)

        self._seed_regime_config("test-v1", is_active=1)
        query = FillMetricsQueryDTO(
            start_date_iso="2026-04-08",
            end_date_iso="2026-04-08",
        )
        result = self.read_repo.get_fill_metrics(query)
        self.assertEqual(len(result), 2)

    def test_upsert_empty_returns_zero(self):
        """Empty list → 0."""
        count = self.write_repo.upsert_attribution_metrics([])
        self.assertEqual(count, 0)

    def test_upsert_is_idempotent(self):
        """Same metrics upserted twice do not duplicate."""
        rows = _make_attribution_rows(2, "2026-04-08")
        self.write_repo.upsert_attribution_metrics(rows)
        self.write_repo.upsert_attribution_metrics(rows)

        self._seed_regime_config("test-v1", is_active=1)
        query = FillMetricsQueryDTO(
            start_date_iso="2026-04-08",
            end_date_iso="2026-04-08",
        )
        result = self.read_repo.get_fill_metrics(query)
        self.assertEqual(len(result), 2)

    def test_seed_default_config(self):
        """Config seeded and returns 'attr_v0'."""
        version = self.write_repo.seed_default_config()
        self.assertEqual(version, "attr_v0")

        # Verify via direct SQL (seed_default_config writes to
        # audit_attribution_config_versions, not audit_regime_config_versions)
        conn = self.mgr.get_admin_connection("regime")
        try:
            row = conn.execute(
                "SELECT version_id, is_active FROM audit_attribution_config_versions "
                "WHERE version_id=?", ("attr_v0",),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "attr_v0")
        self.assertEqual(row[1], 1)

    def test_seed_default_config_idempotent(self):
        """Seeding config twice does not create duplicates."""
        v1 = self.write_repo.seed_default_config()
        v2 = self.write_repo.seed_default_config()
        self.assertEqual(v1, v2)

    def test_insert_pipeline_run(self):
        """Pipeline run inserted with DTO."""
        run = PipelineRunDTO(
            stage_name="test_stage",
            run_started_at=datetime.now().isoformat(),
            status="running",
            target_start_date="2026-04-08",
            target_end_date="2026-04-08",
            config_version="v1",
            schema_version=3,
        )
        run_id = self.write_repo.insert_pipeline_run(run)
        self.assertIsInstance(run_id, int)
        self.assertGreater(run_id, 0)

    def test_update_pipeline_run(self):
        """Pipeline run updated with result DTO."""
        run = PipelineRunDTO(
            stage_name="test_stage",
            run_started_at=datetime.now().isoformat(),
            status="running",
            target_start_date="2026-04-08",
            target_end_date="2026-04-08",
            config_version="v1",
            schema_version=3,
        )
        run_id = self.write_repo.insert_pipeline_run(run)

        result = PipelineRunResultDTO(
            run_id=run_id,
            run_finished_at=datetime.now().isoformat(),
            status="completed",
            rows_written=100,
            rows_updated=0,
            error_message=None,
            duration_sec=42.5,
        )
        self.write_repo.update_pipeline_run(result)

        # Verify via direct SQL query
        conn = self.mgr.get_admin_connection("regime")
        try:
            row = conn.execute(
                "SELECT status, rows_written FROM audit_pipeline_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "completed")
        self.assertEqual(row[1], 100)

    def test_get_recommendations(self):
        """Recommender query works."""
        rows = _make_attribution_rows(5, "2026-04-08")
        self.write_repo.upsert_attribution_metrics(rows)
        self._seed_regime_config("test-v1", is_active=1)

        df = self.write_repo.get_recommendations(
            market="US", side=1, lo=0.0, hi=0.5,
            metric="is_bps", config_version="test-v1",
            params=["test-v1", "US", 1, 0.0, 0.5],
        )
        self.assertFalse(df.empty)
        self.assertIn("broker", df.columns)
        self.assertIn("algo", df.columns)

    def test_write_research_snapshot(self):
        """Research snapshot written correctly."""
        self.write_repo.write_research_snapshot(
            run_id=1,
            config_version="v1",
            start_date_iso="2026-04-08",
            end_date_iso="2026-04-08",
            rows_written=100,
            rows_total=200,
            snapshot_sha256="abc123",
            created_at=datetime.now().isoformat(),
        )
        conn = self.mgr.get_admin_connection("regime")
        try:
            row = conn.execute(
                "SELECT rows_written, rows_total FROM audit_research_snapshots WHERE run_id=?",
                (1,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], 100)
        self.assertEqual(row[1], 200)

    def test_upsert_regime_labels_delegation(self):
        """Regime labels delegation — _upsert_labels not available (known gap)."""
        df = pd.DataFrame([{
            "OrderId": "ORD001",
            "RouteId": "RTE000",
            "FillId": "FILL00001",
            "order_as_of_date_iso": "2026-04-08",
            "config_version": "test-v1",
            "market_code": "US",
            "vol_regime": "high_vol",
        }])
        # The write repo's upsert_regime_labels tries to import
        # CostView.src.regime.fill_regime_tagger._upsert_labels which
        # doesn't exist — this is a known codebase gap.
        with self.assertRaises(ImportError):
            self.write_repo.upsert_regime_labels(df)

"""Tests for SqliteFillReadRepository and SqliteFillWriteRepository.

Uses real SQLite databases in temp directories to verify round-trip
read/write operations, idempotency, edge cases, and query correctness.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from DataPipeline.storage.repositories.fills import SqliteFillReadRepository
from DataPipeline.storage.repositories.fills import SqliteFillWriteRepository
from CostView.tests.testing_helpers import (
    create_temp_db,
    make_fills_dataframe,
)


class SqliteFillReadRepositoryTest(unittest.TestCase):
    """Tests for fill read operations."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = create_temp_db("processed_fills", self.tmp_dir.name)
        self.read_repo = SqliteFillReadRepository(self.mgr)
        self.write_repo = SqliteFillWriteRepository(self.mgr)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _seed_data(self, date_str: str = "20260408", num_rows: int = 5):
        df = make_fills_dataframe(num_rows=num_rows, date_str=date_str)
        self.write_repo.upsert_processed_fills(df)
        return df

    def test_read_returns_empty_for_missing_date(self):
        """Querying a non-existent date returns an empty DataFrame."""
        df = self.read_repo.get_fills_for_date("20990101")
        self.assertTrue(df.empty)

    def test_write_and_read_roundtrip(self):
        """Upsert fills then read them back — same row count."""
        seeded = self._seed_data("20260408", 5)
        result = self.read_repo.get_fills_for_date("20260408")
        self.assertEqual(len(result), 5)
        self.assertIn("OrderId", result.columns)

    def test_upsert_is_idempotent(self):
        """Upserting the same data twice does not duplicate rows."""
        self._seed_data("20260408", 3)
        df = make_fills_dataframe(num_rows=3, date_str="20260408")
        second_count = self.write_repo.upsert_processed_fills(df)
        result = self.read_repo.get_fills_for_date("20260408")
        # With INSERT OR REPLACE, second upsert returns row count but
        # does not add new rows—same 3 rows
        self.assertEqual(len(result), 3)

    def test_get_distinct_dates_in_range(self):
        """Multiple dates → distinct date list filtered by range."""
        self._seed_data("20260408", 2)
        self._seed_data("20260409", 3)
        self._seed_data("20260410", 1)

        dates = self.read_repo.get_distinct_dates_in_range("20260408", "20260409")
        self.assertIn("20260408", dates)
        self.assertIn("20260409", dates)
        self.assertNotIn("20260410", dates)

    def test_get_processed_dates(self):
        """Processing log entries → correct stage dates returned."""
        conn = self.mgr.get_admin_connection("processed_fills")
        try:
            conn.execute(
                "INSERT INTO processing_log (order_as_of_date, row_count, stage) "
                "VALUES (?, ?, ?)",
                ("20260408", 10, "processed"),
            )
            conn.execute(
                "INSERT INTO processing_log (order_as_of_date, row_count, stage) "
                "VALUES (?, ?, ?)",
                ("20260409", 20, "processed"),
            )
            conn.commit()
        finally:
            conn.close()

        dates = self.read_repo.get_processed_dates(stage="processed")
        self.assertIn("20260408", dates)
        self.assertIn("20260409", dates)

    def test_get_unprocessed_dates(self):
        """Only dates NOT in processing_log are returned."""
        conn = self.mgr.get_admin_connection("processed_fills")
        try:
            conn.execute(
                "INSERT INTO processing_log (order_as_of_date, row_count, stage) "
                "VALUES (?, ?, ?)",
                ("20260408", 10, "processed"),
            )
            conn.commit()
        finally:
            conn.close()

        unprocessed = self.read_repo.get_unprocessed_dates(
            ["20260408", "20260409", "20260410"], stage="processed",
        )
        self.assertNotIn("20260408", unprocessed)
        self.assertIn("20260409", unprocessed)
        self.assertIn("20260410", unprocessed)

    def test_get_ticker_exchange_map(self):
        """Ticker repository → correct mapping returned."""
        conn = self.mgr.get_admin_connection("processed_fills")
        try:
            conn.execute(
                "INSERT INTO ticker_repository (equ_ticker, exchange) VALUES (?, ?)",
                ("AAPL US Equity", "US"),
            )
            conn.execute(
                "INSERT INTO ticker_repository (equ_ticker, exchange) VALUES (?, ?)",
                ("1CO GR Equity", "GR"),
            )
            conn.commit()
        finally:
            conn.close()

        mapping = self.read_repo.get_ticker_exchange_map()
        self.assertEqual(mapping.get("AAPL US Equity"), "US")
        self.assertEqual(mapping.get("1CO GR Equity"), "GR")

    def test_get_ticker_exchange_map_filtered(self):
        """Exchange filter restricts results."""
        conn = self.mgr.get_admin_connection("processed_fills")
        try:
            conn.execute(
                "INSERT INTO ticker_repository (equ_ticker, exchange) VALUES (?, ?)",
                ("AAPL US Equity", "US"),
            )
            conn.execute(
                "INSERT INTO ticker_repository (equ_ticker, exchange) VALUES (?, ?)",
                ("1CO GR Equity", "GR"),
            )
            conn.commit()
        finally:
            conn.close()

        mapping = self.read_repo.get_ticker_exchange_map(exchanges=["US"])
        self.assertIn("AAPL US Equity", mapping)
        self.assertNotIn("1CO GR Equity", mapping)

    def test_get_agg_fills_10s_for_date(self):
        """Aggregated 10s fills query returns correct rows."""
        conn = self.mgr.get_admin_connection("processed_fills")
        try:
            conn.execute("""
                INSERT INTO agg_fills_10s (OrderId, RouteId, mkt_timestamp, order_as_of_date,
                    FillPrice, FillShares)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("ORD001", "RTE000", "09:30:00", "20260408", 100.0, 100))
            conn.commit()
        finally:
            conn.close()

        df = self.read_repo.get_agg_fills_10s_for_date("20260408")
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["OrderId"], "ORD001")


class SqliteFillWriteRepositoryTest(unittest.TestCase):
    """Tests for fill write operations."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = create_temp_db("processed_fills", self.tmp_dir.name)
        self.write_repo = SqliteFillWriteRepository(self.mgr)
        self.read_repo = SqliteFillReadRepository(self.mgr)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_upsert_empty_returns_zero(self):
        """Upserting an empty DataFrame returns 0."""
        result = self.write_repo.upsert_processed_fills(pd.DataFrame())
        self.assertEqual(result, 0)

    def test_upsert_order_labels(self):
        """Order labels are upserted and readable."""
        labels = pd.DataFrame({
            "OrderId": ["ORD001", "ORD002"],
            "order_as_of_date": ["20260408", "20260408"],
        })
        count = self.write_repo.upsert_order_labels(labels)
        self.assertEqual(count, 2)

        read_back = self.read_repo.get_order_labels()
        self.assertEqual(len(read_back), 2)

    def test_upsert_agg_fills_10s(self):
        """Aggregated fills are upserted correctly."""
        agg = pd.DataFrame({
            "OrderId": ["ORD001"],
            "RouteId": ["RTE000"],
            "mkt_timestamp": ["09:30:00"],
            "order_as_of_date": ["20260408"],
            "FillPrice": [100.0],
            "FillShares": [100],
        })
        count = self.write_repo.upsert_agg_fills_10s(agg)
        self.assertEqual(count, 1)

    def test_mark_date_processed(self):
        """Processing log entries are created."""
        self.write_repo.mark_date_processed("20260408", stage="processed", row_count=10)
        dates = self.read_repo.get_processed_dates(stage="processed")
        self.assertIn("20260408", dates)

    def test_write_with_explicit_conn(self):
        """External connection can be passed to upsert."""
        df = make_fills_dataframe(num_rows=2, date_str="20260408")
        conn = self.mgr.get_admin_connection("processed_fills")
        try:
            count = self.write_repo.upsert_processed_fills(df, conn=conn)
            conn.commit()
        finally:
            conn.close()

        result = self.read_repo.get_fills_for_date("20260408")
        self.assertEqual(len(result), 2)

"""Tests for SqliteRawFillReadRepository and SqliteRawFillWriteRepository.

Uses real SQLite databases in temp directories.
"""

from __future__ import annotations

import tempfile
import unittest

import pandas as pd

from DataPipeline.src.storage.repositories.raw_fills_read import SqliteRawFillReadRepository
from DataPipeline.src.storage.repositories.raw_fills_write import SqliteRawFillWriteRepository
from CostView.tests.testing_helpers import create_temp_db


class SqliteRawFillReadRepositoryTest(unittest.TestCase):
    """Tests for raw fill read operations."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = create_temp_db("raw_fills", self.tmp_dir.name)
        self.read_repo = SqliteRawFillReadRepository(self.mgr)
        self.write_repo = SqliteRawFillWriteRepository(self.mgr)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _insert_raw_row(self, date_str: str, order_id: str = "ORD001",
                        route_id: str = "RTE000", fill_id: str = "FILL00001"):
        conn = self.mgr.get_admin_connection("raw_fills")
        try:
            conn.execute("""
                INSERT INTO raw_fills (OrderId, RouteId, FillId, source_date,
                    Ticker, Exchange, Side, ExecType, FillPrice, FillShares)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, route_id, fill_id, date_str,
                  "AAPL", "US", "BUY", "FILL", "100.0", "100"))
            conn.commit()
        finally:
            conn.close()

    def _insert_unique_row(self, date_str: str, idx: int):
        """Insert a row with unique PK to avoid integrity errors."""
        self._insert_raw_row(date_str,
                             order_id=f"ORD{idx:03d}",
                             route_id=f"RTE{idx:03d}",
                             fill_id=f"FILL{idx:05d}")

    def _insert_fetch_log(self, date_str: str):
        conn = self.mgr.get_admin_connection("raw_fills")
        try:
            conn.execute("""
                INSERT INTO fetch_log (source_date, row_count, data_hash, status)
                VALUES (?, ?, ?, ?)
            """, (date_str, 10, "abc123", "fetched"))
            conn.commit()
        finally:
            conn.close()

    def test_get_fills_for_source_date(self):
        """Query by source_date returns matching rows."""
        self._insert_raw_row("20260408")
        df = self.read_repo.get_fills_for_source_date("20260408")
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["OrderId"], "ORD001")

    def test_get_fills_for_source_date_empty(self):
        """Non-existent source_date returns empty DataFrame."""
        df = self.read_repo.get_fills_for_source_date("20990101")
        self.assertTrue(df.empty)

    def test_get_fills_for_date_fallback(self):
        """order_as_of_date not present → fallback to source_date."""
        self._insert_raw_row("20260408")
        df = self.read_repo.get_fills_for_date("20260408")
        self.assertEqual(len(df), 1)

    def test_get_all_source_dates(self):
        """Multiple source_dates returned sorted."""
        self._insert_unique_row("20260408", 1)
        self._insert_unique_row("20260409", 2)
        self._insert_unique_row("20260410", 3)
        dates = self.read_repo.get_all_source_dates()
        self.assertEqual(dates, ["20260408", "20260409", "20260410"])

    def test_get_row_count(self):
        """COUNT(*) returns correct total."""
        self._insert_raw_row("20260408")
        self._insert_raw_row("20260409", order_id="ORD002")
        self.assertEqual(self.read_repo.get_row_count(), 2)

    def test_get_date_row_counts(self):
        """Row counts grouped by source_date."""
        self._insert_unique_row("20260408", 1)
        self._insert_unique_row("20260408", 2)
        self._insert_unique_row("20260409", 3)
        counts = self.read_repo.get_date_row_counts()
        self.assertEqual(counts.get("20260408"), 2)
        self.assertEqual(counts.get("20260409"), 1)

    def test_get_fetch_log_stats(self):
        """Fetch log query returns stats."""
        self._insert_fetch_log("20260408")
        stats = self.read_repo.get_fetch_log_stats()
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["source_date"], "20260408")


class SqliteRawFillWriteRepositoryTest(unittest.TestCase):
    """Tests for raw fill write operations."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = create_temp_db("raw_fills", self.tmp_dir.name)
        self.write_repo = SqliteRawFillWriteRepository(self.mgr)
        self.read_repo = SqliteRawFillReadRepository(self.mgr)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_upsert_raw_api_data(self):
        """API format data is upserted correctly."""
        fills = [
            {
                "OrderId": "ORD001",
                "RouteId": "RTE000",
                "FillId": "FILL00001",
                "Ticker": "AAPL",
                "ExecType": "FILL",
                "FillPrice": "100.0",
                "FillShares": "100",
            },
        ]
        count = self.write_repo.upsert_raw_api_data(fills, source_date="20260408")
        self.assertEqual(count, 1)

        df = self.read_repo.get_fills_for_source_date("20260408")
        self.assertEqual(len(df), 1)

    def test_upsert_fills_from_dataframe(self):
        """DataFrame fills are upserted."""
        df = pd.DataFrame([{
            "OrderId": "ORD001",
            "RouteId": "RTE000",
            "FillId": "FILL00001",
            "Ticker": "AAPL",
            "Exchange": "US",
            "Side": "BUY",
            "ExecType": "FILL",
            "FillPrice": "100.0",
            "FillShares": "100",
            "source_date": "20260408",
        }])
        count = self.write_repo.upsert_fills(df)
        self.assertEqual(count, 1)

    def test_upsert_raw_api_empty_returns_zero(self):
        """No data → returns 0."""
        count = self.write_repo.upsert_raw_api_data([], source_date="20260408")
        self.assertEqual(count, 0)

    def test_upsert_fills_empty_returns_zero(self):
        """Empty DataFrame → returns 0."""
        count = self.write_repo.upsert_fills(pd.DataFrame())
        self.assertEqual(count, 0)

    def test_upsert_idempotent_same_data(self):
        """Same data upserted twice does not increase row count."""
        fills = [{"OrderId": "ORD001", "RouteId": "RTE000", "FillId": "FILL00001",
                   "Ticker": "AAPL", "ExecType": "FILL"}]
        self.write_repo.upsert_raw_api_data(fills, source_date="20260408")
        self.write_repo.upsert_raw_api_data(fills, source_date="20260408")

        df = self.read_repo.get_fills_for_source_date("20260408")
        self.assertEqual(len(df), 1)

    def test_upsert_raw_api_column_mapping(self):
        """Verify column mapping preserves all EMSX fields."""
        fills = [
            {
                "OrderId": "ORD001",
                "RouteId": "RTE000",
                "FillId": "FILL00001",
                "Ticker": "AAPL",
                "Exchange": "US",
                "Side": "BUY",
                "ExecType": "FILL",
                "FillPrice": "100.50",
                "FillShares": "200",
            },
        ]
        self.write_repo.upsert_raw_api_data(fills, source_date="20260408")
        df = self.read_repo.get_fills_for_source_date("20260408")
        self.assertEqual(df.iloc[0]["Ticker"], "AAPL")
        self.assertEqual(df.iloc[0]["FillPrice"], "100.50")
        self.assertEqual(df.iloc[0]["FillShares"], "200")

"""Tests for SqliteIntegratedReadRepository and SqliteIntegratedWriteRepository.

Uses real SQLite databases in temp directories.
"""

from __future__ import annotations

import tempfile
import unittest

import pandas as pd

from DataPipeline.storage.repositories.integrated import (
    SqliteIntegratedReadRepository,
    SqliteIntegratedWriteRepository,
)
from CostView.tests.testing_helpers import create_temp_db, make_integrated_dataframe


class SqliteIntegratedReadRepositoryTest(unittest.TestCase):
    """Tests for integrated data read operations."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = create_temp_db("fill_bdib", self.tmp_dir.name)
        self.read_repo = SqliteIntegratedReadRepository(self.mgr)
        self.write_repo = SqliteIntegratedWriteRepository(self.mgr)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _seed_data(self, date_str: str = "20260408", num_rows: int = 3):
        df = make_integrated_dataframe(num_rows=num_rows, date_str=date_str)
        self.write_repo.upsert_integrated_data(df, date_str=date_str)
        return df

    def test_get_integrated_data_for_date(self):
        """Query by date returns integrated rows."""
        self._seed_data("20260408", 3)
        df = self.read_repo.get_integrated_data_for_date("20260408")
        self.assertEqual(len(df), 3)
        self.assertIn("OrderId", df.columns)

    def test_get_integrated_data_for_date_empty(self):
        """Non-existent date returns empty DataFrame."""
        df = self.read_repo.get_integrated_data_for_date("20990101")
        self.assertTrue(df.empty)

    def test_get_row_count(self):
        """Total row count."""
        self._seed_data("20260408", 2)
        self._seed_data("20260409", 3)
        self.assertEqual(self.read_repo.get_row_count(), 5)

    def test_get_empty_db_returns_empty(self):
        """Empty database returns empty DataFrame for any query."""
        df = self.read_repo.get_integrated_data_for_date("20260408")
        self.assertTrue(df.empty)


class SqliteIntegratedWriteRepositoryTest(unittest.TestCase):
    """Tests for integrated data write operations."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = create_temp_db("fill_bdib", self.tmp_dir.name)
        self.write_repo = SqliteIntegratedWriteRepository(self.mgr)
        self.read_repo = SqliteIntegratedReadRepository(self.mgr)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_upsert_integrated_data(self):
        """Integrated data upserted and readable."""
        df = make_integrated_dataframe(2, "20260408")
        count = self.write_repo.upsert_integrated_data(df, date_str="20260408")
        self.assertEqual(count, 2)

        result = self.read_repo.get_integrated_data_for_date("20260408")
        self.assertEqual(len(result), 2)

    def test_upsert_empty_returns_zero(self):
        """Empty DataFrame → 0."""
        count = self.write_repo.upsert_integrated_data(pd.DataFrame())
        self.assertEqual(count, 0)

    def test_upsert_none_returns_zero(self):
        """None input → 0."""
        count = self.write_repo.upsert_integrated_data(None)
        self.assertEqual(count, 0)

    def test_upsert_integrated_idempotent(self):
        """Multiple upserts of same data don't duplicate rows."""
        df = make_integrated_dataframe(2, "20260408")
        self.write_repo.upsert_integrated_data(df, date_str="20260408")
        self.write_repo.upsert_integrated_data(df, date_str="20260408")

        result = self.read_repo.get_integrated_data_for_date("20260408")
        self.assertEqual(len(result), 2)

    def test_upsert_with_date_in_dataframe(self):
        """DataFrame already has order_as_of_date column."""
        df = make_integrated_dataframe(3, "20260408")
        count = self.write_repo.upsert_integrated_data(df)
        self.assertEqual(count, 3)

        result = self.read_repo.get_integrated_data_for_date("20260408")
        self.assertEqual(len(result), 3)

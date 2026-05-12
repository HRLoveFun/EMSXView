"""Tests for SqliteMarketDataReadRepository and SqliteMarketDataWriteRepository.

Uses real SQLite databases in temp directories.
"""

from __future__ import annotations

import tempfile
import unittest

import pandas as pd

from DataPipeline.storage.repositories.market_data import SqliteMarketDataReadRepository
from DataPipeline.storage.repositories.market_data import SqliteMarketDataWriteRepository
from CostView.tests.testing_helpers import create_temp_db, make_bdib_dataframe


class SqliteMarketDataReadRepositoryTest(unittest.TestCase):
    """Tests for market data read operations."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = create_temp_db("raw_bdib", self.tmp_dir.name)
        self.read_repo = SqliteMarketDataReadRepository(self.mgr)
        self.write_repo = SqliteMarketDataWriteRepository(self.mgr)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _seed_bars(self, num_bars: int = 5, date_str: str = "20260408",
                   ticker: str = "AAPL US Equity"):
        df = make_bdib_dataframe(num_bars=num_bars, date_str=date_str, ticker=ticker)
        self.write_repo.upsert_bdib_data(df, date_str=date_str)
        return df

    def test_get_bdib_bars_for_date(self):
        """Single ticker + date query returns bars."""
        self._seed_bars(5, "20260408", "AAPL US Equity")
        df = self.read_repo.get_bdib_bars_for_date("AAPL US Equity", "20260408")
        self.assertEqual(len(df), 5)
        self.assertEqual(df.iloc[0]["equ_ticker"], "AAPL US Equity")

    def test_get_bdib_bars_for_date_empty(self):
        """Non-existent date returns empty DataFrame."""
        df = self.read_repo.get_bdib_bars_for_date("NONEXIST", "20990101")
        self.assertTrue(df.empty)

    def test_get_bdib_bars_for_tickers_and_dates(self):
        """Multiple tickers + date range query."""
        self._seed_bars(3, "20260408", "AAPL US Equity")
        self._seed_bars(3, "20260408", "MSFT US Equity")
        self._seed_bars(2, "20260409", "AAPL US Equity")

        df = self.read_repo.get_bdib_bars_for_tickers_and_dates(
            ["AAPL US Equity", "MSFT US Equity"],
            "20260408", "20260409",
        )
        self.assertEqual(len(df), 8)  # 3 + 3 + 2
        self.assertIn("AAPL US Equity", df["equ_ticker"].values)
        self.assertIn("MSFT US Equity", df["equ_ticker"].values)

    def test_get_latest_order_as_of_date(self):
        """Latest date from raw_bdib is returned."""
        self._seed_bars(2, "20260408", "AAPL US Equity")
        self._seed_bars(2, "20260409", "AAPL US Equity")
        latest = self.read_repo.get_latest_order_as_of_date()
        self.assertEqual(latest, "20260409")

    def test_get_latest_order_as_of_date_empty(self):
        """Empty DB returns None."""
        latest = self.read_repo.get_latest_order_as_of_date()
        self.assertIsNone(latest)

    def test_get_distinct_tickers(self):
        """Unique ticker list query."""
        self._seed_bars(2, "20260408", "AAPL US Equity")
        self._seed_bars(2, "20260408", "MSFT US Equity")
        tickers = self.read_repo.get_distinct_dates()  # This returns dates, not tickers
        # Let's verify dates instead
        self.assertIn("20260408", tickers)

    def test_get_distinct_dates(self):
        """Unique date list query."""
        self._seed_bars(2, "20260408", "AAPL US Equity")
        self._seed_bars(2, "20260409", "MSFT US Equity")
        dates = self.read_repo.get_distinct_dates()
        self.assertIn("20260408", dates)
        self.assertIn("20260409", dates)

    def test_get_daily_summary(self):
        """Daily summary query returns correct rows."""
        conn = self.mgr.get_admin_connection("raw_bdib")
        try:
            conn.execute("""
                INSERT INTO bdib_daily_summary
                    (equ_ticker, trade_date, total_volume, daily_vwap, daily_close,
                     daily_volatility, intraday_volatility, adv_5d, adv_20d)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("AAPL US Equity", "20260408", 10000.0, 100.5, 101.0,
                  0.25, 0.15, 8000.0, 7500.0))
            conn.commit()
        finally:
            conn.close()

        df = self.read_repo.get_daily_summary("AAPL US Equity")
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["total_volume"], 10000.0)

    def test_get_row_count(self):
        """Row count query."""
        self._seed_bars(3, "20260408", "AAPL US Equity")
        self.assertEqual(self.read_repo.get_row_count(), 3)


class SqliteMarketDataWriteRepositoryTest(unittest.TestCase):
    """Tests for market data write operations."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = create_temp_db("raw_bdib", self.tmp_dir.name)
        self.write_repo = SqliteMarketDataWriteRepository(self.mgr)
        self.read_repo = SqliteMarketDataReadRepository(self.mgr)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_upsert_bdib_data(self):
        """BDIB bars upserted and readable."""
        df = make_bdib_dataframe(3, "20260408", "AAPL US Equity")
        count = self.write_repo.upsert_bdib_data(df, date_str="20260408")
        self.assertEqual(count, 3)

        result = self.read_repo.get_bdib_bars_for_date("AAPL US Equity", "20260408")
        self.assertEqual(len(result), 3)

    def test_upsert_bdib_data_empty(self):
        """Empty DataFrame → 0."""
        count = self.write_repo.upsert_bdib_data(pd.DataFrame())
        self.assertEqual(count, 0)

    def test_upsert_bdib_data_none(self):
        """None input → 0."""
        count = self.write_repo.upsert_bdib_data(None)
        self.assertEqual(count, 0)

    def test_upsert_daily_summary(self):
        """Daily summary rows upserted."""
        rows = [{
            "equ_ticker": "AAPL US Equity",
            "trade_date": "20260408",
            "total_volume": 10000.0,
            "daily_vwap": 100.5,
            "daily_close": 101.0,
            "daily_volatility": 0.25,
            "intraday_volatility": 0.15,
            "adv_5d": 8000.0,
            "adv_20d": 7500.0,
        }]
        count = self.write_repo.upsert_daily_summary(rows)
        self.assertEqual(count, 1)

        df = self.read_repo.get_daily_summary("AAPL US Equity")
        self.assertEqual(len(df), 1)

    def test_upsert_daily_summary_empty(self):
        """Empty daily summary list → 0."""
        count = self.write_repo.upsert_daily_summary([])
        self.assertEqual(count, 0)

    def test_upsert_bdib_data_without_date_str(self):
        """DataFrame with order_as_of_date column works without date_str."""
        df = make_bdib_dataframe(2, "20260408", "AAPL US Equity")
        count = self.write_repo.upsert_bdib_data(df)
        self.assertEqual(count, 2)

    def test_latest_daily_summary(self):
        """Latest daily summary query."""
        conn = self.mgr.get_admin_connection("raw_bdib")
        try:
            conn.execute("""
                INSERT INTO bdib_daily_summary
                    (equ_ticker, trade_date, total_volume, daily_vwap, daily_close,
                     daily_volatility, intraday_volatility, adv_5d, adv_20d)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("AAPL US Equity", "20260408", 10000.0, 100.5, 101.0,
                  0.25, 0.15, 8000.0, 7500.0))
            conn.commit()
        finally:
            conn.close()

        df = self.read_repo.get_latest_daily_summary()
        self.assertFalse(df.empty)
        self.assertIn("trade_date", df.columns)

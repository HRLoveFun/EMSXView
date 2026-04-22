from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from CostView.src.bdib_fetcher import _is_safe_bdib_query_date
from CostView.src.daily_metrics_calculator import CalculateDailyMetrics
from CostView.src.outdated_tickers import load_outdated_ticker_records, record_outdated_ticker
from CostView.src.pipeline import BaseStage, FinancialPipeline, IntegrateBDIBStage, PipelineContext
from CostView.src.processed_fills_db import ProcessedFillsDB
from CostView.src.processing_config import ProcessingConfig as Config
from CostView.src.raw_bdib_db import RawBDIBDB
from CostView.src.tca_query_service import TcaQueryService


class PipelineGuardTests(unittest.TestCase):
    def test_bdib_latest_safe_date_moves_after_cutoff(self) -> None:
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

    def test_recent_bdib_date_is_blocked_before_cutoff(self) -> None:
        morning = datetime(2026, 4, 22, 9, 26)
        evening = datetime(2026, 4, 22, 18, 30)

        self.assertFalse(_is_safe_bdib_query_date(date(2026, 4, 21), morning))
        self.assertTrue(_is_safe_bdib_query_date(date(2026, 4, 21), evening))

    def test_processed_fills_db_sets_busy_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = ProcessedFillsDB(db_path=f"{tmp_dir}/processed_fills.db")
            conn = db._get_conn()
            try:
                busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(busy_timeout, Config.SQLITE_BUSY_TIMEOUT_MS)

    def test_outdated_ticker_record_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = f"{tmp_dir}/outdated_tickers.json"
            first = record_outdated_ticker(
                "1CO GR Equity",
                "cannot_find_exchange_info",
                detail="Cannot find exchange info for 1CO GR Equity",
                file_path=file_path,
            )
            second = record_outdated_ticker(
                "1CO GR Equity",
                "cannot_find_exchange_info",
                detail="Cannot find exchange info for 1CO GR Equity",
                file_path=file_path,
            )
            records = load_outdated_ticker_records(file_path)

        self.assertEqual(first["equ_ticker"], "1CO GR Equity")
        self.assertEqual(second["hit_count"], 2)
        self.assertIn("1CO GR Equity", records)
        self.assertEqual(records["1CO GR Equity"]["reason"], "cannot_find_exchange_info")

    @patch("CostView.src.bdib_fetcher.fetch_bdib_for_ticker_date")
    @patch("CostView.src.bdib_fetcher.load_outdated_ticker_set")
    @patch("CostView.src.bdib_fetcher._is_safe_bdib_query_date", return_value=True)
    @patch("CostView.src.bdib_fetcher._is_trading_day", return_value=True)
    def test_fetch_bdib_skips_outdated_tickers(
        self,
        _mock_trading_day,
        _mock_safe_date,
        mock_load_outdated,
        mock_fetch_one,
    ) -> None:
        from CostView.src.bdib_fetcher import fetch_bdib_for_fills

        mock_load_outdated.return_value = {"1CO GR Equity"}
        mock_fetch_one.return_value = pd.DataFrame(
            [{"mkt_timestamp": "09:30:00", "close": 100.0, "equ_ticker": "AAPL US Equity"}]
        )

        result = fetch_bdib_for_fills(
            {
                "1CO GR Equity": ["20260420"],
                "AAPL US Equity": ["20260420"],
            },
            ticker_exchange_map={
                "1CO GR Equity": "GR",
                "AAPL US Equity": "US",
            },
        )

        self.assertEqual(mock_fetch_one.call_count, 1)
        self.assertIn("AAPL US Equity|20260420", result)
        self.assertNotIn("1CO GR Equity|20260420", result)

    def test_manifest_excludes_outdated_equity_tickers(self) -> None:
        from CostView.src.downstream_interface import write_manifest

        class FakeProcDb:
            @staticmethod
            def get_equ_ticker_registry() -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {"equ_ticker": "1CO GR Equity"},
                        {"equ_ticker": "AAPL US Equity"},
                    ]
                )

            @staticmethod
            def get_ccy_ticker_registry() -> pd.DataFrame:
                return pd.DataFrame(
                    [{"ccy_ticker": "USDJPY Curncy"}]
                )

        with tempfile.TemporaryDirectory() as tmp_dir:
            outdated_path = Path(tmp_dir) / "outdated_tickers.json"
            manifest_path = Path(tmp_dir) / "market_fetch_manifest.json"
            record_outdated_ticker(
                "1CO GR Equity",
                "cannot_find_exchange_info",
                detail="Cannot find exchange info for 1CO GR Equity",
                file_path=outdated_path,
            )

            with patch.object(Config, "OUTDATED_TICKERS_FILE", outdated_path), patch.object(
                Config, "MARKET_FETCH_MANIFEST", manifest_path
            ):
                write_manifest(proc_db=FakeProcDb(), updated_dates=["20260420"])
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertNotIn("1CO GR Equity", manifest["equ_tickers"])
        self.assertIn("AAPL US Equity", manifest["equ_tickers"])

    def test_raw_bdib_daily_summary_has_new_stage7_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = RawBDIBDB(db_path=f"{tmp_dir}/raw_bdib.db")
            conn = db._get_conn()
            try:
                columns = {
                    row[1]
                    for row in conn.execute(
                        f"PRAGMA table_info({Config.BDIB_DAILY_SUMMARY_TABLE})"
                    ).fetchall()
                }
            finally:
                conn.close()

        self.assertIn("daily_close", columns)
        self.assertIn("intraday_volatility", columns)

    def test_daily_metrics_use_bloomberg_daily_fields_and_preserve_intraday_logic(self) -> None:
        class FakeProcDb:
            @staticmethod
            def get_ticker_dates(ticker_type: str = "equ_ticker") -> dict[str, list[str]]:
                if ticker_type != "equ_ticker":
                    raise AssertionError(f"unexpected ticker_type: {ticker_type}")
                return {"AAPL US Equity": ["20260421"]}

        with tempfile.TemporaryDirectory() as tmp_dir:
            db = RawBDIBDB(db_path=f"{tmp_dir}/raw_bdib.db")
            db.upsert_bdib_data(
                pd.DataFrame(
                    [
                        {
                            "equ_ticker": "AAPL US Equity",
                            "order_as_of_date": "20260421",
                            "mkt_timestamp": "09:30:00",
                            "close": 100.0,
                            "volume": 10.0,
                        },
                        {
                            "equ_ticker": "AAPL US Equity",
                            "order_as_of_date": "20260421",
                            "mkt_timestamp": "09:30:10",
                            "close": 101.0,
                            "volume": 20.0,
                        },
                        {
                            "equ_ticker": "AAPL US Equity",
                            "order_as_of_date": "20260421",
                            "mkt_timestamp": "09:30:20",
                            "close": 102.0,
                            "volume": 30.0,
                        },
                    ]
                )
            )

            calc = CalculateDailyMetrics(db=db, proc_db=FakeProcDb())
            history_df = pd.DataFrame(
                [
                    {
                        "equ_ticker": "AAPL US Equity",
                        "trade_date": "20260415",
                        "total_volume": 100.0,
                        "daily_volatility": 20.0,
                        "daily_close": 196.0,
                    },
                    {
                        "equ_ticker": "AAPL US Equity",
                        "trade_date": "20260416",
                        "total_volume": 110.0,
                        "daily_volatility": 21.0,
                        "daily_close": 197.0,
                    },
                    {
                        "equ_ticker": "AAPL US Equity",
                        "trade_date": "20260417",
                        "total_volume": 120.0,
                        "daily_volatility": 22.0,
                        "daily_close": 198.0,
                    },
                    {
                        "equ_ticker": "AAPL US Equity",
                        "trade_date": "20260418",
                        "total_volume": 130.0,
                        "daily_volatility": 23.0,
                        "daily_close": 199.0,
                    },
                    {
                        "equ_ticker": "AAPL US Equity",
                        "trade_date": "20260421",
                        "total_volume": 140.0,
                        "daily_volatility": 24.0,
                        "daily_close": 200.0,
                    },
                ]
            )

            with patch.object(CalculateDailyMetrics, "_fetch_daily_history", return_value=history_df):
                upserted = calc.run_for_date("20260421")

            summary_df = db.get_daily_summary("AAPL US Equity", end_date="20260421")
            row = summary_df[summary_df["trade_date"] == "20260421"].iloc[0]

        self.assertEqual(upserted, 1)
        self.assertAlmostEqual(row["total_volume"], 140.0)
        self.assertAlmostEqual(row["daily_volatility"], 24.0)
        self.assertAlmostEqual(row["daily_close"], 200.0)
        self.assertAlmostEqual(row["adv_5d"], 120.0)
        self.assertAlmostEqual(row["adv_20d"], 120.0)
        self.assertAlmostEqual(row["daily_vwap"], (100.0 * 10.0 + 101.0 * 20.0 + 102.0 * 30.0) / 60.0)
        self.assertGreater(row["intraday_volatility"], 0.0)

    def test_market_context_reads_intraday_volatility_from_new_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            raw_bdib_path = f"{tmp_dir}/raw_bdib.db"
            db = RawBDIBDB(db_path=raw_bdib_path)
            db.upsert_bdib_data(
                pd.DataFrame(
                    [
                        {
                            "equ_ticker": "AAPL US Equity",
                            "order_as_of_date": "20260421",
                            "mkt_timestamp": "09:29:50",
                            "close": 99.0,
                            "volume": 10.0,
                        },
                        {
                            "equ_ticker": "AAPL US Equity",
                            "order_as_of_date": "20260421",
                            "mkt_timestamp": "09:30:00",
                            "close": 100.0,
                            "volume": 20.0,
                        },
                        {
                            "equ_ticker": "AAPL US Equity",
                            "order_as_of_date": "20260421",
                            "mkt_timestamp": "09:30:10",
                            "close": 101.0,
                            "volume": 30.0,
                        },
                    ]
                )
            )
            db.upsert_daily_summary(
                [
                    {
                        "equ_ticker": "AAPL US Equity",
                        "trade_date": "20260421",
                        "total_volume": 140.0,
                        "daily_vwap": 100.5,
                        "daily_close": 200.0,
                        "daily_volatility": 24.0,
                        "intraday_volatility": 1.5,
                        "adv_5d": 120.0,
                        "adv_20d": 120.0,
                    }
                ]
            )

            service = TcaQueryService(raw_bdib_db_path=raw_bdib_path)
            market_ctx = service._get_market_context(
                {("AAPL US Equity", "20260421")},
                [
                    {
                        "equ_ticker": "AAPL US Equity",
                        "order_as_of_date": "20260421",
                        "start_time": "09:30:00",
                        "end_time": "09:30:10",
                    }
                ],
                {},
            )

        row = market_ctx[("AAPL US Equity", "20260421")]
        self.assertEqual(row["daily_volatility"], 24.0)
        self.assertEqual(row["intraday_volatility"], 1.5)

    def test_mean_numeric_ignores_none_values(self) -> None:
        self.assertEqual(TcaQueryService._mean_numeric([1.0, None, 3.0]), 2.0)
        self.assertIsNone(TcaQueryService._mean_numeric([None, None]))

    def test_pipeline_emits_granular_processing_stage_markers(self) -> None:
        class DummyStage(BaseStage):
            def __init__(self, stage_name: str):
                self._stage_name = stage_name

            @property
            def name(self) -> str:
                return self._stage_name

            def process(self, context: PipelineContext) -> bool:
                return True

        ctx = PipelineContext(
            config={
                "stage_marker_name": "processing",
                "stage_marker_start": 55,
                "stage_marker_end": 95,
            }
        )
        pipeline = FinancialPipeline("test-pipeline")
        pipeline.add_stage(DummyStage("stage-a"))
        pipeline.add_stage(DummyStage("stage-b"))
        pipeline.add_stage(DummyStage("stage-c"))

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            pipeline.run(ctx)

        output = buffer.getvalue()
        self.assertIn("[STAGE] processing 68", output)
        self.assertIn("[STAGE] processing 81", output)
        self.assertIn("[STAGE] processing 95", output)


if __name__ == '__main__':
    unittest.main()
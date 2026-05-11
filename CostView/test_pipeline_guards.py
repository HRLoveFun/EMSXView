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

from DataPipeline.src.acquisition.bdib_fetcher import _is_safe_bdib_query_date
from DataPipeline.src.processing.daily_metrics_calculator import CalculateDailyMetrics
from DataPipeline.src.common.exchange_tz import batch_convert_ny_to_local
from DataPipeline.src.common.outdated_tickers import load_outdated_ticker_records, record_outdated_ticker
from DataPipeline.src.orchestration.pipeline import BaseStage, FinancialPipeline, IntegrateBDIBStage, PipelineContext
from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from DataPipeline.src.storage.connection import ConnectionManager
from DataPipeline.src.storage.repositories.fills_read import SqliteFillReadRepository
from DataPipeline.src.storage.repositories._schema import init_processed_fills_schema
from DataPipeline.src.storage.raw_bdib_db import RawBDIBDB
from CostView.src.tca_query_service import TcaQueryService
from platform_data.adapters import MarketReferenceDataAdapter


class PipelineGuardTests(unittest.TestCase):
    def test_batch_exchange_time_conversion_preserves_local_wall_clock(self) -> None:
        converted = batch_convert_ny_to_local(
            pd.Series(pd.to_datetime(["2026-04-20T01:00:14-04:00"])),
            pd.Series(["NZ"]),
        )

        self.assertEqual(converted.dt.strftime("%Y-%m-%d %H:%M:%S").iloc[0], "2026-04-20 15:00:14")

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
            mgr = ConnectionManager(path_overrides={"processed_fills": f"{tmp_dir}/processed_fills.db"})
            init_processed_fills_schema(SqliteFillReadRepository(mgr))
            repo = SqliteFillReadRepository(mgr)
            conn = repo._get_read_conn()
            try:
                busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(busy_timeout, Config.SQLITE_BUSY_TIMEOUT_MS)

    def test_processed_fills_db_initializes_execution_history_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            mgr = ConnectionManager(path_overrides={"processed_fills": f"{tmp_dir}/processed_fills.db"})
            init_processed_fills_schema(SqliteFillReadRepository(mgr))
            repo = SqliteFillReadRepository(mgr)
            conn = repo._get_read_conn()
            try:
                table_names = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                conn.close()

        self.assertIn(Config.ORDER_HISTORY_TABLE, table_names)
        self.assertIn(Config.ROUTE_HISTORY_TABLE, table_names)
        self.assertIn(Config.ROUTE_EVENT_HISTORY_TABLE, table_names)

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

    @patch("DataPipeline.src.acquisition.bdib_fetcher.fetch_bdib_for_ticker_date")
    @patch("DataPipeline.src.acquisition.bdib_fetcher.load_outdated_ticker_set")
    @patch("DataPipeline.src.acquisition.bdib_fetcher._is_safe_bdib_query_date", return_value=True)
    @patch("DataPipeline.src.acquisition.bdib_fetcher._is_trading_day", return_value=True)
    def test_fetch_bdib_skips_outdated_tickers(
        self,
        _mock_trading_day,
        _mock_safe_date,
        mock_load_outdated,
        mock_fetch_one,
    ) -> None:
        from DataPipeline.src.acquisition.bdib_fetcher import fetch_bdib_for_fills

        mock_load_outdated.return_value = {"1CO GR Equity"}
        mock_fetch_one.return_value = pd.DataFrame(
            [
                {
                    "mkt_timestamp": "09:30:00",
                    "close": 100.0,
                    "equ_ticker": "AAPL US Equity",
                    "order_as_of_date": "20260420",
                    "open": 99.0,
                    "high": 101.0,
                    "low": 98.0,
                    "volume": 10.0,
                    "num_trds": 1.0,
                    "value": 1000.0,
                }
            ]
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
                write_manifest(fills_repo=FakeProcDb(), updated_dates=["20260420"])
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
        from DataPipeline.src.storage.facade import CostViewDatabase
        from DataPipeline.src.storage.connection import ConnectionManager

        class FakeFillsRead:
            """Minimal stub to provide ticker dates for the new facade."""
            @staticmethod
            def get_ticker_dates(ticker_type: str = "equ_ticker") -> dict[str, list[str]]:
                if ticker_type != "equ_ticker":
                    raise AssertionError(f"unexpected ticker_type: {ticker_type}")
                return {"AAPL US Equity": ["20260421"]}

        with tempfile.TemporaryDirectory() as tmp_dir:
            mgr = ConnectionManager(path_overrides={
                "raw_bdib": Path(tmp_dir) / "raw_bdib.db",
            })
            # Initialize schema via legacy RawBDIBDB (its _init_db creates tables)
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                RawBDIBDB(connection_manager=mgr)

            db = CostViewDatabase(connection_manager=mgr)

            # Inject fake fills_read so _get_active_tickers_for_date works
            db.fills_read = FakeFillsRead()  # type: ignore[assignment]

            db.market_data_write.upsert_bdib_data(
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

            calc = CalculateDailyMetrics(connection_manager=mgr, db=db)
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

            summary_df = db.market_data_read.get_daily_summary("AAPL US Equity", end_date="20260421")
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


class MarketViewIntradayFeatureTests(unittest.TestCase):
    def _build_db_with_bars(self, tmp_dir: str) -> RawBDIBDB:
        db = RawBDIBDB(db_path=f"{tmp_dir}/raw_bdib.db")
        bars = []
        # Build 2 tickers x 60 bars each at 10:00:00..10:09:50 with increasing close
        for ticker_idx, ticker in enumerate(["AAPL US Equity", "MSFT US Equity"]):
            base_close = 100.0 + ticker_idx * 50.0
            for bar_idx in range(60):
                total_seconds = 10 * 3600 + bar_idx * 10
                hh, rem = divmod(total_seconds, 3600)
                mm, ss = divmod(rem, 60)
                bars.append(
                    {
                        "equ_ticker": ticker,
                        "order_as_of_date": "20260421",
                        "mkt_timestamp": f"{hh:02d}:{mm:02d}:{ss:02d}",
                        "open": base_close + bar_idx * 0.05,
                        "high": base_close + bar_idx * 0.05 + 0.05,
                        "low": base_close + bar_idx * 0.05 - 0.05,
                        "close": base_close + bar_idx * 0.1,
                        "volume": 100.0 + bar_idx,
                        "num_trds": 10.0,
                        "value": 0.0,
                    }
                )
        db.upsert_bdib_data(pd.DataFrame(bars))
        db.upsert_daily_summary(
            [
                {
                    "equ_ticker": "AAPL US Equity",
                    "trade_date": "20260421",
                    "total_volume": 9500.0,
                    "daily_vwap": 105.0,
                    "daily_close": 200.0,
                    "daily_volatility": 24.0,
                    "intraday_volatility": 1.5,
                    "adv_5d": 8500.0,
                    "adv_20d": 8000.0,
                },
                {
                    "equ_ticker": "MSFT US Equity",
                    "trade_date": "20260421",
                    "total_volume": 9800.0,
                    "daily_vwap": 155.0,
                    "daily_close": 260.0,
                    "daily_volatility": 20.0,
                    "intraday_volatility": 1.2,
                    "adv_5d": 9200.0,
                    "adv_20d": 9000.0,
                },
            ]
        )
        return db

    def test_raw_bdib_pool_batch_query_returns_only_requested_tickers_and_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = self._build_db_with_bars(tmp_dir)
            # Insert bars for another date to ensure date filter works
            db.upsert_bdib_data(
                pd.DataFrame(
                    [
                        {
                            "equ_ticker": "AAPL US Equity",
                            "order_as_of_date": "20260420",
                            "mkt_timestamp": "09:30:00",
                            "close": 199.0,
                            "volume": 5.0,
                        }
                    ]
                )
            )

            result = db.get_bdib_bars_for_tickers_and_dates(
                ["AAPL US Equity", "MSFT US Equity"],
                start_date="20260421",
                end_date="20260421",
            )

        self.assertEqual(set(result["equ_ticker"].unique()), {"AAPL US Equity", "MSFT US Equity"})
        self.assertEqual(set(result["order_as_of_date"].unique()), {"20260421"})
        self.assertEqual(len(result), 120)

    def test_intraday_feature_adapter_produces_bucketed_features(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._build_db_with_bars(tmp_dir)
            mgr = ConnectionManager(path_overrides={
                "raw_bdib": Path(tmp_dir) / "raw_bdib.db",
            })
            adapter = MarketReferenceDataAdapter(connection_manager=mgr)

            snapshot = adapter.get_intraday_features(
                equ_tickers=["AAPL US Equity", "MSFT US Equity", "MISSING US Equity"],
                trade_date="20260421",
                bucket_minutes=5,
            )

        self.assertEqual(snapshot.trade_date, "20260421")
        self.assertEqual(snapshot.bucket_minutes, 5)
        self.assertEqual(snapshot.ticker_count, 2)
        self.assertEqual(snapshot.missing_tickers, ["MISSING US Equity"])

        aapl = next(t for t in snapshot.tickers if t.equ_ticker == "AAPL US Equity")
        self.assertEqual(aapl.bar_count, 60)
        self.assertEqual(aapl.first_bar_time, "10:00")
        self.assertEqual(aapl.last_bar_time, "10:09")
        # 60 bars / 5-min bucket at 10s interval → 2 buckets
        self.assertEqual(len(aapl.buckets), 2)
        self.assertEqual(aapl.buckets[0].bucket_start, "10:00")
        self.assertEqual(aapl.buckets[0].bucket_end, "10:05")
        # cumulative volume of last bucket must equal total volume
        self.assertAlmostEqual(
            aapl.buckets[-1].cumulative_volume,
            aapl.total_volume,
        )
        # cumulative pct at end ≈ 100%
        self.assertAlmostEqual(aapl.buckets[-1].cumulative_volume_pct, 100.0, places=4)
        # volume_vs_adv20 uses daily_summary adv_20d
        self.assertAlmostEqual(aapl.adv_20d, 8000.0)
        self.assertAlmostEqual(
            aapl.volume_vs_adv20_pct,
            aapl.total_volume / 8000.0 * 100.0,
            places=4,
        )
        # open/close 10-min windows cover the whole session here so share ≈ 100%
        self.assertIsNotNone(aapl.open_window_share_pct)
        self.assertGreater(aapl.open_window_share_pct, 99.0)
        # realized vol is a non-negative percent or None
        for bucket in aapl.buckets:
            if bucket.realized_vol_annualized is not None:
                self.assertGreaterEqual(bucket.realized_vol_annualized, 0.0)

    def test_intraday_feature_adapter_rejects_bad_bucket_and_too_many_tickers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = RawBDIBDB(db_path=f"{tmp_dir}/raw_bdib.db")
            adapter = MarketReferenceDataAdapter(daily_summary_db_factory=lambda: db)

            with self.assertRaises(ValueError):
                adapter.get_intraday_features(
                    equ_tickers=["AAPL US Equity"],
                    trade_date="20260421",
                    bucket_minutes=7,
                )

            with self.assertRaises(ValueError):
                adapter.get_intraday_features(
                    equ_tickers=[],
                    trade_date="20260421",
                )

            too_many = [f"T{i} US Equity" for i in range(26)]
            with self.assertRaises(ValueError):
                adapter.get_intraday_features(
                    equ_tickers=too_many,
                    trade_date="20260421",
                )

    def test_intraday_feature_adapter_handles_missing_trade_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = RawBDIBDB(db_path=f"{tmp_dir}/raw_bdib.db")
            adapter = MarketReferenceDataAdapter(daily_summary_db_factory=lambda: db)

            snapshot = adapter.get_intraday_features(
                equ_tickers=["AAPL US Equity"],
                trade_date=None,
            )

        self.assertIsNone(snapshot.trade_date)
        self.assertEqual(snapshot.ticker_count, 0)
        self.assertEqual(snapshot.missing_tickers, ["AAPL US Equity"])


if __name__ == '__main__':
    unittest.main()
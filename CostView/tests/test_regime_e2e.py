"""End-to-end smoke test of the regime layer using a deterministic mock fetcher.

Runs:
  1. ensure_default_config()
  2. market_index_loader.load_market_index(..., fetcher=mock_fetcher)
  3. vol_regime / liquidity_regime / trend_regime classify
  4. fill_regime_tagger.tag_fills against an in-memory processed_fills.db

Uses a temp regime.db so the production DB is untouched.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from CostView.src.regime import (
    fill_regime_tagger,
    liquidity_regime,
    market_index_loader,
    trend_regime,
    vol_regime,
)
from CostView.src.regime.config import ensure_default_config
from CostView.src.regime.migrations.apply import apply_pending
from CostView.src.regime.schema import connect, ensure_schema_current


def make_mock_fetcher(seed: int = 42):
    """Return a fetcher that yields a deterministic price/turnover/vol series per ticker."""
    rng = np.random.default_rng(seed)

    def _fetch(ticker: str, fields, start: dt.date, end: dt.date) -> pd.DataFrame:
        # Generate business-day-ish daily index (use calendar days; sufficient for unit test).
        idx = pd.date_range(start=start, end=end, freq="D").date
        n = len(idx)
        if n == 0:
            return pd.DataFrame()
        # Random-walk price around 100.
        steps = rng.normal(0, 1, n)
        px = 100 + np.cumsum(steps)
        df = pd.DataFrame(index=pd.Index(idx, name="date"))
        if "PX_LAST" in fields:
            df["PX_LAST"] = px
        if "TURNOVER" in fields:
            df["TURNOVER"] = rng.uniform(1e8, 5e8, n)
        for f in ("VOLATILITY_20D", "VOLATILITY_60D"):
            if f in fields:
                df[f] = rng.uniform(8.0, 25.0, n)
        for f in ("MOV_AVG_30D", "MOV_AVG_50D", "MOV_AVG_200D"):
            if f in fields:
                df[f] = pd.Series(px).rolling(5, min_periods=1).mean().to_numpy()
        if "RSI_30D" in fields:
            df["RSI_30D"] = rng.uniform(20.0, 80.0, n)
        return df

    return _fetch


class RegimeE2ETest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.regime_db = Path(self.tmpdir.name) / "regime.db"
        self.fills_db = Path(self.tmpdir.name) / "processed_fills.db"
        apply_pending(self.regime_db)
        ensure_schema_current(self.regime_db)
        # Seed minimal market mapping (don't depend on JSON file path).
        self._seed_markets()
        self._seed_processed_fills()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _seed_markets(self):
        conn = connect(self.regime_db)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                """INSERT INTO ref_market_mapping
                   (market_code, description, currency, vol_index, benchmark,
                    session_open, session_close, lunch_start, lunch_end,
                    closing_auction_start, source_file_version, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    ("US", "United States", "USD", "VIX Index", "SPX Index",
                     "09:30", "16:00", None, None, "15:50",
                     "test", dt.datetime.now().isoformat()),
                    ("HK", "Hong Kong", "HKD", "VHSI Index", "HSI Index",
                     "09:30", "16:00", "12:00", "13:00", "16:00",
                     "test", dt.datetime.now().isoformat()),
                ],
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

    def _seed_processed_fills(self):
        # Build a minimal processed_fills table matching tagger's SELECT.
        conn = sqlite3.connect(str(self.fills_db))
        try:
            conn.execute("""
                CREATE TABLE processed_fills (
                    OrderId TEXT, RouteId TEXT, FillId TEXT,
                    order_as_of_date TEXT,
                    Exchange TEXT, Currency TEXT,
                    PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)
                )
            """)
            rows = [
                ("O1", "R1", "F1", "20260415", "US", "USD"),
                ("O1", "R1", "F2", "20260415", "US", "USD"),
                ("O2", "R1", "F1", "20260416", "HK", "HKD"),
            ]
            conn.executemany(
                "INSERT INTO processed_fills VALUES (?,?,?,?,?,?)", rows,
            )
            conn.commit()
        finally:
            conn.close()

    def test_full_pipeline(self):
        version = ensure_default_config(self.regime_db)
        self.assertEqual(version, "v0_default")

        n = market_index_loader.load_market_index(
            "2026-04-01", "2026-04-20", db_path=self.regime_db,
            fetcher=make_mock_fetcher(),
        )
        self.assertGreater(n, 0)

        n_vol = vol_regime.classify("2026-04-01", "2026-04-20", db_path=self.regime_db)
        n_liq = liquidity_regime.classify("2026-04-01", "2026-04-20", db_path=self.regime_db)
        n_trend = trend_regime.classify("2026-04-01", "2026-04-20", db_path=self.regime_db)
        self.assertGreater(n_vol, 0)
        self.assertGreater(n_liq, 0)
        self.assertGreater(n_trend, 0)

        s = fill_regime_tagger.tag_fills(
            "2026-04-15", "2026-04-16",
            db_path=self.regime_db, fills_db_path=self.fills_db,
        )
        self.assertEqual(s["total_fills"], 3)
        self.assertEqual(s["skipped_no_market"], 0)
        self.assertEqual(s["rows_upserted"], 3)

        # Verify labels were written.
        conn = connect(self.regime_db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM fill_regime_labels").fetchone()[0]
            mc_set = {r[0] for r in conn.execute(
                "SELECT DISTINCT market_code FROM fill_regime_labels"
            ).fetchall()}
        finally:
            conn.close()
        self.assertEqual(count, 3)
        self.assertEqual(mc_set, {"US", "HK"})

        # Re-running the tagger must be idempotent (UPSERT, not duplicate).
        s2 = fill_regime_tagger.tag_fills(
            "2026-04-15", "2026-04-16",
            db_path=self.regime_db, fills_db_path=self.fills_db,
        )
        self.assertEqual(s2["rows_upserted"], 3)
        conn = connect(self.regime_db)
        try:
            count2 = conn.execute("SELECT COUNT(*) FROM fill_regime_labels").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count2, 3)

    def test_audit_run_journal(self):
        from CostView.src.regime.run_journal import run_journal
        ensure_default_config(self.regime_db)
        with run_journal("smoke_test", config_version="v0_default",
                         start="2026-04-01", end="2026-04-02",
                         db_path=self.regime_db) as rec:
            rec.set_rows(42)
        conn = connect(self.regime_db)
        try:
            row = conn.execute(
                "SELECT stage_name, status, rows_written FROM audit_pipeline_runs WHERE stage_name='smoke_test'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(tuple(row), ("smoke_test", "success", 42))


if __name__ == "__main__":
    unittest.main()

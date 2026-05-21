"""Unit + small e2e coverage for CostView/src/attribution/.

Tested:
  - metrics.parse_side / slippage_bps / reversal_bps / winsorize_series
  - aggregator.bootstrap_ci_mean  (CI shrinks with n; covers true mean)
  - aggregator.aggregate_cells    (per-cell n / mean / ci columns)
  - aggregator.pairwise_welch_bh  (separable means -> low p; identical -> high p)
                                   and BH q-values are non-decreasing in p
"""
from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from DataPipeline.analysis.attribution.aggregator import (
    METRICS,
    DEFAULT_BUCKET_SPECS,
    add_bucket_columns,
    aggregate_cells,
    bootstrap_ci_mean,
    pairwise_welch_bh,
)
from DataPipeline.analysis.attribution.config import ActiveAttributionConfig
from DataPipeline.analysis.attribution.metrics import (
    parse_side,
    reversal_bps,
    slippage_bps,
    winsorize_series,
)


def _cfg(min_n: int = 30, n_boot: int = 300) -> ActiveAttributionConfig:
    return ActiveAttributionConfig(
        version_id="test",
        bench_methods=["arrival_mid", "interval_vwap"],
        reversal_windows_min=[1, 5, 30],
        winsor_pct=0.01,
        adv_window_days=20,
        bootstrap_n=n_boot,
        min_cell_n=min_n,
        description="unit-test",
    )


class TestMetrics(unittest.TestCase):
    def test_parse_side(self):
        for s in ("B", "BUY", "buy"): self.assertEqual(parse_side(s), 1)
        for s in ("S", "SELL", "sell"): self.assertEqual(parse_side(s), -1)
        self.assertIsNone(parse_side(""))
        self.assertIsNone(parse_side(None))

    def test_slippage_sign(self):
        # Buy fills above arrival -> adverse positive
        self.assertAlmostEqual(slippage_bps(+1, 100.5, 100.0), 50.0, places=4)
        # Sell fills below arrival -> adverse positive
        self.assertAlmostEqual(slippage_bps(-1, 99.5, 100.0), 50.0, places=4)
        # Neutral / missing
        self.assertIsNone(slippage_bps(+1, 100.0, None))
        self.assertIsNone(slippage_bps(+1, 100.0, 0.0))

    def test_reversal_sign(self):
        # Buy fill 100, mid_after 101 -> price kept moving up -> reversal positive
        self.assertAlmostEqual(reversal_bps(+1, 100.0, 101.0), 100.0, places=2)
        # Sell fill 100, mid_after 99 -> price kept moving down -> reversal positive
        self.assertAlmostEqual(reversal_bps(-1, 100.0, 99.0), 100.0, places=2)
        self.assertIsNone(reversal_bps(+1, 100.0, None))

    def test_winsorize(self):
        v = np.array([-1000.0, -1.0, 0.0, 1.0, 1000.0])
        w = winsorize_series(v, 0.20)
        # Tails clipped to non-extreme values
        self.assertLess(w.max(), 1000.0)
        self.assertGreater(w.min(), -1000.0)


class TestBootstrapCI(unittest.TestCase):
    def test_ci_covers_mean_and_shrinks(self):
        rng = np.random.default_rng(7)
        sample_small = rng.normal(0, 1, 60)
        sample_big   = rng.normal(0, 1, 6000)
        lo_s, hi_s = bootstrap_ci_mean(sample_small, n_resamples=400, rng=np.random.default_rng(1))
        lo_b, hi_b = bootstrap_ci_mean(sample_big,   n_resamples=400, rng=np.random.default_rng(2))
        self.assertLess(hi_b - lo_b, hi_s - lo_s)            # bigger n -> tighter CI
        self.assertLessEqual(lo_b, 0.0)                       # CI brackets true mean=0
        self.assertGreaterEqual(hi_b, 0.0)

    def test_too_few_returns_nan(self):
        lo, hi = bootstrap_ci_mean(np.array([1.0, 2.0]), n_resamples=100)
        self.assertTrue(math.isnan(lo) and math.isnan(hi))


class TestAggregator(unittest.TestCase):
    @staticmethod
    def _mk_df(n_per_cell: int = 80, seed: int = 11) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        rows = []
        # Two brokers with different IS distributions; rest of metric columns
        # are present (NaN for vwap_bps/reversal to exercise NaN handling).
        for broker, mu in [("A", 5.0), ("B", -5.0)]:
            for _ in range(n_per_cell):
                rows.append({
                    "OrderId": "o", "RouteId": "r", "FillId": str(rng.integers(0, 1e9)),
                    "order_as_of_date_iso": "2026-01-01",
                    "market_code": "XX", "broker": broker, "algo": "vwap",
                    "side": 1,
                    "fill_shares": 100.0, "fill_price": 100.0, "route_shares": 100.0,
                    "pct_adv": 1e-4,
                    "is_bps":  rng.normal(mu, 1.0),
                    "vwap_bps": rng.normal(mu, 1.0),
                    "reversal_1m_bps": np.nan,
                    "reversal_5m_bps": np.nan,
                    "reversal_30m_bps": np.nan,
                })
        return pd.DataFrame(rows)

    def test_aggregate_cells_shape(self):
        df = self._mk_df()
        agg = aggregate_cells(df, cfg=_cfg(min_n=30, n_boot=200), by=["broker", "algo"])
        self.assertEqual(len(agg), 2)
        for col in ("is_bps_n", "is_bps_mean", "is_bps_ci_lo", "is_bps_ci_hi", "is_bps_mean_winsor"):
            self.assertIn(col, agg.columns)
        # Means roughly recover the population means
        means = dict(zip(agg["broker"], agg["is_bps_mean"]))
        self.assertGreater(means["A"], 4.0)
        self.assertLess(means["B"], -4.0)

    def test_pairwise_welch_bh(self):
        df = self._mk_df(n_per_cell=80)
        pairs = pairwise_welch_bh(df, metric="is_bps", by=["broker", "algo"], cfg=_cfg(min_n=30, n_boot=100))
        self.assertEqual(len(pairs), 1)
        row = pairs.iloc[0]
        self.assertLess(row["p_value"], 0.001)
        self.assertLess(row["q_value"], 0.001)
        # diff is mean_a - mean_b; sorted alphabetically, A is first -> +ve diff
        self.assertGreater(row["diff"], 0.0)

    def test_bh_monotone_qvalues(self):
        # Build 4 cells: 2 distinct means and 2 near-identical pairs
        rng = np.random.default_rng(3)
        rows = []
        for broker, mu in [("A", 0.0), ("B", 0.05), ("C", 8.0), ("D", -8.0)]:
            for _ in range(60):
                rows.append({
                    "OrderId":"o","RouteId":"r","FillId":str(rng.integers(0,1e9)),
                    "order_as_of_date_iso":"2026-01-01",
                    "market_code":"XX","broker":broker,"algo":"vwap","side":1,
                    "fill_shares":100,"fill_price":100,"route_shares":100,"pct_adv":1e-4,
                    "is_bps": rng.normal(mu, 1.0),
                    "vwap_bps": np.nan, "reversal_1m_bps": np.nan,
                    "reversal_5m_bps": np.nan, "reversal_30m_bps": np.nan,
                })
        df = pd.DataFrame(rows)
        pairs = pairwise_welch_bh(df, metric="is_bps", by=["broker","algo"], cfg=_cfg(min_n=30, n_boot=100))
        # 4 cells -> C(4,2)=6 pairs
        self.assertEqual(len(pairs), 6)
        # q sorted by p ascending must be non-decreasing
        q = pairs["q_value"].to_numpy()
        for i in range(1, len(q)):
            self.assertGreaterEqual(q[i] + 1e-12, q[i-1])
        # All q in [0,1]
        self.assertTrue(((q >= 0) & (q <= 1)).all())


class TestBuckets(unittest.TestCase):
    def test_add_bucket_columns(self):
        df = pd.DataFrame({
            "pct_adv": [0.0, 0.001, 0.007, 0.02, 0.5, np.nan, -0.1],
            "participation_rate": [0.0, 0.03, 0.07, 0.15, 0.5, 0.99, np.nan],
        })
        out = add_bucket_columns(df, DEFAULT_BUCKET_SPECS)
        self.assertIn("pct_adv_bucket", out.columns)
        self.assertIn("participation_rate_bucket", out.columns)
        # 0.001 -> first bucket [0%-0.50%)
        self.assertTrue(out["pct_adv_bucket"].iloc[1].startswith("[0.00%-0.50%"))
        # 0.5 -> last bucket which is closed on right
        self.assertTrue(out["pct_adv_bucket"].iloc[4].endswith("]"))
        # Negative / NaN -> NaN bucket label
        self.assertTrue(pd.isna(out["pct_adv_bucket"].iloc[5]))
        self.assertTrue(pd.isna(out["pct_adv_bucket"].iloc[6]))

    def test_aggregate_cells_with_bucket(self):
        # Build a frame with two pct_adv buckets and verify groupby slices.
        rng = np.random.default_rng(7)
        rows = []
        for pct in (0.001, 0.03):  # bucket 1 vs bucket 3
            for _ in range(50):
                rows.append({
                    "OrderId":"o","RouteId":"r","FillId":str(rng.integers(0,1e9)),
                    "order_as_of_date_iso":"2026-01-01","market_code":"XX",
                    "broker":"A","algo":"vwap","side":1,
                    "fill_shares":100,"fill_price":100,"route_shares":100,
                    "pct_adv": pct,
                    "is_bps": rng.normal(2.0 if pct < 0.005 else 8.0, 1.0),
                    "vwap_bps": np.nan, "reversal_1m_bps": np.nan,
                    "reversal_5m_bps": np.nan, "reversal_30m_bps": np.nan,
                })
        df = pd.DataFrame(rows)
        agg = aggregate_cells(
            df, cfg=_cfg(min_n=30, n_boot=200),
            by=["broker", "algo", "pct_adv_bucket"],
            bucket_specs={"pct_adv": [0.0, 0.005, 0.01, 0.05, 1.0]},
        )
        self.assertEqual(len(agg), 2)
        # Larger pct_adv bucket should have larger mean is_bps
        agg_sorted = agg.sort_values("pct_adv_bucket")
        means = agg_sorted["is_bps_mean"].tolist()
        self.assertLess(means[0], means[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)

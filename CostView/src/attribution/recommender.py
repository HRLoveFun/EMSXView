"""Conditional algo recommender (P1.5).

Given a context (market, side, size_pct_adv, vol_regime, liq_regime), return
the top-k (broker, algo) cells with lowest mean implementation shortfall (IS),
along with bootstrap CI and sample size.

Cells with n < min_n are excluded. Default IS = is_bps (positive = adverse).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from CostView.src.regime.schema import REGIME_DB_PATH, connect as connect_regime

from .aggregator import bootstrap_ci_mean
from .config import get_active_config

logger = logging.getLogger(__name__)


def recommend(
    market: str,
    side: int,                       # +1 buy, -1 sell
    size_pct_adv: float,             # e.g. 0.02 means 2%
    vol_regime: Optional[str] = None,
    liq_regime: Optional[str] = None,
    *,
    metric: str = "is_bps",
    top_k: int = 3,
    min_n: int = 30,
    pct_adv_window: float = 0.5,     # +/- 50% around size_pct_adv
    config_version: Optional[str] = None,
    db_path: Path = REGIME_DB_PATH,
    bootstrap_n: int = 5000,
    rng_seed: int = 42,
) -> pd.DataFrame:
    """Return DataFrame: broker, algo, n, mean, ci_lo, ci_hi (sorted by mean asc).

    Pipeline:
      1. SELECT from fill_attribution_metrics filtered by market_code+side+pct_adv window.
      2. Optional JOIN to fill_regime_labels for vol_regime / liq_regime match.
      3. group by broker+algo; require n >= min_n; bootstrap CI; sort by mean asc.
    """
    if metric not in ("is_bps", "vwap_bps"):
        raise ValueError(f"unsupported metric: {metric}")
    if config_version is None:
        cfg = get_active_config(db_path)
        if cfg is None:
            raise RuntimeError("no active attribution config")
        config_version = cfg.version_id

    lo = max(0.0, size_pct_adv * (1.0 - pct_adv_window))
    hi = size_pct_adv * (1.0 + pct_adv_window)

    params: list = [config_version, market, int(side), lo, hi]
    join_sql = ""
    where_extra = ""
    if vol_regime or liq_regime:
        join_sql = """
            JOIN fill_regime_labels frl
              ON frl.FillId = fam.FillId
             AND frl.order_as_of_date_iso = fam.order_as_of_date_iso
             AND frl.config_version = (
                 SELECT version_id FROM audit_regime_config_versions
                 WHERE is_active = 1 LIMIT 1
             )
        """
        if vol_regime:
            where_extra += " AND frl.vol_regime = ? "
            params.append(vol_regime)
        if liq_regime:
            where_extra += " AND frl.liq_regime = ? "
            params.append(liq_regime)

    sql = f"""
        SELECT fam.broker, fam.algo, fam.{metric} AS m
        FROM fill_attribution_metrics fam
        {join_sql}
        WHERE fam.config_version = ?
          AND fam.market_code = ?
          AND fam.side = ?
          AND fam.pct_adv BETWEEN ? AND ?
          AND fam.{metric} IS NOT NULL
          {where_extra}
    """
    conn = connect_regime(db_path)
    try:
        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
    if df.empty:
        return pd.DataFrame(columns=["broker", "algo", "n", "mean", "ci_lo", "ci_hi"])

    rng = np.random.default_rng(rng_seed)
    rows: List[dict] = []
    for (broker, algo), sub in df.groupby(["broker", "algo"], dropna=False):
        v = sub["m"].to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        n = int(v.size)
        if n < min_n:
            continue
        ci_lo, ci_hi = bootstrap_ci_mean(v, bootstrap_n, rng=rng)
        rows.append({
            "broker": broker, "algo": algo, "n": n,
            "mean": float(v.mean()), "ci_lo": ci_lo, "ci_hi": ci_hi,
        })
    if not rows:
        return pd.DataFrame(columns=["broker", "algo", "n", "mean", "ci_lo", "ci_hi"])
    out = pd.DataFrame(rows).sort_values("mean", ascending=True).head(top_k).reset_index(drop=True)
    return out

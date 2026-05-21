"""Conditional algo recommender (P1.5).

Given a context (market, side, size_pct_adv, vol_regime, liq_regime), return
the top-k (broker, algo) cells with lowest mean implementation shortfall (IS),
along with bootstrap CI and sample size.

Cells with n < min_n are excluded. Default IS = is_bps (positive = adverse).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

import numpy as np
import pandas as pd

from .aggregator import bootstrap_ci_mean
from .config import get_active_config

if TYPE_CHECKING:
    from .protocols import AttributionConfigRepository, RegimeRepository

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
    db_path: Optional[Path] = None,
    bootstrap_n: int = 5000,
    rng_seed: int = 42,
    regime_repo: Optional["RegimeRepository"] = None,
    config_repo: Optional["AttributionConfigRepository"] = None,
) -> pd.DataFrame:
    """Return DataFrame: broker, algo, n, mean, ci_lo, ci_hi (sorted by mean asc).

    Pipeline:
      1. SELECT from fill_attribution_metrics filtered by market_code+side+pct_adv window.
      2. Optional JOIN to fill_regime_labels for vol_regime / liq_regime match.
      3. group by broker+algo; require n >= min_n; bootstrap CI; sort by mean asc.

    Supports two calling conventions:
      1. Pass regime_repo and config_repo directly (preferred).
      2. Pass db_path to auto-create repositories (legacy).
    """
    if metric not in ("is_bps", "vwap_bps"):
        raise ValueError(f"unsupported metric: {metric}")

    # Resolve repository instances (legacy fallback)
    if regime_repo is None or config_repo is None:
        if db_path is None:
            from DataPipeline.analysis.regime.schema import REGIME_DB_PATH as _DEFAULT_PATH
            db_path = _DEFAULT_PATH
        from .repositories import SqliteAttributionConfigRepository, SqliteRegimeRepository
        if regime_repo is None:
            regime_repo = SqliteRegimeRepository(db_path)
        if config_repo is None:
            config_repo = SqliteAttributionConfigRepository(db_path)

    if config_version is None:
        cfg = get_active_config(config_repo=config_repo)
        if cfg is None:
            raise RuntimeError("no active attribution config")
        config_version = cfg.version_id

    lo = max(0.0, size_pct_adv * (1.0 - pct_adv_window))
    hi = size_pct_adv * (1.0 + pct_adv_window)

    # Build query parameters for regime_repo.get_recommendations()
    params: List = [config_version, market, int(side), lo, hi]
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

    df = regime_repo.get_recommendations(
        market=market, side=side, lo=lo, hi=hi,
        metric=metric, config_version=config_version,
        join_sql=join_sql, where_extra=where_extra, params=params,
    )

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

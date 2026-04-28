"""
Cell aggregator (Stage 11) for attribution metrics.

Reads fill_attribution_metrics, optionally JOINs fill_regime_labels for a
regime dimension, then computes per-cell statistics:

  cell key   = (broker, algo[, regime_dim, regime_value])
  per metric = mean, median, std, n
               + winsorized mean
               + bootstrap 95% CI on mean (resample N from active config)

Pairwise Welch's t-test between cells (within the same metric + regime slice),
then Benjamini-Hochberg FDR correction over all p-values inside that slice.

Output: pandas DataFrames (in-memory). The caller (CLI / notebook) can write
them to CSV / Markdown. We do NOT persist back to regime.db: aggregations are
reproducible from fill_attribution_metrics.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    from scipy import stats as scipy_stats
except ImportError:  # pragma: no cover
    scipy_stats = None  # type: ignore

from CostView.src.regime.schema import REGIME_DB_PATH, connect as connect_regime

from .config import ActiveAttributionConfig, get_active_config
from .metrics import winsorize_series

logger = logging.getLogger(__name__)

METRICS = ["is_bps", "vwap_bps", "reversal_1m_bps", "reversal_5m_bps", "reversal_30m_bps"]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_fill_metrics(
    start_date_iso: str,
    end_date_iso: str,
    *,
    config_version: Optional[str] = None,
    regime_dim: Optional[str] = None,        # 'vol_regime' | 'liq_regime' | 'trend_regime'
    db_path: Path = REGIME_DB_PATH,
) -> pd.DataFrame:
    """Load attribution rows for the requested window, optionally joined with one regime dim.

    Returns DataFrame with columns: OrderId, RouteId, FillId, order_as_of_date_iso,
      market_code, broker, algo, side, fill_shares, fill_price, route_shares,
      pct_adv, is_bps, vwap_bps, reversal_*, [regime_dim_col]
    """
    if config_version is None:
        cfg = get_active_config(db_path)
        if cfg is None:
            raise RuntimeError("no active attribution config")
        config_version = cfg.version_id

    base_sql = """
        SELECT fam.OrderId, fam.RouteId, fam.FillId, fam.order_as_of_date_iso,
               fam.market_code, fam.broker, fam.algo, fam.side,
               fam.fill_shares, fam.fill_price, fam.route_shares, fam.pct_adv,
               fam.is_bps, fam.vwap_bps,
               fam.reversal_1m_bps, fam.reversal_5m_bps, fam.reversal_30m_bps
        FROM fill_attribution_metrics fam
        WHERE fam.config_version = ?
          AND fam.order_as_of_date_iso BETWEEN ? AND ?
    """
    conn = connect_regime(db_path)
    try:
        df = pd.read_sql_query(
            base_sql, conn,
            params=(config_version, start_date_iso, end_date_iso),
        )
        if regime_dim:
            if regime_dim not in {"vol_regime", "liq_regime", "trend_regime"}:
                raise ValueError(f"unknown regime_dim: {regime_dim}")
            # Pull regime labels (regime config = active)
            reg_df = pd.read_sql_query(
                f"""SELECT fill_id AS FillId, trade_date AS order_as_of_date_iso,
                           {regime_dim} AS regime_value
                    FROM fill_regime_labels
                    WHERE config_version = (
                        SELECT version_id FROM audit_regime_config_versions
                        WHERE is_active = 1 LIMIT 1
                    )
                      AND trade_date BETWEEN ? AND ?""",
                conn, params=(start_date_iso, end_date_iso),
            )
            df = df.merge(reg_df, on=["FillId", "order_as_of_date_iso"], how="left")
            df = df.rename(columns={"regime_value": regime_dim})
    finally:
        conn.close()
    return df


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------
def bootstrap_ci_mean(
    values: np.ndarray,
    n_resamples: int,
    alpha: float = 0.05,
    rng: Optional[np.random.Generator] = None,
) -> Tuple[float, float]:
    """Percentile bootstrap CI for the mean. Returns (lo, hi). NaN if n<5."""
    finite = values[np.isfinite(values)]
    if finite.size < 5:
        return (float("nan"), float("nan"))
    rng = rng or np.random.default_rng(0)
    n = finite.size
    idx = rng.integers(0, n, size=(n_resamples, n))
    means = finite[idx].mean(axis=1)
    lo = float(np.quantile(means, alpha / 2))
    hi = float(np.quantile(means, 1 - alpha / 2))
    return (lo, hi)


# ---------------------------------------------------------------------------
# Cell aggregation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CellSpec:
    by: Tuple[str, ...]                         # group columns
    metrics: Tuple[str, ...] = tuple(METRICS)
    weight_col: Optional[str] = None            # 'route_notional' for weighted mean


def _route_notional(df: pd.DataFrame) -> pd.Series:
    return (df["route_shares"].fillna(df["fill_shares"]) * df["fill_price"]).abs()


def aggregate_cells(
    df: pd.DataFrame,
    *,
    cfg: ActiveAttributionConfig,
    by: Sequence[str],
    metrics: Sequence[str] = METRICS,
    rng_seed: int = 42,
) -> pd.DataFrame:
    """Per-cell stats with bootstrap CI.

    Output columns per (cell, metric):
      n, mean, median, std, mean_winsor, ci_lo, ci_hi, mean_weighted
    Cells with n < cfg.min_cell_n are tagged but kept.
    """
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["_w"] = _route_notional(df)
    rng = np.random.default_rng(rng_seed)
    rows: List[Dict] = []

    for keys, sub in df.groupby(list(by), dropna=False, sort=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        cell: Dict = {col: keys[i] for i, col in enumerate(by)}
        n_total = len(sub)
        for m in metrics:
            vals = sub[m].to_numpy(dtype=float)
            finite_mask = np.isfinite(vals)
            v = vals[finite_mask]
            n = int(v.size)
            if n == 0:
                cell[f"{m}_n"] = 0
                for k in ["mean", "median", "std", "mean_winsor", "ci_lo", "ci_hi", "mean_weighted"]:
                    cell[f"{m}_{k}"] = np.nan
                continue
            w = sub["_w"].to_numpy(dtype=float)[finite_mask]
            w_sum = float(w.sum())
            mean_w = float((v * w).sum() / w_sum) if w_sum > 0 else float("nan")
            v_winsor = winsorize_series(v.copy(), cfg.winsor_pct)
            cell[f"{m}_n"] = n
            cell[f"{m}_mean"] = float(v.mean())
            cell[f"{m}_median"] = float(np.median(v))
            cell[f"{m}_std"] = float(v.std(ddof=1)) if n > 1 else 0.0
            cell[f"{m}_mean_winsor"] = float(np.nanmean(v_winsor))
            cell[f"{m}_mean_weighted"] = mean_w
            ci_lo, ci_hi = bootstrap_ci_mean(v, cfg.bootstrap_n, rng=rng)
            cell[f"{m}_ci_lo"] = ci_lo
            cell[f"{m}_ci_hi"] = ci_hi
        cell["_n_total"] = n_total
        cell["_insufficient"] = n_total < cfg.min_cell_n
        rows.append(cell)

    out = pd.DataFrame(rows)
    return out


# ---------------------------------------------------------------------------
# Pairwise Welch t + BH-FDR
# ---------------------------------------------------------------------------
def pairwise_welch_bh(
    df: pd.DataFrame,
    *,
    metric: str,
    by: Sequence[str],
    cfg: ActiveAttributionConfig,
) -> pd.DataFrame:
    """All pairs of cells: Welch's t-test on `metric`, BH-FDR adjusted q-values.

    Returns DataFrame: cell_a (tuple), cell_b (tuple), n_a, n_b, mean_a, mean_b,
                       diff (a-b), t_stat, p_value, q_value (BH).
    Cells with n < cfg.min_cell_n are dropped from comparison.
    """
    if scipy_stats is None:
        raise RuntimeError("scipy is required for pairwise Welch t-test")
    if df.empty:
        return pd.DataFrame()

    samples: Dict[tuple, np.ndarray] = {}
    for keys, sub in df.groupby(list(by), dropna=False, sort=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        v = sub[metric].to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        if v.size >= cfg.min_cell_n:
            samples[keys] = v

    cells = sorted(samples.keys(), key=lambda k: tuple(str(x) for x in k))
    rows: List[Dict] = []
    for i in range(len(cells)):
        for j in range(i + 1, len(cells)):
            ka, kb = cells[i], cells[j]
            a, b = samples[ka], samples[kb]
            t, p = scipy_stats.ttest_ind(a, b, equal_var=False, nan_policy="omit")
            rows.append({
                "cell_a": ka, "cell_b": kb,
                "n_a": int(a.size), "n_b": int(b.size),
                "mean_a": float(a.mean()), "mean_b": float(b.mean()),
                "diff": float(a.mean() - b.mean()),
                "t_stat": float(t), "p_value": float(p),
            })

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    # Benjamini-Hochberg FDR
    p = out["p_value"].to_numpy()
    m = p.size
    order = np.argsort(p)
    ranked = p[order]
    q_sorted = ranked * m / (np.arange(1, m + 1))
    # Enforce monotone non-decreasing from the right
    q_sorted = np.minimum.accumulate(q_sorted[::-1])[::-1]
    q = np.empty(m)
    q[order] = np.clip(q_sorted, 0, 1)
    out["q_value"] = q
    out = out.sort_values("p_value").reset_index(drop=True)
    return out

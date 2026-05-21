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
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    from scipy import stats as scipy_stats
except ImportError:  # pragma: no cover
    scipy_stats = None  # type: ignore

from .config import ActiveAttributionConfig
from DataPipeline.storage.dto import FillMetricsQueryDTO
from .metrics import winsorize_series
from .protocols import AttributionConfigRepository, RegimeRepository

logger = logging.getLogger(__name__)

METRICS = ["is_bps", "vwap_bps", "reversal_1m_bps", "reversal_5m_bps", "reversal_30m_bps"]

# Default bucket specs (P0.2). Caller passes these (or override) and includes
# `{col}_bucket` in the `by` argument to slice cells by bucket.
DEFAULT_BUCKET_SPECS: Dict[str, List[float]] = {
    "pct_adv": [0.0, 0.005, 0.01, 0.05, 1.0],
    "participation_rate": [0.0, 0.05, 0.10, 0.20, 1.0],
}


def _format_bucket_label(lo: float, hi: float, is_last: bool) -> str:
    """ASCII-safe label like '[0.00%-0.50%)' or '[5.00%-100.00%]'."""
    bracket_hi = "]" if is_last else ")"
    return f"[{lo*100:.2f}%-{hi*100:.2f}%{bracket_hi}"


def add_bucket_columns(
    df: pd.DataFrame,
    bucket_specs: Optional[Dict[str, List[float]]] = None,
) -> pd.DataFrame:
    """Add `{col}_bucket` columns for each col in bucket_specs.

    Values <=0 or NaN -> bucket label NaN (excluded by groupby dropna). The
    last bin is closed on the right (include_lowest=False, right=True).
    """
    if bucket_specs is None:
        return df
    df = df.copy()
    for col, edges in bucket_specs.items():
        if col not in df.columns:
            continue
        edges = list(edges)
        if len(edges) < 2:
            continue
        labels = [
            _format_bucket_label(edges[i], edges[i + 1], is_last=(i == len(edges) - 2))
            for i in range(len(edges) - 1)
        ]
        df[f"{col}_bucket"] = pd.cut(
            df[col], bins=edges, labels=labels,
            include_lowest=True, right=True,
        ).astype(object)
    return df


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_fill_metrics(
    start_date_iso: str,
    end_date_iso: str,
    *,
    config_version: Optional[str] = None,
    regime_dim: Optional[str] = None,        # 'vol_regime' | 'liq_regime' | 'trend_regime'
    regime_repo: Optional[RegimeRepository] = None,
    config_repo: Optional[AttributionConfigRepository] = None,
    # Deprecated: kept for backward compatibility; will be removed in next iteration.
    db_path: Optional["Path"] = None,
) -> pd.DataFrame:
    """Load attribution rows for the requested window, optionally joined with one regime dim.

    Returns DataFrame with columns: OrderId, RouteId, FillId, order_as_of_date_iso,
      market_code, broker, algo, side, fill_shares, fill_price, route_shares,
      pct_adv, is_bps, vwap_bps, reversal_*, [regime_dim_col]

    Supports two calling conventions:
      1. (Preferred) Pass regime_repo and config_repo directly.
      2. (Legacy) Pass db_path to auto-create repositories.
    """
    # Legacy fallback: if db_path is given but no repos, create them.
    if regime_repo is None or config_repo is None:
        if db_path is None:
            raise ValueError(
                "Either (regime_repo + config_repo) or db_path must be provided"
            )
        from .repositories import SqliteAttributionConfigRepository, SqliteRegimeRepository
        if regime_repo is None:
            regime_repo = SqliteRegimeRepository(db_path)
        if config_repo is None:
            config_repo = SqliteAttributionConfigRepository(db_path)

    if config_version is None:
        cfg = config_repo.get_active_config()
        if cfg is None:
            raise RuntimeError("no active attribution config")
        config_version = cfg.version_id

    query = FillMetricsQueryDTO(
        start_date_iso=start_date_iso,
        end_date_iso=end_date_iso,
        config_version=config_version,
        regime_dim=regime_dim,
    )
    return regime_repo.get_fill_metrics(query)


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
    # For very large samples, cap to keep bootstrap O(n_resamples * n_cap).
    # CI for the mean stabilises well before n=50k; this keeps memory and
    # runtime bounded for full-window aggregation across many cells.
    n_cap = 50_000
    if n > n_cap:
        finite = rng.choice(finite, size=n_cap, replace=False)
        n = n_cap
    # Chunk resamples to cap peak memory at ~chunk*n*8 bytes
    target_bytes = 256 * 1024 * 1024  # 256 MiB
    chunk = max(1, min(n_resamples, target_bytes // max(1, n * 8)))
    means_parts = []
    remaining = n_resamples
    while remaining > 0:
        c = min(chunk, remaining)
        idx = rng.integers(0, n, size=(c, n))
        means_parts.append(finite[idx].mean(axis=1))
        remaining -= c
    means = np.concatenate(means_parts)
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
    bucket_specs: Optional[Dict[str, List[float]]] = None,
) -> pd.DataFrame:
    """Per-cell stats with bootstrap CI.

    Output columns per (cell, metric):
      n, mean, median, std, mean_winsor, ci_lo, ci_hi, mean_weighted
    Cells with n < cfg.min_cell_n are tagged but kept.

    If `bucket_specs` is provided, `{col}_bucket` columns are derived first;
    callers can include those in `by` to slice cells by bucket.
    """
    if df.empty:
        return pd.DataFrame()

    df = add_bucket_columns(df, bucket_specs)
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

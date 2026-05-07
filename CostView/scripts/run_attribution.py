"""
CLI: run attribution (Stage 10) for a date range, optionally inspect aggregates.

Examples:
  python -m CostView.scripts.run_attribution --start 2026-04-22 --end 2026-04-22
  python -m CostView.scripts.run_attribution --start 2025-09-25 --end 2026-04-22
  python -m CostView.scripts.run_attribution --inspect --start 2026-04-22 --end 2026-04-22 \\
                                             --by broker algo
  python -m CostView.scripts.run_attribution --inspect --by broker algo \\
                                             --regime-dim vol_regime --metric is_bps
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from CostView.src.attribution.aggregator import (
    aggregate_cells, load_fill_metrics, pairwise_welch_bh, METRICS,
)
from CostView.src.attribution.config import get_active_config, seed_default_config
from CostView.src.attribution.repositories import (
    SqliteAttributionConfigRepository,
    SqliteBarDataRepository,
    SqliteFillRepository,
    SqliteRegimeRepository,
)
from CostView.src.attribution.writer import run_metrics


def main(argv=None) -> int:
    p = argparse.ArgumentParser("run_attribution")
    p.add_argument("--start", required=True, help="ISO YYYY-MM-DD")
    p.add_argument("--end",   required=True, help="ISO YYYY-MM-DD")
    p.add_argument("--inspect", action="store_true",
                   help="Skip writer, just aggregate from existing rows")
    p.add_argument("--by", nargs="+", default=["broker", "algo"],
                   help="Group columns (default: broker algo)")
    p.add_argument("--regime-dim", default=None,
                   choices=[None, "vol_regime", "liq_regime", "trend_regime"])
    p.add_argument("--metric", default="is_bps", choices=METRICS,
                   help="Metric for pairwise Welch t-test (--inspect only)")
    p.add_argument("--top", type=int, default=20, help="Show top-N cells / pairs")
    p.add_argument("--config-version", default=None,
                   help="Use a specific attribution config_version (default: active)")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not args.inspect:
        # Create repository instances for dependency injection
        fill_repo = SqliteFillRepository()
        bar_repo = SqliteBarDataRepository()
        regime_repo = SqliteRegimeRepository()
        config_repo = SqliteAttributionConfigRepository()

        result = run_metrics(
            args.start, args.end,
            fill_repo=fill_repo,
            bar_repo=bar_repo,
            regime_repo=regime_repo,
            config_repo=config_repo,
        )
        print("== run_metrics ==")
        print(json.dumps(result, indent=2, default=str))

    # Aggregate
    config_repo = SqliteAttributionConfigRepository()
    seed_default_config(config_repo=config_repo)
    cfg = get_active_config(config_repo=config_repo)
    if cfg is None:
        print("ERROR: no active attribution config", file=sys.stderr)
        return 2

    by = list(args.by)
    if args.regime_dim:
        by = by + [args.regime_dim]

    regime_repo = SqliteRegimeRepository()
    df = load_fill_metrics(args.start, args.end,
                           config_version=args.config_version,
                           regime_dim=args.regime_dim,
                           regime_repo=regime_repo,
                           config_repo=config_repo)
    if df.empty:
        print("(no rows)")
        return 0

    agg = aggregate_cells(df, cfg=cfg, by=by)
    if agg.empty:
        print("(no cells)")
        return 0

    print()
    print(f"== cells (group by {by}, top {args.top} by row count) ==")
    cols = by + [
        "_n_total",
        f"{args.metric}_n", f"{args.metric}_mean", f"{args.metric}_median",
        f"{args.metric}_mean_winsor", f"{args.metric}_mean_weighted",
        f"{args.metric}_ci_lo", f"{args.metric}_ci_hi",
        "_insufficient",
    ]
    cols = [c for c in cols if c in agg.columns]
    show = agg.sort_values("_n_total", ascending=False).head(args.top)
    with_format = show[cols].to_string(index=False, float_format=lambda v: f"{v:+.2f}")
    print(with_format)

    # Pairwise stats on the chosen metric
    print()
    print(f"== pairwise Welch t + BH-FDR on {args.metric} (top {args.top} smallest p) ==")
    pairs = pairwise_welch_bh(df, metric=args.metric, by=by, cfg=cfg)
    if pairs.empty:
        print("(no qualifying pairs)")
    else:
        head = pairs.head(args.top).copy()
        for c in ("mean_a", "mean_b", "diff", "t_stat"):
            head[c] = head[c].map(lambda v: f"{v:+.2f}")
        for c in ("p_value", "q_value"):
            head[c] = head[c].map(lambda v: f"{v:.3g}")
        print(head.to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Backfill the regime layer for a date range.

Order:
  1. ensure_default_config() — seed v0_default if no active config
  2. market_index_loader.load_market_index(start, end)
  3. vol_regime.classify(start, end)
  4. liquidity_regime.classify(start, end)
  5. trend_regime.classify(start, end)
  6. fill_regime_tagger.tag_fills(start, end)

Each stage is wrapped in run_journal() → audit_pipeline_runs row.

Usage:
    python -m CostView.scripts.backfill_regime --start 2026-04-01 --end 2026-04-27
    python -m CostView.scripts.backfill_regime --start 2026-04-01 --end 2026-04-27 --skip-fetch
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from DataPipeline.analysis.regime import (
    fill_regime_tagger,
    liquidity_regime,
    market_index_loader,
    trend_regime,
    vol_regime,
)
from DataPipeline.analysis.regime.config import ensure_default_config
from DataPipeline.analysis.regime.run_journal import run_journal


def _wrap(stage_name: str, fn, start: str, end: str, version: str, **kwargs) -> int:
    with run_journal(stage_name, config_version=version, start=start, end=end) as rec:
        result = fn(start, end, **kwargs)
        if isinstance(result, dict):
            rec.set_rows(result.get("rows_upserted", 0))
            return int(result.get("rows_upserted", 0))
        rec.set_rows(int(result))
        return int(result)


def backfill(start: str, end: str, *, skip_fetch: bool = False,
             config_version: Optional[str] = None) -> dict:
    version = config_version or ensure_default_config()
    summary = {"config_version": version, "stages": {}}

    if not skip_fetch:
        n = _wrap("market_index_loader", market_index_loader.load_market_index,
                  start, end, version)
        summary["stages"]["market_index_loader"] = n
    else:
        print("[backfill] --skip-fetch: assuming daily_market_index already populated")

    summary["stages"]["vol_regime"] = _wrap(
        "vol_regime", vol_regime.classify, start, end, version,
        config_version=version,
    )
    summary["stages"]["liquidity_regime"] = _wrap(
        "liquidity_regime", liquidity_regime.classify, start, end, version,
        config_version=version,
    )
    summary["stages"]["trend_regime"] = _wrap(
        "trend_regime", trend_regime.classify, start, end, version,
        config_version=version,
    )

    # fill_regime_tagger has different signature (returns dict)
    with run_journal("fill_regime_tagger", config_version=version, start=start, end=end) as rec:
        s = fill_regime_tagger.tag_fills(start, end, config_version=version)
        rec.set_rows(s["rows_upserted"])
        summary["stages"]["fill_regime_tagger"] = s

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill regime layer")
    parser.add_argument("--start", required=True, help="ISO date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="ISO date YYYY-MM-DD")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip Bloomberg fetch (use existing daily_market_index)")
    parser.add_argument("--config-version", default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        summary = backfill(args.start, args.end,
                           skip_fetch=args.skip_fetch,
                           config_version=args.config_version)
    except Exception as e:
        print(f"[backfill] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"[backfill] done: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

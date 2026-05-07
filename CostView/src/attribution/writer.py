"""
Per-fill attribution metrics writer (Stage 10 of the regime/attribution pipeline).

For each order_as_of_date in [start, end]:
  1. Load fills + route ticker/side from processed_fills.db (via FillRepository)
  2. Load 1-min bar panels for distinct tickers from raw_bdib.db (via BarDataRepository)
  3. Compute arrival_px / interval_vwap / mid_at_fill / mid+N (per active config)
  4. Compute is_bps / vwap_bps / reversal_Nm_bps (side-aware)
  5. Pull pct_adv from bdib_daily_summary.adv_20d (via BarDataRepository)
  6. Batch UPSERT into regime.db.fill_attribution_metrics (via RegimeRepository)
  7. Write audit_pipeline_runs row (via RegimeRepository)

Downstream (Stage 11 = aggregator) reads back this table and builds the
broker x algo x regime cells with bootstrap CI + Welch t + BH-FDR.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

from CostView.src.regime.market_code import derive_market_code

from .benchmarks import (
    add_minutes,
    compute_route_arrival_minutes,
    interval_volume,
    interval_vwap,
    lookup_mid_at_or_after,
    _floor_to_minute,
)
from .config import ActiveAttributionConfig
from .dto import AttributionRowDTO, PipelineRunDTO, PipelineRunResultDTO
from .metrics import parse_side, reversal_bps, slippage_bps
from .protocols import (
    AttributionConfigRepository,
    BarDataRepository,
    FillRepository,
    RegimeRepository,
)

logger = logging.getLogger(__name__)

SOURCE_VERSION = "attribution.metrics.writer/1"

__FLAG_NO_ARRIVAL = 1
_FLAG_NO_INTERVAL_VWAP = 2
_FLAG_NO_MID_AT_FILL = 4
_FLAG_NO_MID_PLUS_BASE = 8  # bit position multiplier for reversal windows


# ---------------------------------------------------------------------------
# Per-date worker
# ---------------------------------------------------------------------------
def _iso_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _process_one_date(
    yyyymmdd: str,
    cfg: ActiveAttributionConfig,
    fill_repo: FillRepository,
    bar_repo: BarDataRepository,
    regime_repo: RegimeRepository,
    now_iso: str,
) -> Tuple[int, int]:
    """Process one trade date. Returns (rows_written, rows_skipped)."""
    fills_df = fill_repo.get_fills_for_date(yyyymmdd)
    if fills_df.empty:
        return 0, 0
    n_total = len(fills_df)

    # Drop fills lacking ticker / side (cannot benchmark).
    fills_df["side_int"] = fills_df["Side"].map(parse_side)
    bad_mask = fills_df["equ_ticker"].isna() | (fills_df["equ_ticker"] == "") | fills_df["side_int"].isna()
    n_skip_meta = int(bad_mask.sum())
    fills_df = fills_df[~bad_mask].copy()
    if fills_df.empty:
        return 0, n_skip_meta

    distinct_tickers = sorted(fills_df["equ_ticker"].dropna().unique().tolist())
    panels = bar_repo.get_bar_panels_for_date(yyyymmdd, distinct_tickers)
    adv_map = bar_repo.get_adv_map(yyyymmdd, distinct_tickers)
    route_minutes = compute_route_arrival_minutes(fills_df)  # idx (OrderId, RouteId)

    # Per-route participation cache:
    #   participation_rate = route_shares / sum(BDIB volume over [first_min, last_min])
    # Build once per (OrderId, RouteId) using the route's ticker + window.
    route_partic: Dict[Tuple[str, str], Optional[float]] = {}
    route_keys = (
        fills_df[["OrderId", "RouteId", "equ_ticker", "RouteShares"]]
        .drop_duplicates(subset=["OrderId", "RouteId"])
    )
    for r in route_keys.itertuples(index=False):
        key = (r.OrderId, r.RouteId)
        try:
            first_m, last_m = route_minutes.loc[key]
        except KeyError:
            route_partic[key] = None
            continue
        panel = panels.get(r.equ_ticker)
        if panel is None or not first_m or not last_m:
            route_partic[key] = None
            continue
        ivol = interval_volume(panel, first_m, last_m)
        rs = r.RouteShares
        if ivol is None or ivol <= 0 or rs is None or not pd.notna(rs) or float(rs) <= 0:
            route_partic[key] = None
            continue
        pr = float(rs) / float(ivol)
        # Schema constraint: participation_rate in [0, 5]. Off-book / dark
        # fills can push the ratio above bar interval volume; cap to None
        # when it exceeds 5x (clearly outside on-book interpretation).
        if pr < 0 or pr > 5.0:
            route_partic[key] = None
        else:
            route_partic[key] = pr

    iso_date = _iso_date(yyyymmdd)
    rev_windows = list(cfg.reversal_windows_min)

    rows: List[tuple] = []
    for fill in fills_df.itertuples(index=False):
        ticker = fill.equ_ticker
        side = int(fill.side_int)
        fill_price = float(fill.FillPrice)
        fill_shares = float(fill.FillShares)
        if not (math.isfinite(fill_price) and fill_price > 0):
            continue
        if not (math.isfinite(fill_shares) and fill_shares > 0):
            continue

        market_code = derive_market_code(fill.Exchange, None)
        if market_code is None:
            # No market => cannot FK; skip silently (already excluded by tagger).
            continue

        panel = panels.get(ticker)
        flags = 0
        arrival_px = None
        ivwap = None
        mid_at = None
        mids_plus: Dict[int, Optional[float]] = {n: None for n in rev_windows}

        try:
            first_min, last_min = route_minutes.loc[(fill.OrderId, fill.RouteId)]
        except KeyError:
            first_min, last_min = "", ""
        fill_minute = _floor_to_minute(fill.mkt_timestamp)

        if panel is not None:
            arrival_px = lookup_mid_at_or_after(panel, first_min) if first_min else None
            ivwap = interval_vwap(panel, first_min, last_min) if (first_min and last_min) else None
            mid_at = lookup_mid_at_or_after(panel, fill_minute) if fill_minute else None
            for n in rev_windows:
                later = add_minutes(fill_minute, n) if fill_minute else ""
                mids_plus[n] = lookup_mid_at_or_after(panel, later) if later else None

        if arrival_px is None:
            flags |= _FLAG_NO_ARRIVAL
        if ivwap is None:
            flags |= _FLAG_NO_INTERVAL_VWAP
        if mid_at is None:
            flags |= _FLAG_NO_MID_AT_FILL
        for idx, n in enumerate(rev_windows):
            if mids_plus[n] is None:
                flags |= (_FLAG_NO_MID_PLUS_BASE << idx)

        is_bps = slippage_bps(side, fill_price, arrival_px)
        vwap_b = slippage_bps(side, fill_price, ivwap)
        rev_vals: List[Optional[float]] = [
            reversal_bps(side, fill_price, mids_plus[n]) for n in rev_windows
        ]
        # Pad to 3 windows for fixed schema (1m,5m,30m)
        while len(rev_vals) < 3:
            rev_vals.append(None)
        rev1, rev5, rev30 = rev_vals[0], rev_vals[1], rev_vals[2]

        adv = adv_map.get(ticker)
        pct_adv: Optional[float] = None
        if adv is not None and adv > 0:
            # %ADV is per-fill share count divided by ADV. (Cell aggregator
            # weighs by route notional; this is just per-fill share footprint.)
            pct_adv = float(fill_shares) / float(adv)

        rows.append(AttributionRowDTO(
            order_id=str(fill.OrderId),
            route_id=str(fill.RouteId),
            fill_id=str(fill.FillId),
            order_as_of_date_iso=iso_date,
            config_version=cfg.version_id,
            market_code=market_code,
            broker=fill.Broker,
            algo=fill.algo,
            side=side,
            fill_shares=fill_shares,
            fill_price=fill_price,
            route_shares=float(fill.RouteShares) if pd.notna(fill.RouteShares) else None,
            pct_adv=pct_adv,
            participation_rate=route_partic.get((fill.OrderId, fill.RouteId)),
            arrival_px=arrival_px,
            interval_vwap=ivwap,
            mid_at_fill=mid_at,
            mid_fill_plus_1m=mids_plus.get(rev_windows[0] if len(rev_windows) > 0 else None),
            mid_fill_plus_5m=mids_plus.get(rev_windows[1] if len(rev_windows) > 1 else None),
            mid_fill_plus_30m=mids_plus.get(rev_windows[2] if len(rev_windows) > 2 else None),
            is_bps=is_bps,
            vwap_bps=vwap_b,
            reversal_1m_bps=rev1,
            reversal_5m_bps=rev5,
            reversal_30m_bps=rev30,
            data_quality_flags=flags,
            source_version=SOURCE_VERSION,
            ingested_at=now_iso,
        ))

    if not rows:
        return 0, n_skip_meta + (n_total - len(fills_df))

    # Batch UPSERT via Repository
    written = regime_repo.upsert_attribution_metrics(rows)

    skipped = (n_total - len(fills_df)) + (len(fills_df) - len(rows))
    return written, skipped


# ----------------------------------------------------------------------------
# Public driver
# ----------------------------------------------------------------------------
def run_metrics(
    start_date_iso: str,
    end_date_iso: str,
    *,
    fill_repo: FillRepository,
    bar_repo: BarDataRepository,
    regime_repo: RegimeRepository,
    config_repo: AttributionConfigRepository,
) -> Dict:
    """Compute attribution metrics for all dates in [start, end] inclusive.

    Inputs are ISO YYYY-MM-DD; converts to YYYYMMDD for cross-DB queries.
    All database access is via the provided Repository interfaces.
    """
    config_repo.ensure_schema_current()
    cfg_id = config_repo.seed_default_config()
    cfg_dto = config_repo.get_active_config()
    if cfg_dto is None:
        raise RuntimeError("no active attribution config")
    cfg = ActiveAttributionConfig(
        version_id=cfg_dto.version_id,
        bench_methods=cfg_dto.bench_methods,
        reversal_windows_min=cfg_dto.reversal_windows_min,
        winsor_pct=cfg_dto.winsor_pct,
        adv_window_days=cfg_dto.adv_window_days,
        bootstrap_n=cfg_dto.bootstrap_n,
        min_cell_n=cfg_dto.min_cell_n,
        description=cfg_dto.description,
    )

    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    yyyymmdd_start = start_date_iso.replace("-", "")
    yyyymmdd_end = end_date_iso.replace("-", "")

    # Audit run row (status='running' first, then update)
    run_started = now_iso
    run_dto = PipelineRunDTO(
        stage_name="attribution_metrics",
        run_started_at=run_started,
        status="running",
        target_start_date=start_date_iso,
        target_end_date=end_date_iso,
        config_version=cfg.version_id,
        schema_version=3,
    )
    run_id = regime_repo.insert_pipeline_run(run_dto)

    rows_written = 0
    rows_skipped = 0
    failed = False
    err: Optional[str] = None
    t0 = time.time()
    try:
        # Discover dates with fills in range
        dates = fill_repo.get_distinct_dates_in_range(yyyymmdd_start, yyyymmdd_end)
        logger.info("attribution_metrics: %d dates from %s to %s",
                    len(dates), start_date_iso, end_date_iso)

        for d in dates:
            d_iso = _iso_date(d)
            t = time.time()
            w, s = _process_one_date(d, cfg, fill_repo, bar_repo, regime_repo, now_iso)
            rows_written += w
            rows_skipped += s
            logger.info("  %s: written=%d skipped=%d (%.2fs)", d_iso, w, s, time.time() - t)
    except Exception as e:
        failed = True
        err = repr(e)
        raise
    finally:
        duration_sec = round(time.time() - t0, 2)
        finished_at = dt.datetime.now().isoformat(timespec="seconds")
        result_dto = PipelineRunResultDTO(
            run_id=run_id,
            run_finished_at=finished_at,
            status="failed" if failed else "success",
            rows_written=rows_written,
            rows_updated=0,
            error_message=err,
            duration_sec=duration_sec,
        )
        regime_repo.update_pipeline_run(result_dto)
        # P2.9: research snapshot hash (only on success).
        if not failed:
            try:
                sha, total = regime_repo.compute_snapshot_hash(
                    cfg.version_id, start_date_iso, end_date_iso,
                )
                regime_repo.write_research_snapshot(
                    run_id=run_id,
                    config_version=cfg.version_id,
                    start_date_iso=start_date_iso,
                    end_date_iso=end_date_iso,
                    rows_written=rows_written,
                    rows_total=total,
                    snapshot_sha256=sha,
                    created_at=finished_at,
                )
                logger.info("snapshot sha256=%s rows_total=%d", sha[:16], total)
            except Exception as e:
                logger.warning("snapshot write failed: %r", e)

    return {
        "config_version": cfg.version_id,
        "rows_written": rows_written,
        "rows_skipped": rows_skipped,
        "duration_sec": duration_sec,
    }

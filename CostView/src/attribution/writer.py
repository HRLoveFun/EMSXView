"""
Per-fill attribution metrics writer (Stage 10 of the regime/attribution pipeline).

For each order_as_of_date in [start, end]:
  1. Load fills + route ticker/side from processed_fills.db
  2. Load 1-min bar panels for distinct tickers from raw_bdib.db
  3. Compute arrival_px / interval_vwap / mid_at_fill / mid+N (per active config)
  4. Compute is_bps / vwap_bps / reversal_Nm_bps (side-aware)
  5. Pull pct_adv from bdib_daily_summary.adv_20d (proxy for ADV)
  6. Batch UPSERT into regime.db.fill_attribution_metrics (PK includes config_version)
  7. Write audit_pipeline_runs row

Downstream (Stage 11 = aggregator) reads back this table and builds the
broker x algo x regime cells with bootstrap CI + Welch t + BH-FDR.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import math
import sqlite3
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from CostView.src.regime.market_code import derive_market_code
from CostView.src.regime.schema import REGIME_DB_PATH, connect as connect_regime, ensure_schema_current

from .benchmarks import (
    PROCESSED_FILLS_DB,
    RAW_BDIB_DB,
    add_minutes,
    compute_route_arrival_minutes,
    interval_volume,
    interval_vwap,
    load_bar_panels_for_date,
    load_fills_for_date,
    lookup_mid_at_or_after,
    _floor_to_minute,
)
from .config import ActiveAttributionConfig, get_active_config, seed_default_config
from .metrics import parse_side, reversal_bps, slippage_bps

logger = logging.getLogger(__name__)

SOURCE_VERSION = "attribution.metrics.writer/1"

_FLAG_NO_ARRIVAL = 1
_FLAG_NO_INTERVAL_VWAP = 2
_FLAG_NO_MID_AT_FILL = 4
_FLAG_NO_MID_PLUS_BASE = 8  # bit position multiplier for reversal windows


# ----------------------------------------------------------------------------
# Snapshot table (P2.9) - lazy create-if-missing
# ----------------------------------------------------------------------------
_SNAPSHOT_DDL = """
CREATE TABLE IF NOT EXISTS audit_research_snapshots (
    run_id           INTEGER PRIMARY KEY,
    stage_name       TEXT NOT NULL,
    config_version   TEXT NOT NULL,
    start_date       TEXT NOT NULL,
    end_date         TEXT NOT NULL,
    rows_written     INTEGER NOT NULL,
    rows_total       INTEGER NOT NULL,
    snapshot_sha256  TEXT NOT NULL,
    created_at       TIMESTAMP NOT NULL
)
"""


def _compute_snapshot_sha256(
    regime_conn: sqlite3.Connection,
    config_version: str,
    start_iso: str,
    end_iso: str,
) -> Tuple[str, int]:
    """Return (sha256_hex, total_rows_in_range) over a deterministic top-100
    sample of (OrderId, RouteId, FillId) keys + their is_bps values.

    Uses ORDER BY ascending PK so the sample is reproducible across runs.
    """
    cur = regime_conn.execute(
        """SELECT OrderId, RouteId, FillId, order_as_of_date_iso, is_bps
           FROM fill_attribution_metrics
           WHERE config_version=? AND order_as_of_date_iso BETWEEN ? AND ?
           ORDER BY OrderId, RouteId, FillId, order_as_of_date_iso
           LIMIT 100""",
        (config_version, start_iso, end_iso),
    )
    h = hashlib.sha256()
    for row in cur.fetchall():
        oid, rid, fid, d, isb = row
        h.update(f"{oid}|{rid}|{fid}|{d}|{isb}\n".encode("utf-8"))
    total = regime_conn.execute(
        """SELECT COUNT(*) FROM fill_attribution_metrics
           WHERE config_version=? AND order_as_of_date_iso BETWEEN ? AND ?""",
        (config_version, start_iso, end_iso),
    ).fetchone()[0]
    return h.hexdigest(), int(total)


# ----------------------------------------------------------------------------
# ADV loading
# ----------------------------------------------------------------------------
def _load_adv_map(
    bdib_conn: sqlite3.Connection,
    yyyymmdd: str,
    tickers: List[str],
) -> Dict[str, float]:
    """Map equ_ticker -> adv_20d for the given trade_date."""
    if not tickers:
        return {}
    out: Dict[str, float] = {}
    CHUNK = 500
    for i in range(0, len(tickers), CHUNK):
        batch = tickers[i:i + CHUNK]
        ph = ",".join(["?"] * len(batch))
        sql = (
            f"SELECT equ_ticker, adv_20d FROM bdib_daily_summary "
            f"WHERE trade_date=? AND equ_ticker IN ({ph})"
        )
        for tk, adv in bdib_conn.execute(sql, [yyyymmdd] + batch).fetchall():
            if adv is not None and adv > 0:
                out[tk] = float(adv)
    return out


# ----------------------------------------------------------------------------
# Per-date worker
# ----------------------------------------------------------------------------
def _iso_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _process_one_date(
    yyyymmdd: str,
    cfg: ActiveAttributionConfig,
    fills_conn: sqlite3.Connection,
    bdib_conn: sqlite3.Connection,
    regime_conn: sqlite3.Connection,
    now_iso: str,
) -> Tuple[int, int]:
    """Process one trade date. Returns (rows_written, rows_skipped)."""
    fills_df = load_fills_for_date(fills_conn, yyyymmdd)
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
    panels = load_bar_panels_for_date(bdib_conn, yyyymmdd, distinct_tickers)
    adv_map = _load_adv_map(bdib_conn, yyyymmdd, distinct_tickers)
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

        rows.append((
            str(fill.OrderId), str(fill.RouteId), str(fill.FillId), iso_date, cfg.version_id,
            market_code, fill.Broker, fill.algo, side, fill_shares, fill_price,
            float(fill.RouteShares) if pd.notna(fill.RouteShares) else None,
            pct_adv, route_partic.get((fill.OrderId, fill.RouteId)),
            arrival_px, ivwap,
            mid_at, mids_plus.get(rev_windows[0] if len(rev_windows) > 0 else None),
            mids_plus.get(rev_windows[1] if len(rev_windows) > 1 else None),
            mids_plus.get(rev_windows[2] if len(rev_windows) > 2 else None),
            is_bps, vwap_b, rev1, rev5, rev30,
            flags, SOURCE_VERSION, now_iso,
        ))

    if not rows:
        return 0, n_skip_meta + (n_total - len(fills_df))

    # Batch UPSERT
    BATCH = 5000
    written = 0
    sql = """
    INSERT INTO fill_attribution_metrics
      (OrderId, RouteId, FillId, order_as_of_date_iso, config_version,
       market_code, broker, algo, side, fill_shares, fill_price,
       route_shares, pct_adv, participation_rate,
       arrival_px, interval_vwap,
       mid_at_fill, mid_fill_plus_1m, mid_fill_plus_5m, mid_fill_plus_30m,
       is_bps, vwap_bps, reversal_1m_bps, reversal_5m_bps, reversal_30m_bps,
       data_quality_flags, source_version, ingested_at)
    VALUES (?,?,?,?,?, ?,?,?,?,?,?, ?,?,?, ?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?)
    ON CONFLICT(OrderId, RouteId, FillId, order_as_of_date_iso, config_version)
    DO UPDATE SET
       market_code=excluded.market_code,
       broker=excluded.broker, algo=excluded.algo, side=excluded.side,
       fill_shares=excluded.fill_shares, fill_price=excluded.fill_price,
       route_shares=excluded.route_shares, pct_adv=excluded.pct_adv,
       participation_rate=excluded.participation_rate,
       arrival_px=excluded.arrival_px, interval_vwap=excluded.interval_vwap,
       mid_at_fill=excluded.mid_at_fill,
       mid_fill_plus_1m=excluded.mid_fill_plus_1m,
       mid_fill_plus_5m=excluded.mid_fill_plus_5m,
       mid_fill_plus_30m=excluded.mid_fill_plus_30m,
       is_bps=excluded.is_bps, vwap_bps=excluded.vwap_bps,
       reversal_1m_bps=excluded.reversal_1m_bps,
       reversal_5m_bps=excluded.reversal_5m_bps,
       reversal_30m_bps=excluded.reversal_30m_bps,
       data_quality_flags=excluded.data_quality_flags,
       source_version=excluded.source_version,
       ingested_at=excluded.ingested_at
    """
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        regime_conn.execute("BEGIN IMMEDIATE")
        try:
            regime_conn.executemany(sql, chunk)
            regime_conn.execute("COMMIT")
            written += len(chunk)
        except Exception:
            regime_conn.execute("ROLLBACK")
            raise

    skipped = (n_total - len(fills_df)) + (len(fills_df) - len(rows))
    return written, skipped


# ----------------------------------------------------------------------------
# Public driver
# ----------------------------------------------------------------------------
def run_metrics(
    start_date_iso: str,
    end_date_iso: str,
    db_path: Path = REGIME_DB_PATH,
) -> Dict:
    """Compute attribution metrics for all dates in [start, end] inclusive.

    Inputs are ISO YYYY-MM-DD; converts to YYYYMMDD for cross-DB queries.
    """
    ensure_schema_current(db_path)
    cfg_id = seed_default_config(db_path)
    cfg = get_active_config(db_path)
    if cfg is None:
        raise RuntimeError("no active attribution config")

    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    yyyymmdd_start = start_date_iso.replace("-", "")
    yyyymmdd_end = end_date_iso.replace("-", "")

    regime_conn = connect_regime(db_path)
    fills_conn = sqlite3.connect(str(PROCESSED_FILLS_DB))
    bdib_conn = sqlite3.connect(str(RAW_BDIB_DB))

    # Audit run row (status='running' first, then update)
    run_started = now_iso
    cur = regime_conn.execute(
        """INSERT INTO audit_pipeline_runs
           (stage_name, run_started_at, status, target_start_date,
            target_end_date, config_version, schema_version)
           VALUES (?,?,?,?,?,?,?)""",
        ("attribution_metrics", run_started, "running",
         start_date_iso, end_date_iso, cfg.version_id, 3),
    )
    run_id = cur.lastrowid

    rows_written = 0
    rows_skipped = 0
    failed = False
    err: Optional[str] = None
    t0 = time.time()
    try:
        # Discover dates with fills in range
        dates_df = pd.read_sql_query(
            "SELECT DISTINCT order_as_of_date FROM processed_fills "
            "WHERE order_as_of_date BETWEEN ? AND ? "
            "  AND ExecType='FILL' AND FillShares>0 AND FillPrice>0 "
            "ORDER BY order_as_of_date",
            fills_conn, params=(yyyymmdd_start, yyyymmdd_end),
        )
        dates = dates_df["order_as_of_date"].tolist()
        logger.info("attribution_metrics: %d dates from %s to %s",
                    len(dates), start_date_iso, end_date_iso)

        for d in dates:
            d_iso = _iso_date(d)
            t = time.time()
            w, s = _process_one_date(d, cfg, fills_conn, bdib_conn, regime_conn, now_iso)
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
        regime_conn.execute(
            """UPDATE audit_pipeline_runs
               SET run_finished_at=?, status=?, rows_written=?, rows_updated=?,
                   error_message=?, duration_sec=?
               WHERE run_id=?""",
            (finished_at, "failed" if failed else "success",
             rows_written, 0, err, duration_sec, run_id),
        )
        # P2.9: research snapshot hash (only on success).
        if not failed:
            try:
                regime_conn.execute(_SNAPSHOT_DDL)
                sha, total = _compute_snapshot_sha256(
                    regime_conn, cfg.version_id, start_date_iso, end_date_iso,
                )
                regime_conn.execute(
                    """INSERT OR REPLACE INTO audit_research_snapshots
                       (run_id, stage_name, config_version, start_date,
                        end_date, rows_written, rows_total, snapshot_sha256,
                        created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (run_id, "attribution_metrics", cfg.version_id,
                     start_date_iso, end_date_iso, rows_written, total,
                     sha, finished_at),
                )
                regime_conn.commit()
                logger.info("snapshot sha256=%s rows_total=%d", sha[:16], total)
            except Exception as e:
                logger.warning("snapshot write failed: %r", e)
        regime_conn.close()
        fills_conn.close()
        bdib_conn.close()

    return {
        "config_version": cfg.version_id,
        "rows_written": rows_written,
        "rows_skipped": rows_skipped,
        "duration_sec": duration_sec,
    }

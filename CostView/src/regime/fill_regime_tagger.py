"""
Stage 8: tag every fill in processed_fills with regime labels.

Reads from CostView/data/processed_fills.db (cross-DB) and looks up the active
config_version's daily_*_regime + macro calendar; writes one row per
(OrderId, RouteId, FillId, order_as_of_date_iso, config_version) into
fill_regime_labels (append-only across config drift).

Notes
-----
- order_as_of_date in processed_fills is legacy 'YYYYMMDD'; we convert to
  'YYYY-MM-DD' (regime-layer standard) at read time.
- market_code derived from (Exchange, Currency) via regime.market_code.derive_market_code.
  Fills with unknown market_code are SKIPPED with a warning (counted in run summary).
- time_bucket is computed via regime.time_bucket.assign_time_bucket using the
  fill's exchange_exec_time (exchange-local HH:MM:SS). Only the 5 enabled
  markets {US, AU, JP, LN, EU} are tagged; others remain NULL.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from CostView.src.processing_config import ProcessingConfig as PCConfig
from DataPipeline.src.storage.connection import ConnectionManager, AccessTier
from CostView.src.exchange_tz import convert_ny_to_local, get_exchange_timezone
from CostView.src.regime.config import get_active_config, get_config
from CostView.src.regime.market_code import derive_market_code
from CostView.src.regime.schema import REGIME_DB_PATH, connect, ensure_schema_current
from CostView.src.regime.time_bucket import ENABLED_MARKETS, assign_time_bucket

logger = logging.getLogger(__name__)


def _to_iso(ymd: str) -> Optional[str]:
    """'20260427' → '2026-04-27'; passthrough if already ISO; None on failure."""
    if not ymd or not isinstance(ymd, str):
        return None
    s = ymd.strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _load_regimes(db_path: Path, version_id: str, dates_iso: List[str]) -> Dict[Tuple[str, str], Dict]:
    """Return {(market_code, trade_date_iso): {vol, liq, trend}} for the given dates."""
    if not dates_iso:
        return {}
    conn = connect(db_path)
    placeholders = ",".join(["?"] * len(dates_iso))
    try:
        sql = f"""
            SELECT market_code, trade_date, vol_regime, NULL AS liq_regime, NULL AS trend_regime
            FROM daily_vol_regime
            WHERE config_version = ? AND trade_date IN ({placeholders})
            UNION ALL
            SELECT market_code, trade_date, NULL, liq_regime, NULL
            FROM daily_liquidity_regime
            WHERE config_version = ? AND trade_date IN ({placeholders})
            UNION ALL
            SELECT market_code, trade_date, NULL, NULL, trend_regime
            FROM daily_trend_regime
            WHERE config_version = ? AND trade_date IN ({placeholders})
        """
        params = [version_id, *dates_iso, version_id, *dates_iso, version_id, *dates_iso]
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    out: Dict[Tuple[str, str], Dict] = {}
    for mc, td, vol, liq, trend in rows:
        slot = out.setdefault((mc, td), {"vol": None, "liq": None, "trend": None})
        if vol is not None:
            slot["vol"] = vol
        if liq is not None:
            slot["liq"] = liq
        if trend is not None:
            slot["trend"] = trend
    return out


def _load_macro_windows(db_path: Path, dates_iso: List[str]) -> set:
    """Return set of (market_code, trade_date_iso) within any macro event window."""
    if not dates_iso:
        return set()
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event_date, market_code, window_days FROM ref_macro_event_calendar"
        ).fetchall()
    finally:
        conn.close()
    target_dates = {dt.date.fromisoformat(d) for d in dates_iso}
    flagged: set = set()
    for ed, mc, win in rows:
        try:
            d0 = dt.date.fromisoformat(ed)
        except ValueError:
            continue
        for offset in range(-int(win), int(win) + 1):
            d = d0 + dt.timedelta(days=offset)
            if d in target_dates:
                flagged.add((mc, d.isoformat()))
    return flagged


def tag_fills(
    start_date: str,
    end_date: str,
    db_path: Path = REGIME_DB_PATH,
    fills_db_path: Path = PCConfig.PROCESSED_FILLS_DB,
    config_version: Optional[str] = None,
) -> Dict[str, int]:
    """Tag fills whose order_as_of_date falls in [start_date, end_date] (ISO).

    Returns {"total_fills", "skipped_no_market", "rows_upserted"}.
    """
    ensure_schema_current(db_path)
    cfg = get_config(config_version, db_path) if config_version else get_active_config(db_path)
    if not cfg:
        raise RuntimeError("No active regime config")
    version_id = cfg["version_id"]

    # Convert ISO date range → legacy YYYYMMDD for processed_fills query.
    start_legacy = start_date.replace("-", "")
    end_legacy = end_date.replace("-", "")

    fconn_mgr = ConnectionManager(path_overrides={"processed_fills": Path(fills_db_path)})
    fconn = fconn_mgr.get_connection("processed_fills", AccessTier.READ).raw_connection
    try:
        cols = {c[1] for c in fconn.execute(
            f"PRAGMA table_info({PCConfig.PROCESSED_FILLS_TABLE})"
        ).fetchall()}
        has_currency = "Currency" in cols
        currency_col = "Currency" if has_currency else "NULL AS Currency"
        # DateTimeOfFill is the canonical NY-time ISO string with explicit
        # offset; this is the only timestamp safe to convert to exchange-local.
        # `local_fill_datetime`/`exchange_exec_time` are NY-time literal strings
        # in upstream processed_fills (misnamed historically), so we don't use
        # them here.
        df = pd.read_sql_query(
            f"""SELECT OrderId, RouteId, FillId, order_as_of_date, Exchange, {currency_col}, DateTimeOfFill
                FROM {PCConfig.PROCESSED_FILLS_TABLE}
                WHERE order_as_of_date BETWEEN ? AND ?""",
            fconn,
            params=(start_legacy, end_legacy),
        )
    finally:
        fconn.close()

    total = len(df)
    if total == 0:
        return {"total_fills": 0, "skipped_no_market": 0, "rows_upserted": 0}

    df["trade_date_iso"] = df["order_as_of_date"].map(_to_iso)
    df["market_code"] = [derive_market_code(e, c) for e, c in zip(df["Exchange"], df["Currency"])]

    invalid = df[df["market_code"].isna() | df["trade_date_iso"].isna()]
    skipped = len(invalid)
    df = df.dropna(subset=["market_code", "trade_date_iso"])
    if df.empty:
        return {"total_fills": total, "skipped_no_market": skipped, "rows_upserted": 0}

    dates_iso = sorted(df["trade_date_iso"].unique().tolist())
    regimes = _load_regimes(db_path, version_id, dates_iso)
    macro_flags = _load_macro_windows(db_path, dates_iso)

    src_version = f"fill_regime_tagger@{version_id}"
    ingested_at = dt.datetime.now().isoformat(timespec="seconds")
    rows: List[tuple] = []
    tod_tagged = 0
    tod_parse_fail = 0
    # Pre-compute local time strings only for fills whose market is TOD-enabled.
    # Use the original Exchange code (not the folded EU market_code) to look up
    # the IANA timezone, since EU is an aggregate not a single tz.
    df["local_hhmmss"] = None
    enabled_mask = df["market_code"].isin(ENABLED_MARKETS) & df["DateTimeOfFill"].notna()
    if enabled_mask.any():
        for idx in df.index[enabled_mask]:
            raw = df.at[idx, "DateTimeOfFill"]
            exch = df.at[idx, "Exchange"]
            try:
                # DateTimeOfFill is ISO with explicit offset (e.g. '...-04:00').
                ny_dt = dt.datetime.fromisoformat(str(raw))
            except (TypeError, ValueError):
                tod_parse_fail += 1
                continue
            # convert_ny_to_local needs a NY-time datetime; DateTimeOfFill's
            # offset already encodes that, so we pass it through fromisoformat
            # and let the helper astimezone() it. Unknown exch → tz lookup
            # returns None → bucket stays None.
            if get_exchange_timezone(str(exch)) is None:
                continue
            local_dt = convert_ny_to_local(ny_dt, str(exch))
            if local_dt is None:
                continue
            df.at[idx, "local_hhmmss"] = local_dt.strftime("%H:%M:%S")

    for _i, r in df.iterrows():
        key = (r["market_code"], r["trade_date_iso"])
        slot = regimes.get(key, {})
        macro = 1 if key in macro_flags else 0
        tod = assign_time_bucket(r["market_code"], r.get("local_hhmmss"))
        if tod is not None:
            tod_tagged += 1
        rows.append((
            str(r["OrderId"]) if r["OrderId"] is not None else "",
            str(r["RouteId"]) if r["RouteId"] is not None else "",
            str(r["FillId"]) if r["FillId"] is not None else "",
            r["trade_date_iso"],
            version_id,
            r["trade_date_iso"],          # trade_date column duplicates order_as_of_date_iso for now
            r["market_code"],
            slot.get("vol"),
            slot.get("liq"),
            slot.get("trend"),
            macro,
            tod,
            src_version,
            ingested_at,
        ))

    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for i in range(0, len(rows), 5000):
            conn.executemany(
                """INSERT INTO fill_regime_labels (
                    OrderId, RouteId, FillId, order_as_of_date_iso, config_version,
                    trade_date, market_code, vol_regime, liq_regime, trend_regime,
                    macro_event_window, time_bucket, source_version, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(OrderId, RouteId, FillId, order_as_of_date_iso, config_version)
                DO UPDATE SET
                    trade_date         = excluded.trade_date,
                    market_code        = excluded.market_code,
                    vol_regime         = excluded.vol_regime,
                    liq_regime         = excluded.liq_regime,
                    trend_regime       = excluded.trend_regime,
                    macro_event_window = excluded.macro_event_window,
                    time_bucket        = excluded.time_bucket,
                    source_version     = excluded.source_version,
                    ingested_at        = excluded.ingested_at""",
                rows[i:i + 5000],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    summary = {
        "total_fills": total,
        "skipped_no_market": skipped,
        "rows_upserted": len(rows),
        "time_bucket_tagged": tod_tagged,
        "time_bucket_parse_fail": tod_parse_fail,
    }
    logger.info(f"fill_regime_tagger: {summary}")
    return summary

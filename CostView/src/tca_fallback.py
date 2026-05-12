"""
TCA fallback computation — raw BDIB backfill for routes missing fill_bdib data.

Extracted from ``tca_query_service.py`` in Iteration 6.3 to reduce file size.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import sqlite3

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager

from .tca_utils import (
    derive_local_exchange_datetime as _derive_local_exchange_datetime,
    floor_time_to_10s as _floor_time_to_10s,
    side_sign as _side_sign,
    time_key as _time_key,
    to_optional_float as _to_optional_float,
)


def get_route_metric_fallbacks(
    mgr: ConnectionManager,
    route_rows: list[dict],
    tca_metrics: dict[tuple[str, str, str], dict],
) -> tuple[
    dict[tuple[str, str, str], dict[str, Optional[float]]],
    dict[tuple[str, str, str], list[dict]],
]:
    """Backfill missing route market metrics directly from raw_bdib.

    Used when fill_bdib was generated before local-time conversion was corrected.
    """
    fallback_candidates = []
    for route in route_rows:
        key = (route["order_id"], route["route_id"], route["order_as_of_date"])
        metrics = tca_metrics.get(key, {})
        if any(metrics.get(field) is None for field in ("cum_vwap", "cum_tracking_error", "cum_volume_pct")):
            fallback_candidates.append(route)

    if not fallback_candidates:
        return {}, {}

    metric_fallbacks: dict[tuple[str, str, str], dict[str, Optional[float]]] = {}
    series_fallbacks: dict[tuple[str, str, str], list[dict]] = {}

    proc_conn = mgr.get_connection("processed_fills", AccessTier.READ, row_factory=sqlite3.Row)
    raw_conn = mgr.get_connection("raw_bdib", AccessTier.READ, row_factory=sqlite3.Row)
    try:
        for route in fallback_candidates:
            key = (route["order_id"], route["route_id"], route["order_as_of_date"])
            fills = proc_conn.execute(
                f"""
                SELECT DateTimeOfFill, Exchange, FillPrice, FillShares
                FROM {Config.PROCESSED_FILLS_TABLE}
                WHERE OrderId = ? AND RouteId = ? AND order_as_of_date = ?
                ORDER BY DateTimeOfFill
                """,
                list(key),
            ).fetchall()
            computed = _compute_route_metrics_from_raw_bdib(raw_conn, route, fills)
            if computed is None:
                continue
            metric_fallbacks[key] = computed["metrics"]
            series_fallbacks[key] = computed["time_series"]
    finally:
        proc_conn.close()
        raw_conn.close()

    return metric_fallbacks, series_fallbacks


def _compute_route_metrics_from_raw_bdib(
    raw_conn: sqlite3.Connection,
    route: dict,
    fill_rows,
) -> Optional[dict[str, Any]]:
    """Compute cumulative fill metrics directly from raw_bdib bars.

    Used as a fallback when fill_bdib is missing data for specific metrics.
    """
    ticker = route.get("equ_ticker")
    trade_date = route.get("order_as_of_date")
    if not ticker or not trade_date or not fill_rows:
        return None

    fills_by_bucket: dict[str, dict[str, float]] = {}
    bucket_times: list[str] = []
    for fill in fill_rows:
        exchange = fill["Exchange"] if fill["Exchange"] else route.get("exchange")
        local_dt = _derive_local_exchange_datetime(fill["DateTimeOfFill"], exchange)
        if local_dt is None:
            continue
        bucket = _floor_time_to_10s(local_dt)
        fill_volume = _to_optional_float(fill["FillShares"])
        fill_price = _to_optional_float(fill["FillPrice"])
        if fill_volume is None or fill_price is None:
            continue
        bucket_times.append(bucket)
        bucket_row = fills_by_bucket.setdefault(bucket, {"fill_volume": 0.0, "fill_value": 0.0})
        bucket_row["fill_volume"] += fill_volume
        bucket_row["fill_value"] += fill_volume * fill_price

    if not bucket_times:
        return None

    start_bucket = min(bucket_times)
    end_bucket = max(bucket_times)
    bars = raw_conn.execute(
        f"""
        SELECT mkt_timestamp, close, volume, value
        FROM {Config.RAW_BDIB_TABLE}
        WHERE equ_ticker = ? AND order_as_of_date = ?
          AND substr(mkt_timestamp, -8) >= ?
          AND substr(mkt_timestamp, -8) <= ?
        ORDER BY substr(mkt_timestamp, -8)
        """,
        [ticker, trade_date, start_bucket, end_bucket],
    ).fetchall()
    if not bars:
        return None

    sign = _side_sign(route.get("side"))
    cum_fill_volume = 0.0
    cum_fill_value = 0.0
    cum_volume = 0.0
    cum_value = 0.0
    slippage_points: list[Optional[float]] = []
    points: list[dict[str, Any]] = []

    for bar in bars:
        ts = _time_key(bar["mkt_timestamp"])
        if ts is None:
            continue

        market_close = _to_optional_float(bar["close"])
        market_volume = _to_optional_float(bar["volume"]) or 0.0
        market_value = _to_optional_float(bar["value"])
        if market_value is None and market_close is not None and market_volume > 0:
            market_value = market_close * market_volume
        market_value = market_value or 0.0

        cum_volume += market_volume
        cum_value += market_value

        fill_bucket = fills_by_bucket.get(ts)
        fill_volume = None
        fill_px = None
        if fill_bucket is not None:
            fill_volume = fill_bucket["fill_volume"]
            fill_value = fill_bucket["fill_value"]
            cum_fill_volume += fill_volume
            cum_fill_value += fill_value
            fill_px = fill_value / fill_volume if fill_volume > 0 else None

        cum_vwap = (cum_value / cum_volume) if cum_volume > 0 else None
        cum_fill_vwap = (cum_fill_value / cum_fill_volume) if cum_fill_volume > 0 else None
        cum_volume_pct = (cum_fill_volume / cum_volume * 100.0) if cum_volume > 0 else None

        cum_slippage_bps = None
        if sign != 0 and cum_vwap not in (None, 0) and cum_fill_vwap is not None:
            cum_slippage_bps = sign * (cum_fill_vwap / cum_vwap - 1.0) * 10000.0
        slippage_points.append(cum_slippage_bps)
        points.append(
            {
                "ts": ts,
                "close": market_close,
                "fill_px": fill_px,
                "fill_volume": fill_volume,
                "volume": market_volume,
                "cum_volume_pct": cum_volume_pct,
                "cum_fill_vwap": cum_fill_vwap,
                "cum_vwap": cum_vwap,
                "cum_tracking_error": None,
            }
        )

    if not points:
        return None

    tracking_series = pd.Series(slippage_points, dtype=float).expanding().std()
    for idx, tracking_value in enumerate(tracking_series.tolist()):
        points[idx]["cum_tracking_error"] = None if pd.isna(tracking_value) else float(tracking_value)

    final_point = points[-1]
    return {
        "metrics": {
            "cum_fill_vwap": final_point.get("cum_fill_vwap"),
            "cum_vwap": final_point.get("cum_vwap"),
            "cum_tracking_error": final_point.get("cum_tracking_error"),
            "cum_volume_pct": final_point.get("cum_volume_pct"),
        },
        "time_series": points,
    }

"""
TCA utility functions — pure helpers extracted from ``tca_query_service.py``.

All functions are stateless (no class or database dependencies).
They are imported by ``tca_query_service.py`` and re-exported as static
methods on ``TcaQueryService`` for backward compatibility.

Extracted in Iteration 6.3 cleanup to reduce tca_query_service.py
from ~1,165 lines toward the ≤500-line target.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from DataPipeline.src.common.exchange_tz import convert_ny_to_local
from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from platform_data.contracts import (
    ScorecardCohortMetrics,
    ScorecardFilters,
    TcaFilters,
    TcaOrderSummary,
)


# ═══════════════════════════════════════════════════════════════════════════
# Date / time helpers
# ═══════════════════════════════════════════════════════════════════════════

def resolve_date_defaults(filters: TcaFilters) -> TcaFilters:
    """Apply sensible defaults when no date range is specified."""
    from datetime import date, timedelta

    if filters.start_date is None and filters.end_date is None and not filters.order_ids:
        # Default: last weekday
        ref = date.today()
        if ref.weekday() == 0:       # Monday → Friday
            ref = ref - timedelta(days=3)
        elif ref.weekday() == 6:     # Sunday → Friday
            ref = ref - timedelta(days=2)
        else:
            ref = ref - timedelta(days=1)
        filters.start_date = ref.strftime("%Y%m%d")
        filters.end_date = filters.start_date
    return filters


def filters_to_dict(filters: TcaFilters) -> dict:
    """Convert a TcaFilters instance to a plain dict."""
    return {
        "order_ids": filters.order_ids,
        "algo": filters.algo,
        "start_date": filters.start_date,
        "end_date": filters.end_date,
        "broker": filters.broker,
        "symbol": filters.symbol,
        "aggregation": filters.aggregation,
        "limit": filters.limit,
        "offset": filters.offset,
    }


def scorecard_filters_to_dict(filters: ScorecardFilters) -> dict:
    """Convert a ScorecardFilters instance to a plain dict."""
    return {
        "cohort": filters.cohort,
        "order_ids": filters.order_ids,
        "algo": filters.algo,
        "start_date": filters.start_date,
        "end_date": filters.end_date,
        "broker": filters.broker,
        "symbol": filters.symbol,
        "min_sample_size": filters.min_sample_size,
        "max_orders": filters.max_orders,
    }


def derive_local_exchange_datetime(
    datetime_value: Any, exchange_code: Any,
) -> Optional[datetime]:
    """Convert a UTC datetime to local exchange time."""
    if datetime_value is None or exchange_code is None:
        return None
    if pd.isna(datetime_value) or pd.isna(exchange_code):
        return None
    parsed = pd.to_datetime(datetime_value, errors="coerce")
    if pd.isna(parsed):
        return None
    local_dt = convert_ny_to_local(parsed.to_pydatetime(), str(exchange_code))
    if local_dt is None:
        return None
    return local_dt.replace(tzinfo=None)


def derive_local_exchange_time(
    datetime_value: Any, exchange_code: Any,
) -> Optional[str]:
    """Convert UTC datetime → local exchange time string."""
    local_dt = derive_local_exchange_datetime(datetime_value, exchange_code)
    if local_dt is None:
        return None
    return local_dt.strftime(Config.TIME_FORMAT)


def floor_time_to_10s(value: datetime) -> str:
    """Floor a datetime to the nearest 10-second bucket."""
    floored_seconds = (value.second // 10) * 10
    floored = value.replace(second=floored_seconds, microsecond=0)
    return floored.strftime(Config.TIME_FORMAT)


def time_key(value: Any) -> Optional[str]:
    """Extract HH:MM:SS from a datetime-like value."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if len(text) >= 8:
        return text[-8:]
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Numeric helpers
# ═══════════════════════════════════════════════════════════════════════════

def side_sign(side: Any) -> int:
    """Map side string → numeric sign: Buy=-1, Sell=+1."""
    if side is None or pd.isna(side):
        return 0
    side_upper = str(side).strip().upper()
    if side_upper in {"B", "BUY"}:
        return -1
    if side_upper in {"S", "SELL"}:
        return 1
    return 0


def to_optional_float(value: Any) -> Optional[float]:
    """Safely convert a value to float or None."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def mean_numeric(
    values: list[Optional[float]] | tuple[Optional[float], ...] | Any,
) -> Optional[float]:
    """Arithmetic mean ignoring None/NaN values."""
    cleaned: list[float] = []
    for value in values:
        if value is None or pd.isna(value):
            continue
        cleaned.append(float(value))
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


# ═══════════════════════════════════════════════════════════════════════════
# Statistical helpers
# ═══════════════════════════════════════════════════════════════════════════

def std(values: list[Optional[float]]) -> Optional[float]:
    """Sample standard deviation ignoring None/NaN."""
    cleaned = [float(v) for v in values if v is not None and not pd.isna(v)]
    if len(cleaned) < 2:
        return None
    mean = sum(cleaned) / len(cleaned)
    variance = sum((v - mean) ** 2 for v in cleaned) / (len(cleaned) - 1)
    return math.sqrt(variance)


def safe_percentile(values: list[float], pct: float) -> Optional[float]:
    """Compute a percentile, handling edge cases safely."""
    cleaned = sorted(float(v) for v in values if v is not None and not math.isnan(float(v)))
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    rank = (pct / 100.0) * (len(cleaned) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return cleaned[lower]
    weight = rank - lower
    return cleaned[lower] * (1 - weight) + cleaned[upper] * weight


# ═══════════════════════════════════════════════════════════════════════════
# Cohort bucketing helpers
# ═══════════════════════════════════════════════════════════════════════════

def bucket_time_of_day(start_time: Optional[str]) -> tuple[str, str]:
    """Classify order start time into Open/Mid/Close buckets."""
    if not start_time:
        return ("unknown", "Unknown")
    try:
        hh = int(str(start_time)[:2])
        mm = int(str(start_time)[3:5])
    except (TypeError, ValueError):
        return ("unknown", "Unknown")
    minutes = hh * 60 + mm
    if minutes < 10 * 60 + 30:
        return ("open", "Open (first hour)")
    if minutes >= 14 * 60 + 30:
        return ("close", "Close (last 90 min)")
    return ("mid", "Mid-day")


# ═══════════════════════════════════════════════════════════════════════════
# Scorecard cohort aggregation
# ═══════════════════════════════════════════════════════════════════════════

def cohort_key_and_label(
    order: TcaOrderSummary,
    cohort: str,
) -> tuple[str, str]:
    """Compute (machine_key, human_label) for the cohort of this order."""
    broker = None
    if order.routes:
        broker = next((r.broker for r in order.routes if r.broker), None)
    broker_label = broker or "Unknown"
    algo_label = order.algo or "Unknown"

    if cohort == "broker":
        return (broker_label, broker_label)
    if cohort == "strategy":
        return (algo_label, algo_label)
    if cohort == "broker_strategy":
        return (f"{broker_label}|{algo_label}", f"{broker_label} | {algo_label}")
    if cohort == "asset_class":
        return asset_class_from_ticker(order.equ_ticker)
    if cohort == "time_of_day":
        return bucket_time_of_day(order.start_time)
    if cohort == "liquidity_adv20":
        return bucket_liquidity(order.volume_pct_adv20)
    if cohort == "volatility":
        return bucket_volatility(order.daily_volatility)
    return ("unknown", "Unknown")


def aggregate_cohorts(
    orders: list[TcaOrderSummary],
    cohort: str,
    min_sample_size: int,
) -> list[ScorecardCohortMetrics]:
    """Group completed orders into cohorts and compute aggregate metrics."""
    buckets: dict[tuple[str, str], list[TcaOrderSummary]] = defaultdict(list)
    for order in orders:
        if order.tracking_error_bps is None and order.exec_price is None:
            continue
        key_label = cohort_key_and_label(order, cohort)
        buckets[key_label].append(order)

    results: list[ScorecardCohortMetrics] = []
    for (key, label), group in buckets.items():
        sample = len(group)
        abs_tracking = [
            abs(o.tracking_error_bps) for o in group if o.tracking_error_bps is not None
        ]
        avg_tracking = mean_numeric(abs_tracking)
        median_tracking = safe_percentile(abs_tracking, 50)
        p95_tracking = safe_percentile(abs_tracking, 95)
        stddev_tracking = std(abs_tracking)

        avg_fill = mean_numeric([o.fill_pct for o in group if o.fill_pct is not None])
        avg_vol_interval = mean_numeric(
            [o.volume_pct_interval for o in group if o.volume_pct_interval is not None]
        )
        avg_vol_adv20 = mean_numeric(
            [o.volume_pct_adv20 for o in group if o.volume_pct_adv20 is not None]
        )
        avg_daily_vol = mean_numeric(
            [o.daily_volatility for o in group if o.daily_volatility is not None]
        )
        avg_intraday_vol = mean_numeric(
            [o.intraday_volatility for o in group if o.intraday_volatility is not None]
        )
        avg_price_move = mean_numeric(
            [abs(o.price_movement_pct) for o in group if o.price_movement_pct is not None]
        )
        dq_ratio = (
            sum(1 for o in group if o.data_quality_warning) / sample if sample else 0.0
        )
        sample_warn = sample < min_sample_size

        flags: list[str] = []
        if sample_warn:
            flags.append("sample_size")
        if avg_tracking is not None and avg_tracking >= 25:
            flags.append("high_tracking_error")
        elif avg_tracking is not None and avg_tracking >= 10:
            flags.append("elevated_tracking_error")
        if p95_tracking is not None and p95_tracking >= 50:
            flags.append("tail_tracking_error")
        if avg_fill is not None and avg_fill < 80:
            flags.append("low_fill_rate")
        if avg_vol_adv20 is not None and avg_vol_adv20 >= 10:
            flags.append("high_participation")
        if dq_ratio >= 0.25:
            flags.append("data_quality")

        results.append(
            ScorecardCohortMetrics(
                cohort_key=key,
                cohort_label=label,
                sample_size=sample,
                order_count=sample,
                avg_tracking_error_bps=avg_tracking,
                median_tracking_error_bps=median_tracking,
                p95_tracking_error_bps=p95_tracking,
                stddev_tracking_error_bps=stddev_tracking,
                avg_fill_pct=avg_fill,
                avg_volume_pct_interval=avg_vol_interval,
                avg_volume_pct_adv20=avg_vol_adv20,
                avg_daily_volatility=avg_daily_vol,
                avg_intraday_volatility=avg_intraday_vol,
                avg_price_movement_pct=avg_price_move,
                data_quality_ratio=round(dq_ratio, 4),
                sample_size_warning=sample_warn,
                anomaly_flags=flags,
            )
        )

    def _sort_key(row: ScorecardCohortMetrics) -> tuple:
        tracking = row.avg_tracking_error_bps if row.avg_tracking_error_bps is not None else -1.0
        return (row.sample_size_warning, -tracking, -row.sample_size, row.cohort_label)

    results.sort(key=_sort_key)
    return results


def bucket_liquidity(volume_pct_adv20: Optional[float]) -> tuple[str, str]:
    """Bucket participation vs. 20-day ADV."""
    if volume_pct_adv20 is None:
        return ("unknown", "Unknown")
    if volume_pct_adv20 < 1.0:
        return ("low", "Low (<1% ADV20)")
    if volume_pct_adv20 < 5.0:
        return ("mid", "Mid (1%-5% ADV20)")
    return ("high", "High (>=5% ADV20)")


def bucket_volatility(daily_volatility: Optional[float]) -> tuple[str, str]:
    """Bucket daily volatility in percent space."""
    if daily_volatility is None:
        return ("unknown", "Unknown")
    if daily_volatility < 1.5:
        return ("calm", "Calm (<1.5%)")
    if daily_volatility < 3.5:
        return ("typical", "Typical (1.5%-3.5%)")
    return ("stressed", "Stressed (>=3.5%)")


def asset_class_from_ticker(equ_ticker: Optional[str]) -> tuple[str, str]:
    """Derive a coarse asset class label from the Bloomberg ticker suffix."""
    if not equ_ticker:
        return ("unknown", "Unknown")
    token = str(equ_ticker).strip().rsplit(" ", 1)[-1].upper()
    mapping = {
        "EQUITY": ("equity", "Equity"),
        "CURNCY": ("fx", "FX"),
        "INDEX": ("index", "Index"),
        "COMDTY": ("commodity", "Commodity"),
        "CORP": ("fixed_income", "Fixed Income"),
        "GOVT": ("fixed_income", "Fixed Income"),
    }
    return mapping.get(token, ("other", token.title() or "Other"))

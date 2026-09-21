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
from datetime import date
from typing import TYPE_CHECKING, Any, Mapping, Optional

import pandas as pd

from platform_data.contracts import (
    ScorecardCohortMetrics,
    ScorecardFilters,
    TcaFilters,
    TcaRouteSummary,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查，避免 monitoring 包级循环 import
    from .monitoring.env_context import RouteEnvContext


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


def business_days_lag(latest_date: str, today: date) -> int:
    """计算最新数据日与 today 之间的滞后交易日数（周一至周五计为交易日）。

    与数据管道新鲜度 SLA（Config.FRESHNESS_*_BUSINESS_DAYS）同一计量口径：
    以"交易日"为单位，规避周末/长周末误判。latest_date 为 YYYYMMDD；
    解析失败返回一个必然触发 fail 级别的大值（保守处理，不静默放行）。
    latest_date 晚于 today（理论上不应发生）按 0 处理。
    """
    from datetime import datetime, timedelta

    try:
        latest = datetime.strptime(latest_date, "%Y%m%d").date()
    except (TypeError, ValueError):
        return 9999
    if latest >= today:
        return 0
    lag = 0
    cursor = latest + timedelta(days=1)
    while cursor <= today:
        if cursor.weekday() < 5:  # 0-4 = Mon-Fri
            lag += 1
        cursor += timedelta(days=1)
    return lag


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


# ═══════════════════════════════════════════════════════════════════════════
# Numeric helpers
# ═══════════════════════════════════════════════════════════════════════════

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

def _env_cohort_key(
    route: TcaRouteSummary,
    cohort: str,
    env: Optional["RouteEnvContext"],
) -> Optional[tuple[str, str]]:
    """三个环境 cohort 的分桶（返回 None 表示该 cohort 不是环境维度）。

    真实字段优先；该维度不可得时回退既有代理口径 —— 保留代理的理由是「静默丢样本比
    降级更有害」，但降级必须可见（可得率经 ``env_context.env_coverage`` 随 payload 披露）。
    """
    if cohort == "time_of_day":
        # 真实 start_time（路由内最早成交时刻；已在 env_context 归一化为 HH:MM:SS）
        return bucket_time_of_day(env.start_time if env else None)
    if cohort == "liquidity_adv20":
        if env is not None and env.adv20_ratio is not None:
            # 真实口径：订单规模 ÷ 20 日均量（bucket 需要百分比空间）
            return bucket_liquidity(env.adv20_ratio * 100)
        # L3 降级：par_rate（区间参与率）作代理（0-1 小数 → 百分比）
        return bucket_liquidity(route.par_rate * 100 if route.par_rate is not None else None)
    if cohort == "volatility":
        if env is not None and env.daily_volatility is not None:
            # 真实口径：bdib_daily_summary.daily_volatility（百分比空间）
            return bucket_volatility(env.daily_volatility)
        # L3 降级：|pnl_vwap|（成本）作波动率代理 —— 循环论证，仅作兜底
        return bucket_volatility(abs(route.pnl_vwap) if route.pnl_vwap is not None else None)
    return None


def cohort_key_and_label(
    route: TcaRouteSummary,
    cohort: str,
    env: Optional["RouteEnvContext"] = None,
) -> tuple[str, str]:
    """计算 (machine_key, human_label) for the cohort of this route。

    ``env`` 为 026 阶段二引入的**可选**执行环境上下文（``monitoring.env_context``）：
    给出时三个环境 cohort 使用真实字段；字段缺失或 ``env=None`` 时自动回退代理口径
    —— 参数默认值天然构成降级路径（plan §4.2 DP-2-4），无需额外开关。非环境 cohort 忽略它。
    """
    broker = route.Broker or "Unknown"
    algo = route.algo or "Unknown"
    equ_ticker = route.equ_ticker

    if cohort == "broker":
        return (broker, broker)
    if cohort == "strategy":
        return (algo, algo)
    if cohort == "broker_strategy":
        return (f"{broker}|{algo}", f"{broker} | {algo}")
    if cohort == "asset_class":
        return asset_class_from_ticker(equ_ticker)

    env_key = _env_cohort_key(route, cohort, env)
    if env_key is not None:
        return env_key
    return ("unknown", "Unknown")


def aggregate_cohorts(
    routes: list[TcaRouteSummary],
    cohort: str,
    min_sample_size: int,
    env_by_route: Optional[Mapping[tuple[str, str, str], "RouteEnvContext"]] = None,
) -> list[ScorecardCohortMetrics]:
    """Group routes into cohorts and compute aggregate metrics.

    ``env_by_route`` 为可选的「路由键 → 执行环境上下文」映射（026 阶段二）：给出时
    环境 cohort 使用真实字段，未覆盖的路由自动回退代理口径。路由键与
    ``env_context.env_route_key`` 同源（局部 import，规避 monitoring 包级循环）。
    """
    from .monitoring.env_context import env_route_key

    buckets: dict[tuple[str, str], list[TcaRouteSummary]] = defaultdict(list)
    for route in routes:
        if route.pnl_vwap is None and route.par_rate is None:
            continue
        env = None
        if env_by_route:
            env = env_by_route.get(
                env_route_key(route.OrderId, route.RouteId, route.order_as_of_date)
            )
        key_label = cohort_key_and_label(route, cohort, env)
        buckets[key_label].append(route)

    results: list[ScorecardCohortMetrics] = []
    for (key, label), group in buckets.items():
        sample = len(group)
        abs_pnl = [
            abs(r.pnl_vwap) for r in group if r.pnl_vwap is not None
        ]
        avg_pnl = mean_numeric(abs_pnl)
        median_pnl = safe_percentile(abs_pnl, 50)
        p95_pnl = safe_percentile(abs_pnl, 95)
        stddev_pnl = std(abs_pnl)

        avg_fill = mean_numeric([r.fill for r in group if r.fill is not None])
        avg_par_rate = mean_numeric(
            [r.par_rate for r in group if r.par_rate is not None]
        )
        avg_par_rate_continuous = mean_numeric(
            [r.par_rate_continuous for r in group if r.par_rate_continuous is not None]
        )
        avg_rpm = mean_numeric(
            [r.RPM for r in group if r.RPM is not None]
        )
        avg_pnl_continuous = mean_numeric(
            [abs(r.pnl_vwap_continuous) for r in group if r.pnl_vwap_continuous is not None]
        )
        # P3-3：dq_ratio 接线为真实代理——cohort 内 BDIB 依赖指标（pnl_vwap）
        # 缺失路由的占比（pnl_vwap/par_rate 双缺失的路由已在入桶前剔除，
        # 故该占比反映的是"有数据但 BDIB 依赖指标计算缺失"的数据质量缺口，
        # 与 metric_coverage 的 bdib_cutoff 原因分类口径一致）。
        bdib_gap_count = sum(1 for r in group if r.pnl_vwap is None)
        dq_ratio = bdib_gap_count / sample if sample else 0.0
        sample_warn = sample < min_sample_size

        flags: list[str] = []
        if sample_warn:
            flags.append("sample_size")
        if avg_pnl is not None and avg_pnl >= 25:
            flags.append("high_tracking_error")
        elif avg_pnl is not None and avg_pnl >= 10:
            flags.append("elevated_tracking_error")
        if p95_pnl is not None and p95_pnl >= 50:
            flags.append("tail_tracking_error")
        if avg_fill is not None and avg_fill < 80:
            flags.append("low_fill_rate")
        if avg_par_rate is not None and avg_par_rate >= 0.10:
            flags.append("high_participation")
        if dq_ratio >= 0.25:
            flags.append("data_quality")

        results.append(
            ScorecardCohortMetrics(
                cohort_key=key,
                cohort_label=label,
                sample_size=sample,
                order_count=sample,
                avg_tracking_error_bps=avg_pnl,
                median_tracking_error_bps=median_pnl,
                p95_tracking_error_bps=p95_pnl,
                stddev_tracking_error_bps=stddev_pnl,
                avg_fill_pct=avg_fill,
                avg_volume_pct_interval=avg_par_rate_continuous * 100 if avg_par_rate_continuous is not None else None,
                avg_volume_pct_adv20=avg_par_rate * 100 if avg_par_rate is not None else None,
                avg_daily_volatility=avg_rpm * 100 if avg_rpm is not None else None,
                avg_intraday_volatility=avg_pnl_continuous,
                avg_price_movement_pct=None,
                data_quality_ratio=round(dq_ratio, 4),
                sample_size_warning=sample_warn,
                anomaly_flags=flags,
            )
        )

    def _sort_key(row: ScorecardCohortMetrics) -> tuple:
        pnl = row.avg_tracking_error_bps if row.avg_tracking_error_bps is not None else -1.0
        return (row.sample_size_warning, -pnl, -row.sample_size, row.cohort_label)

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

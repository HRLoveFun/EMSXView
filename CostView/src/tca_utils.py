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
from datetime import date, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Mapping, Optional

import pandas as pd

from platform_data.adapters.session import ExchangeSessionAdapter
from platform_data.contracts import (
    ScorecardCohortMetrics,
    ScorecardFilters,
    TcaFilters,
    TcaRouteSummary,
    classify_algo,
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

#: 会话注册表查询单例（DL-03；无状态，可跨模块共享）
_SESSION_ADAPTER = ExchangeSessionAdapter()

#: 管道 S9 五桶 + JP 午休的中文报告标签
_TIME_BUCKET_LABELS: dict[str, str] = {
    "open_30m": "Open (first 30 min)",
    "morning": "Morning",
    "midday": "Mid-day",
    "afternoon": "Afternoon",
    "close_30m": "Close (last 30 min)",
    "lunch_break": "Lunch break",
}


def _hhmm_to_minutes(value: Optional[str]) -> Optional[int]:
    """``HH:MM`` → 当日分钟数；不可解析返回 None。"""
    if not value:
        return None
    try:
        hh, mm = str(value).strip().split(":")[:2]
        return int(hh) * 60 + int(mm)
    except (TypeError, ValueError):
        return None


def _parse_local_time(value: Any) -> Optional[datetime]:
    """``HH:MM:SS`` / ``YYYYMMDD HH:MM:SS`` → naive datetime（仅时分秒有意义）。"""
    if not value:
        return None
    return _parse_local_time_text(str(value).strip())


@lru_cache(maxsize=4096)
def _parse_local_time_text(text: str) -> Optional[datetime]:
    """``_parse_local_time`` 的纯字符串实现（lru_cache 需可哈希入参）。

    评估报告会按「维度 × 路由」反复取时段桶，同一 start_time 会被解析数万次；
    缓存后 strptime 只跑一次（实测逐维评估的 2.5s 解析开销降为毫秒级）。
    """
    if len(text) > 8:
        text = text[-8:]
    try:
        return datetime.strptime(text, "%H:%M:%S")
    except ValueError:
        return None


def time_bucket_detail(
    route: Any,
    env: Optional["RouteEnvContext"],
) -> tuple[str, str, str]:
    """决策时点 ``route_as_of_time`` → (key, label, source)。

    211（DL-19）：时段不再取首笔成交时刻，也**不再**用固定挂钟 10:30/14:30。
    - 优先 DL-03 会话相对桶（与管道 S9 同口径：open_30m/morning/midday/
      afternoon/close_30m，JP 含 lunch_break）；
    - 非 S9 市场用 ``session_relative_minutes`` + 会话跨度派生 open/mid/close；
    - 市场未知或时刻不可解析 → ``unknown``。
    """
    exchange = str(getattr(route, "Exchange", None) or "").strip().upper()
    start_time = getattr(env, "start_time", None) if env else None
    return _time_bucket_detail_cached(
        exchange, str(start_time) if start_time else None,
    )


@lru_cache(maxsize=16384)
def _time_bucket_detail_cached(
    exchange: str,
    start_time: Optional[str],
) -> tuple[str, str, str]:
    """``time_bucket_detail`` 的可缓存内核（入参均为可哈希的纯值）。"""
    dt = _parse_local_time(start_time)
    if dt is None or not exchange:
        return ("unknown", "Unknown", "unknown")

    bucket = _SESSION_ADAPTER.time_bucket_for(exchange, dt)
    if bucket is not None:
        return (bucket, _TIME_BUCKET_LABELS.get(bucket, bucket), "s9")

    session = _SESSION_ADAPTER.get_session(exchange)
    relative = _SESSION_ADAPTER.session_relative_minutes(exchange, dt)
    if session is None or relative is None:
        return ("unknown", "Unknown", "unknown")
    open_min = _hhmm_to_minutes(session.market_open)
    close_min = _hhmm_to_minutes(session.market_close)
    if open_min is None or close_min is None:
        return ("unknown", "Unknown", "unknown")
    span = close_min - open_min
    if span <= 0 or relative < 0 or relative >= span:
        return ("unknown", "Unknown", "unknown")
    third = span / 3.0
    if relative < third:
        return ("open", "Open (first third)", "session-relative")
    if relative < 2 * third:
        return ("mid", "Mid-day", "session-relative")
    return ("close", "Close (last third)", "session-relative")


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
        # 211：决策时点 route_as_of_time + DL-03 会话相对分桶（不再用首笔成交时刻）
        return time_bucket_detail(route, env)[:2]
    if cohort == "liquidity_adv20":
        if env is not None and env.adv20_ratio is not None:
            # 决策时点口径：RouteShares ÷ 20 日均量（bucket 需要百分比空间）
            return bucket_liquidity(env.adv20_ratio * 100)
        # 211：删除 par_rate（成交/ADV，后验）兜底 —— 缺失即 unknown
        return ("unknown", "Unknown")
    if cohort == "volatility":
        if env is not None and env.daily_volatility is not None:
            # 真实口径：bdib_daily_summary.daily_volatility（百分比空间）
            return bucket_volatility(env.daily_volatility)
        # 211：删除 |pnl_vwap|（被解释变量）兜底 —— 缺失即 unknown
        return ("unknown", "Unknown")
    return None


def intent_family_key(route: Any) -> tuple[str, str, str, str]:
    """意图 × 算法族分组键（212）。

    - 意图**可选**：路由自带 ``intent`` 时使用（大写）；缺失记 ``UNKNOWN``，
      **不按算法族反推**（用户裁定：意图只是订单到达时的指令，不要求关联到路由）。
    - 算法族取 DL-04 ``classify_algo``；MIX 的两段因族不同自然拆开。
    - 返回 ``(key, label, intent_source, algo_family)``。
    """
    family = classify_algo(
        str(getattr(route, "Broker", None) or ""),
        getattr(route, "algo", None),
    )
    intent = str(getattr(route, "intent", None) or "UNKNOWN").strip().upper() or "UNKNOWN"
    source = str(getattr(route, "intent_source", None) or "unknown")
    key = f"{intent}|{family}"
    label = family.upper() if intent == "UNKNOWN" else f"{intent} | {family.upper()}"
    return (key, label, source, family)


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
    if cohort == "intent_family":
        key, label, _, _ = intent_family_key(route)
        return (key, label)

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
        # 211（DL-19）：不再按 pnl_vwap/par_rate 是否可算做样本过滤（后验选择偏差）；
        # 无基准的路由仍入层，指标按 None 跳过，样本量如实计数。
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
        # P3-3 / 211：cohort 内 BDIB 依赖指标（pnl_vwap）缺失路由的占比。
        # 211 起不再按 pnl_vwap/par_rate 预过滤，故该占比如实反映数据质量缺口，
        # 与 metric_coverage 的 bdib_cutoff 原因分类口径一致。
        bdib_gap_count = sum(1 for r in group if r.pnl_vwap is None)
        dq_ratio = bdib_gap_count / sample if sample else 0.0
        sample_warn = sample < min_sample_size

        # 212（DL-19）：intent_family cohort 的附加披露；组内来源不一致记 mixed
        intent_source = ""
        algo_family = ""
        if cohort == "intent_family":
            _, _, intent_source, algo_family = intent_family_key(group[0])
            if len({intent_family_key(r)[2] for r in group}) > 1:
                intent_source = "mixed"

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
                intent_source=intent_source,
                algo_family=algo_family,
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


def bucket_volatility(annual_volatility: Optional[float]) -> tuple[str, str]:
    """Bucket **annualised** volatility (percent space) —— 028 口径修正。

    026 起本函数接收 `bdib_daily_summary.daily_volatility` 的**原值**，但阈值仍沿用
    日波动率空间（1.5% / 3.5%），而该列实为**年化百分比**（实测中位 26.075，
    见 `docs/archive/2026-09-21/028-volatility-scale-fix/research.md`）—— 二者相差 ≈ √252 ≈ 16 倍，
    实测导致 82.9% 样本落 `stressed`、`typical` 仅 0.61%，该维度**失去区分度**。

    028 起阈值对齐到年化空间，并与 `platform_data/adapters/market.py:50-51`
    解读同一列的既有口径（25 / 40）保持一致。

    入参须为**年化百分比**（小数写法由 `env_context.normalize_volatility_to_percent`
    在数据入口统一，不在本函数兜底 —— 分桶保持纯函数、单一职责）。
    """
    if annual_volatility is None:
        return ("unknown", "Unknown")
    if annual_volatility < 25.0:
        return ("calm", "Calm (<25% ann.)")
    if annual_volatility < 40.0:
        return ("typical", "Typical (25%-40% ann.)")
    return ("stressed", "Stressed (>=40% ann.)")


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

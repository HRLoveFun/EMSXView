"""数据盘点与样本结构统计 —— 057 DL-05（只读 CLI 支撑模块）。

盘点四项（tasks.md DL-05）：
1. D1 配对候选占比：同一 OrderId 同日 ≥2 券商且路由下达时差 ≤5min 的订单占比
   （按市场 × 算法族拆分）；
2. 单元样本量与 MDE：(Exchange × algo 细分族 × 参与率档) 的样本量与可检测
   最小 Δ（正态近似闭式，复用 evaluation/power.py 口径）；
3. BDIB 覆盖：当日订单簿证券 vs raw_bdib 当日有 bar 的证券；
4. PM 意图覆盖率：由 DL-01 盘前单端点承载（MarketView 域），本模块不重复。

数据源：processed_fills（fill 级，route_as_of_time/Broker/algo 所在地）、
tca_route_summary（路由级汇总）、raw_bdib（bar 覆盖）。全部只读。
"""

from __future__ import annotations

import logging
from typing import Optional

from data_access.config import Config
from platform_data.contracts import SESSION_REGISTRY

logger = logging.getLogger(__name__)

# D1 配对判定口径（tasks.md DL-05）
PAIR_MIN_BROKERS = 2
PAIR_MAX_SPREAD_MINUTES = 5.0

# MDE 默认参数（与 evaluation/power.py DEFAULT_ALPHA/POWER 一致；σ=1 标准化单位）
MDE_ALPHA = 0.05
MDE_POWER = 0.8

# 参与率档（par_rate 为路由级区间参与率，tca_route_summary 可得；ADV 规模档
# 留待 DL-10 基线就绪后升级——bdib_daily_summary 跨库 join 不在本模块范围）
PAR_RATE_BUCKETS: tuple[tuple[float | None, str], ...] = (
    (0.05, "<5%"),
    (0.15, "5-15%"),
    (0.30, "15-30%"),
    (None, ">=30%"),
)


def minutes_of_day(value: str | None) -> Optional[int]:
    """'HH:MM:SS' 或 '...THH:MM:SS' → 当日分钟数；不可解析为 None。"""
    if not value:
        return None
    text = str(value).strip()
    if len(text) >= 8 and text[-8:-6].isdigit() and text[-8:-5].count(":") == 1:
        hours = int(text[-8:-6])
        minutes = int(text[-5:-3])
        return hours * 60 + minutes
    return None


def judge_pair_candidate(broker_count: int, spread_minutes: float) -> bool:
    """D1 配对候选判定：≥2 券商且组内下达时差 ≤5min。"""
    return broker_count >= PAIR_MIN_BROKERS and spread_minutes <= PAIR_MAX_SPREAD_MINUTES


def par_rate_bucket(par_rate: float | None) -> str:
    """参与率分桶（不可得归 'unknown'）。"""
    if par_rate is None:
        return "unknown"
    for upper, label in PAR_RATE_BUCKETS:
        if upper is None or par_rate < upper:
            return label
    return PAR_RATE_BUCKETS[-1][1]


def coverage_pct(covered: int, total: int) -> float:
    """覆盖率百分比（total=0 → 0.0，不除零）。"""
    return round(covered / total * 100, 4) if total else 0.0


def mde_for_sample(n_per_group: int, alpha: float = MDE_ALPHA, power: float = MDE_POWER) -> Optional[float]:
    """给定每组样本量，反解可检测的最小 Δ（σ=1 标准化 z 单位）。

    n_per_group = 2(z_{1-α/2}+z_{1-β})²/Δ² ⇒ Δ = sqrt(2(zα+zβ)²/n)。
    """
    if n_per_group <= 0:
        return None
    from scipy import stats as _stats

    z_alpha = float(_stats.norm.ppf(1 - alpha / 2))
    z_beta = float(_stats.norm.ppf(power))
    import math

    return round(math.sqrt(2 * (z_alpha + z_beta) ** 2 / n_per_group), 4)


# ── 取数（只读） ───────────────────────────────────────────────────────────────

_ROUTE_MINUTES_EXPR = (
    "CAST(substr(route_as_of_time, -8, 2) AS INTEGER) * 60 "
    "+ CAST(substr(route_as_of_time, -5, 2) AS INTEGER)"
)


def load_pair_aggregates(mgr, since_date: str) -> list[tuple]:
    """D1 配对聚合：按 (OrderId, 日期, Exchange, algo) 输出组内券商数与下达时差。

    返回 [(OrderId, order_as_of_date, Exchange, algo, broker_count, spread_min)]。
    内层 DISTINCT 先把 fill 级去重为路由级。
    """
    conn = mgr.get_connection("processed_fills")
    try:
        rows = conn.execute(
            f"SELECT OrderId, order_as_of_date, Exchange, algo, "
            f"COUNT(DISTINCT Broker) AS broker_count, "
            f"MAX(t_min) - MIN(t_min) AS spread_min "
            f"FROM (SELECT DISTINCT OrderId, RouteId, order_as_of_date, Exchange, algo, Broker, "
            f"{_ROUTE_MINUTES_EXPR} AS t_min "
            f"FROM {Config.PROCESSED_FILLS_TABLE} WHERE order_as_of_date >= ?) "
            f"GROUP BY OrderId, order_as_of_date, Exchange, algo",
            [since_date],
        ).fetchall()
        return [
            (str(r[0]), str(r[1]), str(r[2] or ""), str(r[3] or ""), int(r[4]), int(r[5] or 0))
            for r in rows
        ]
    finally:
        conn.close()


def load_unit_counts(mgr, since_date: str) -> list[tuple]:
    """单元样本量：按 (Exchange, algo 细分族, 参与率档) 计数路由。

    返回 [(Exchange, family, bucket, n)]；algo 细分族由 DL-04 契约分类。
    """
    from platform_data.contracts import classify_algo

    conn = mgr.get_connection("fill_bdib")
    try:
        rows = conn.execute(
            f"SELECT Exchange, Broker, StrategyType, algo, par_rate, COUNT(*) "
            f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE} WHERE order_as_of_date >= ? "
            f"GROUP BY Exchange, Broker, StrategyType, algo, par_rate",
            [since_date],
        ).fetchall()
    finally:
        conn.close()

    counts: dict[tuple[str, str, str], int] = {}
    for exchange, broker, strategy, algo, par_rate, n in rows:
        family = classify_algo(str(broker or ""), strategy)
        key = (str(exchange or ""), family, par_rate_bucket(par_rate))
        counts[key] = counts.get(key, 0) + int(n)
    return [(k[0], k[1], k[2], v) for k, v in sorted(counts.items())]


def load_ticker_sets(mgr, trade_date: str) -> tuple[set[str], set[str]]:
    """当日订单簿证券（processed_fills）与有 bar 的证券（raw_bdib）集合。"""
    order_book: set[str] = set()
    conn = mgr.get_connection("processed_fills")
    try:
        rows = conn.execute(
            f"SELECT DISTINCT equ_ticker FROM {Config.PROCESSED_FILLS_TABLE} WHERE order_as_of_date = ?",
            [trade_date],
        ).fetchall()
        order_book = {str(r[0]) for r in rows if r[0]}
    finally:
        conn.close()

    with_bars: set[str] = set()
    conn = mgr.get_connection("raw_bdib")
    try:
        rows = conn.execute(
            f"SELECT DISTINCT equ_ticker FROM {Config.RAW_BDIB_TABLE} WHERE order_as_of_date = ?",
            [trade_date],
        ).fetchall()
        with_bars = {str(r[0]) for r in rows if r[0]}
    finally:
        conn.close()
    return order_book, with_bars


def latest_trade_date(mgr) -> str | None:
    """processed_fills 最近交易日（BDIB 覆盖检查的默认目标日）。"""
    conn = mgr.get_connection("processed_fills")
    try:
        row = conn.execute(
            f"SELECT MAX(order_as_of_date) FROM {Config.PROCESSED_FILLS_TABLE}"
        ).fetchone()
        return str(row[0]) if row and row[0] else None
    finally:
        conn.close()


def _split_by_whitelist(tickers: list[str]) -> tuple[list[str], list[str]]:
    """按 equ_ticker 后缀交易所码拆分白名单内外（白名单 = DL-03 注册表键）。"""
    inside: list[str] = []
    outside: list[str] = []
    for ticker in tickers:
        parts = ticker.split()
        exchange = parts[-2].upper() if len(parts) >= 2 else ""
        (inside if exchange in SESSION_REGISTRY else outside).append(ticker)
    return inside, outside


def build_inventory(mgr, since_date: str, trade_date: str | None = None) -> dict:
    """汇总盘点四项 → dict（CLI/报告直接序列化）。

    trade_date 缺省时取数据集中最近交易日（避免用 since_date 当日——通常无数据）。
    """
    if not trade_date:
        trade_date = latest_trade_date(mgr) or since_date
    # ① D1 配对候选
    aggregates = load_pair_aggregates(mgr, since_date)
    candidates = [a for a in aggregates if judge_pair_candidate(a[4], a[5])]
    by_market_family: dict[tuple[str, str], dict[str, int]] = {}
    for order_id, _date, exchange, algo, broker_count, spread in aggregates:
        key = (exchange or "unknown", algo or "unknown")
        slot = by_market_family.setdefault(key, {"groups": 0, "candidates": 0})
        slot["groups"] += 1
        if judge_pair_candidate(broker_count, spread):
            slot["candidates"] += 1
    pair_section = {
        "groups_total": len(aggregates),
        "groups_candidate": len(candidates),
        "group_pct": coverage_pct(len(candidates), len(aggregates)),
        "by_market_family": [
            {"exchange": k[0], "algo": k[1], **v, "pct": coverage_pct(v["candidates"], v["groups"])}
            for k, v in sorted(by_market_family.items())
        ],
    }

    # ② 单元样本量与 MDE
    units = load_unit_counts(mgr, since_date)
    unit_rows = [
        {
            "exchange": exchange,
            "family": family,
            "par_bucket": bucket,
            "n": n,
            "mde": mde_for_sample(n),
        }
        for exchange, family, bucket, n in units
    ]
    unit_rows.sort(key=lambda r: (r["exchange"], r["family"], r["par_bucket"]))

    # ③ BDIB 覆盖（缺失按白名单内外拆分：白名单外市场不拉 BDIB 是预期行为，
    # 2026-07-16 已移出 8 个市场；白名单内缺失才是真数据缺口）
    order_book, with_bars = load_ticker_sets(mgr, trade_date)
    missing = sorted(order_book - with_bars)
    missing_in, missing_out = _split_by_whitelist(missing)
    bdib_section = {
        "trade_date": trade_date,
        "order_book": len(order_book),
        "with_bars": len(order_book & with_bars),
        "coverage_pct": coverage_pct(len(order_book & with_bars), len(order_book)),
        "missing_count": len(missing),
        "missing_in_whitelist": len(missing_in),
        "missing_outside_whitelist": len(missing_out),
        "missing_in_sample": missing_in[:20],
        "missing_outside_sample": missing_out[:10],
    }

    return {
        "since_date": since_date,
        "pair_candidates": pair_section,
        "units": unit_rows,
        "bdib_coverage": bdib_section,
    }

"""盘中市场状态服务（057 DL-15；C 层实时特征，特性开关默认关闭）。

从订阅缓存构建 `MarketStateSnapshot`：价差 bps、相对日度基线的差值与服务端
版本化阈值告警；v2 追加实时涨跌幅（优先 CHG_PCT_1D，缺失时用最新价 ÷ 前收 回落）。
缓存经 `BloombergEMSXService` 门面暴露（`intraday_quotes` / `price_changes`），
MarketView 前端只读快照、不直连 Bloomberg。
预期量曲线（DL-09）、到达价 σ 位移（DL-12）、参与率本期不可得，契约预留 `None`。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from platform_data.contracts import (
    MarketBaseline,
    MarketStateFlag,
    MarketStateSnapshot,
    MarketStateThresholds,
    MarketStateTickerState,
)

logger = logging.getLogger(__name__)

#: 服务端统一阈值（版本化；变更即升版并记审计）
THRESHOLDS = MarketStateThresholds()

#: MonitorBoard 服务端默认阈值（057 DL-15：替代前端 localStorage 全局常数）
MONITOR_THRESHOLDS_VERSION = "monitor-thresholds-v1"
MONITOR_THRESHOLDS_DEFAULTS: dict = {
    "dollarValueLow": 10_000,
    "dollarValueHigh": 49_000_000,
    "pctChangeBuy": 4.5,
    "pctChangeSell": 4.5,
    "qtyAdvRatio": 5,
}


def monitor_thresholds() -> dict:
    """MonitorBoard 默认阈值（版本化，供前端首次使用时取用）。"""
    return {"version": MONITOR_THRESHOLDS_VERSION, "monitor": dict(MONITOR_THRESHOLDS_DEFAULTS)}

#: 基线查询：tickers → {equ_ticker: MarketBaseline}（由路由层注入适配器）
BaselineLookup = Callable[[list], dict]


def intraday_state_enabled() -> bool:
    """特性开关（057 D-6 定稿默认开启；`EMSXVIEW_INTRADAY_STATE_ENABLED=false` 回到四字段）。"""
    from config import settings

    return settings.EMSXVIEW_INTRADAY_STATE_ENABLED


def _spread_bps(quote: dict) -> float | None:
    bid = quote.get("BID")
    ask = quote.get("ASK")
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2
    if mid <= 0:
        return None
    return (ask - bid) / mid * 10_000


def _quote_cache(bloomberg: Any) -> dict:
    """逐票报价缓存：门面公开属性优先，兼容私有属性（历史调用方/测试替身）。"""
    for name in ("intraday_quotes", "_intraday_quotes"):
        cache = getattr(bloomberg, name, None)
        if cache:
            return cache
    return {}


def _scalar_cache(bloomberg: Any, name: str) -> dict:
    """逐票单值缓存（如 price_changes）；缺失返回空字典。"""
    for attr in (name, f"_{name}"):
        cache = getattr(bloomberg, attr, None)
        if cache:
            return cache
    return {}


def _round2(value: Any) -> float | None:
    """数值四舍五入到 2 位；None / 非数值一律返回 None（不猜数）。"""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return round(number, 2)


def _pct_change_1d(quote: dict, pushed_change: Any) -> float | None:
    """实时涨跌幅（%）：优先 CHG_PCT_1D 推送，缺失时用最新价 ÷ 前收回落。

    实盘订阅实测（2026-10-28，本机终端）：CHG_PCT_1D 不在 mktdata 推送字段中，
    而 PREV_CLOSE_VALUE_REALTIME 可用，因此回落口径是工作站 Chg% 列的实际来源。
    前收缺失或非正数时返回 None（不猜数）。
    """
    pushed = _round2(pushed_change)
    if pushed is not None:
        return pushed
    try:
        last = float(quote.get("LAST_PRICE"))
        prev_close = float(quote.get("PREV_CLOSE_VALUE_REALTIME"))
    except (TypeError, ValueError):
        return None
    if prev_close <= 0 or last <= 0:
        return None
    return round((last / prev_close - 1) * 100, 2)


def build_market_state_snapshot(
    bloomberg: Any,
    *,
    baseline_lookup: BaselineLookup | None = None,
    tickers: list | tuple | set | None = None,
    now: datetime | None = None,
) -> MarketStateSnapshot:
    """从订阅缓存构建逐票盘中状态；无行情缓存/无数据时返回空快照（不猜数）。

    ``tickers`` 为可选白名单（MarketView 股票池工作站只关心池内标的）：
    只返回「既在订阅缓存、又在白名单内」的标的，避免把全量订单标的推给前端。
    """
    current = now or datetime.now()
    quotes: dict = _quote_cache(bloomberg)
    wanted = {ticker for ticker in (tickers or ()) if ticker}
    selected = sorted(ticker for ticker in quotes if not wanted or ticker in wanted)

    changes = _scalar_cache(bloomberg, "price_changes")

    baselines: dict = {}
    if baseline_lookup is not None and selected:
        try:
            baselines = baseline_lookup(selected) or {}
        except Exception:
            # 基线不可得 → 退化为无基线比较（披露于日志，不静默填 0）
            logger.warning("market-state baseline lookup failed", exc_info=True)

    states: list[MarketStateTickerState] = []
    for ticker in selected:
        quote = quotes.get(ticker) or {}
        spread = _spread_bps(quote)
        baseline: MarketBaseline | None = baselines.get(ticker)
        spread_vs: float | None = None
        flags: list[MarketStateFlag] = []
        if spread is not None and baseline is not None and baseline.spread_proxy_bps is not None:
            spread_vs = round(spread - baseline.spread_proxy_bps, 2)
            if spread_vs > THRESHOLDS.spread_vs_baseline_bps:
                flags.append(
                    MarketStateFlag(
                        code="SPREAD_VS_BASELINE_WIDE",
                        severity="WARN",
                        evidence=(
                            f"{spread_vs:.2f} bps > {THRESHOLDS.spread_vs_baseline_bps} bps "
                            f"(thresholds {THRESHOLDS.version})"
                        ),
                    )
                )
        states.append(
            MarketStateTickerState(
                equ_ticker=ticker,
                as_of=current.isoformat(timespec="seconds"),
                bid=quote.get("BID"),
                ask=quote.get("ASK"),
                last=quote.get("LAST_PRICE"),
                high=quote.get("HIGH"),
                low=quote.get("LOW"),
                volume=quote.get("VOLUME"),
                spread_bps=round(spread, 2) if spread is not None else None,
                spread_vs_baseline_bps=spread_vs,
                pct_change_1d=_pct_change_1d(quote, changes.get(ticker)),
                cumulative_volume_ratio=None,  # DL-09 预期曲线就绪前不可得
                flags=tuple(flags),
            )
        )
    return MarketStateSnapshot(
        as_of=current.isoformat(timespec="seconds"),
        enabled=True,
        tickers=tuple(states),
        thresholds=THRESHOLDS,
    )


def snapshot_payload(snapshot: MarketStateSnapshot) -> dict:
    """契约 → JSON（REST 与 WS 共用同一形状）。"""
    from dataclasses import asdict

    return asdict(snapshot)

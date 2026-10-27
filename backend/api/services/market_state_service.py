"""盘中市场状态服务（057 DL-15；C 层实时特征，特性开关默认关闭）。

从订阅缓存（`MarketDataEnrichmentService._intraday_quotes`）构建
`MarketStateSnapshot`：价差 bps、相对日度基线的差值与服务端版本化阈值告警。
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


def build_market_state_snapshot(
    bloomberg: Any,
    *,
    baseline_lookup: BaselineLookup | None = None,
    now: datetime | None = None,
) -> MarketStateSnapshot:
    """从订阅缓存构建逐票盘中状态；无行情缓存/无数据时返回空快照（不猜数）。"""
    current = now or datetime.now()
    quotes: dict = getattr(bloomberg, "_intraday_quotes", None) or {}
    tickers = sorted(quotes)

    baselines: dict = {}
    if baseline_lookup is not None and tickers:
        try:
            baselines = baseline_lookup(tickers) or {}
        except Exception:
            # 基线不可得 → 退化为无基线比较（披露于日志，不静默填 0）
            logger.warning("market-state baseline lookup failed", exc_info=True)

    states: list[MarketStateTickerState] = []
    for ticker in tickers:
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

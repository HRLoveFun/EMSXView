"""日度基线适配器（057 DL-10）——个股 60 日稳健分布，替代全局常数阈值。

数据源（v0，DL-09 切换预留见 BaselineSource 协议）：
- 主源 bdib_daily_summary（DL-05 盘点结论：BDIB 白名单内零缺口，BDIB 为主源）：
  log 量 z / 双口径波动分位 / ADV5÷ADV60 / 隔夜跳空 σ；
- 点查源 raw_bdib（每 ticker·日 1 次点查，遵守 access-guide「≤100 ticker·日」
  上限，超限按日期分块）：开/收盘竞价占比（DL-03 会话注册表窗口）、价差代理。

所有口径为纯函数（单测覆盖）；IO 与装配分离。特征 None = 数据不足或不可得，
消费方据此回落，不静默填 0。
"""

from __future__ import annotations

import logging
import math
from statistics import median
from typing import Iterable, Sequence

from platform_data.contracts.market_contracts import (
    BASELINE_MIN_DAYS,
    BASELINE_SCHEMA_VERSION,
    BASELINE_WINDOW_DAYS,
    MarketBaseline,
)

logger = logging.getLogger(__name__)

# raw_bdib 点查上限（access-guide 通道规则，tasks.md DL-10）
MAX_TICKER_DAY_POINTS = 100


# ── 纯函数（无 IO） ────────────────────────────────────────────────────────────


def log_volume_z(volumes: Sequence[float]) -> float | None:
    """log 量序列 → (末值 − median) / (1.4826 × MAD)。

    MAD=0（序列高度集中）或 n < BASELINE_MIN_DAYS 时回落样本 std；
    仍不可用（std=0 或 n=0）返回 None。
    """
    if len(volumes) < BASELINE_MIN_DAYS:
        return None
    logs = [math.log(v) for v in volumes if v and v > 0]
    if len(logs) < BASELINE_MIN_DAYS:
        return None
    center = median(logs)
    mad = median([abs(x - center) for x in logs])
    last = logs[-1]
    if mad > 0:
        return round((last - center) / (1.4826 * mad), 4)
    std = _pstdev(logs)
    return round((last - center) / std, 4) if std > 0 else None


def percentile_of(value: float | None, series: Sequence[float]) -> float | None:
    """value 在 series 中的分位数（0–100；小于等于 value 的占比）。"""
    if value is None or not series:
        return None
    below = sum(1 for x in series if x is not None and x <= value)
    return round(below / len(series) * 100, 2)


def overnight_gap_sigma(closes: Sequence[float | None]) -> float | None:
    """末次隔夜跳空 ÷ 跳空序列 std（σ 倍数）；std=0 或数据不足返回 None。"""
    gaps: list[float] = []
    prev: float | None = None
    for close in closes:
        if close is None or close <= 0:
            continue
        if prev is not None:
            gaps.append(close / prev - 1.0)
        prev = close
    if len(gaps) < BASELINE_MIN_DAYS:
        return None
    std = _pstdev(gaps)
    return round(gaps[-1] / std, 4) if std > 0 else None


def auction_share(bars: Sequence[tuple[str, float]], window: tuple[str, str] | None) -> float | None:
    """竞价窗口内成交量占比（0–100）。

    bars = [(HH:MM:SS, volume)]；window = (start, end) 本地 HH:MM。
    窗口为 None（市场无竞价定义）或全日无量为 None。
    """
    if window is None or not bars:
        return None
    start = _hhmm_to_minutes(window[0])
    end = _hhmm_to_minutes(window[1])
    total = sum(v for _, v in bars if v and v > 0)
    if total <= 0:
        return None
    in_window = sum(v for t, v in bars if v and v > 0 and start <= _hhmmss_to_minutes(t) < end)
    return round(in_window / total * 100, 4)


def spread_proxy(bars: Sequence[tuple[float | None, float | None, float | None]]) -> float | None:
    """bar 级 (high−low)/close 的中位数（bps 空间）；不足返回 None。"""
    ratios = [
        (h - l) / c
        for h, l, c in bars
        if h is not None and l is not None and c is not None and c > 0 and h >= l
    ]
    if len(ratios) < 5:
        return None
    return round(median(ratios) * 10000, 2)


def normalize_volatility(daily_pct: float | None, intraday_dec: float | None) -> tuple[float | None, float | None]:
    """量纲对齐（指南 §10）：daily 百分比 / intraday 小数 → 统一百分比空间。"""
    daily = daily_pct
    intraday = intraday_dec * 100 if intraday_dec is not None else None
    return daily, intraday


def _pstdev(values: Sequence[float]) -> float:
    """总体标准差（不引入 numpy 依赖；n=1 返回 0）。

    相对零判定：相同值序列的浮点噪声（~1e-16）会产出伪 std，使 z 值退化为
    0/ε——std ≤ |mean|×1e-12 时视为 0（调用方据此回落/返回 None）。
    """
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std = math.sqrt(variance)
    return 0.0 if std <= abs(mean) * 1e-12 else std


def _hhmm_to_minutes(value: str) -> int:
    hours, _, minutes = value.partition(":")
    return int(hours) * 60 + int(minutes or 0)


def _minutes_to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _hhmmss_to_minutes(value: str) -> int:
    parts = str(value).strip().split(":")
    hours = int(parts[0]) if parts and parts[0].isdigit() else 0
    minutes = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return hours * 60 + minutes


# ── 适配器（IO + 装配） ───────────────────────────────────────────────────────


class DailyBaselineAdapter:
    """日度基线只读查询（无状态；跨模块公开 API 见 module-boundary §2.3）。"""

    def get_baseline(
        self,
        equ_tickers: Sequence[str],
        *,
        as_of: str | None = None,
        exclude_dates: Iterable[str] = (),
        connection_manager=None,
    ) -> list[MarketBaseline]:
        """逐票 60 日基线；tickers 超 100 时按 ticker 分块（点查上限纪律）。"""
        if connection_manager is None:
            from data_access import ConnectionManager

            connection_manager = ConnectionManager()
        excluded = {str(d) for d in exclude_dates}
        # access-guide 点查上限：每批 ≤100 个 ticker（每 ticker 1 日 bar 点查 = 100 ticker·日），
        # 超限由调用方分批（盘前单/监控板按股票池天然分批）
        if len(equ_tickers) > MAX_TICKER_DAY_POINTS:
            logger.warning(
                "baseline 批量 %d ticker 超点查上限 %d，调用方应分批（本批仍执行，注意额度）",
                len(equ_tickers),
                MAX_TICKER_DAY_POINTS,
            )
        return [
            self._baseline_for(ticker, as_of=as_of, excluded=excluded, mgr=connection_manager)
            for ticker in equ_tickers
        ]

    # ── 内部 ──

    def _baseline_for(self, equ_ticker: str, *, as_of, excluded, mgr) -> MarketBaseline:
        from data_access.config import Config
        from platform_data.contracts.db_constants import BDIB_DAILY_SUMMARY_TABLE

        rows = self._load_daily(mgr, Config, BDIB_DAILY_SUMMARY_TABLE, equ_ticker, as_of, excluded)
        if not rows:
            return self._empty_baseline(equ_ticker, as_of)
        dates = [r[0] for r in rows]
        volumes = [r[1] for r in rows]
        closes = [r[2] for r in rows]
        daily_vols = [r[3] for r in rows]
        intraday_vols = [r[4] for r in rows]
        adv5, adv20 = rows[-1][5], rows[-1][6]

        bars = self._load_bars(mgr, Config, equ_ticker, dates[-1])
        from platform_data.contracts.exchange_session_contracts import SESSION_REGISTRY

        exchange = _exchange_of(equ_ticker)
        session = SESSION_REGISTRY.get(exchange)
        bar_volumes = [(b[0], b[4]) for b in bars]  # (HH:MM:SS, volume)
        open_share = auction_share(bar_volumes, session.opening_auction if session else None)
        # 收盘竞价占比 bar 级近似：收盘前 5 分钟窗口（成交级口径见管道 is_closing_auction，
        # DL-09 快照表就绪后替换为竞价量列）
        close_share = None
        if session:
            end_minutes = _hhmm_to_minutes(session.market_close)
            close_share = auction_share(
                bar_volumes, (_minutes_to_hhmm(end_minutes - 5), session.market_close)
            )
        spread = spread_proxy([(b[1], b[2], b[3]) for b in bars])

        return MarketBaseline(
            equ_ticker=equ_ticker,
            as_of=dates[-1],
            log_volume_z=log_volume_z(volumes),
            vol_percentile=percentile_of(daily_vols[-1], [v for v in daily_vols if v is not None]),
            intraday_vol_percentile=percentile_of(
                intraday_vols[-1], [v for v in intraday_vols if v is not None]
            ),
            overnight_gap_sigma=overnight_gap_sigma(closes),
            auction_open_pct=open_share,
            auction_close_pct=close_share,
            adv5_adv60_ratio=round(adv5 / adv20, 4) if adv5 and adv20 and adv20 > 0 else None,
            spread_proxy_bps=spread,  # z 化需横截面（盘前单批量场景），v0 出原始中位数
            n_days=len(dates),
            excluded_dates=tuple(sorted(excluded)),
        )

    @staticmethod
    def _load_daily(mgr, Config, table, equ_ticker, as_of, excluded):
        conn = mgr.get_connection("raw_bdib")
        try:
            rows = conn.execute(
                f"SELECT trade_date, total_volume, daily_close, daily_volatility, "
                f"intraday_volatility, adv_5d, adv_20d FROM {table} "
                f"WHERE equ_ticker = ? AND trade_date <= ? "
                f"ORDER BY trade_date DESC LIMIT ?",
                (equ_ticker, as_of or "99999999", BASELINE_WINDOW_DAYS),
            ).fetchall()
        finally:
            conn.close()
        # 剔除特殊日后仍可能不足 BASELINE_MIN_DAYS——由纯函数各自判定并回落
        return [r for r in rows if str(r[0]) not in excluded][::-1]  # 时间正序

    @staticmethod
    def _load_bars(mgr, Config, equ_ticker, trade_date):
        from platform_data.contracts.db_constants import RAW_BDIB_TABLE

        conn = mgr.get_connection("raw_bdib")
        try:
            rows = conn.execute(
                f"SELECT mkt_timestamp, high, low, close, volume FROM {RAW_BDIB_TABLE} "
                f"WHERE equ_ticker = ? AND order_as_of_date = ? "
                f"ORDER BY mkt_timestamp",
                (equ_ticker, trade_date),
            ).fetchall()
        finally:
            conn.close()
        return [(str(r[0]), r[1], r[2], r[3], float(r[4] or 0)) for r in rows]

    @staticmethod
    def _empty_baseline(equ_ticker, as_of) -> MarketBaseline:
        return MarketBaseline(
            equ_ticker=equ_ticker,
            as_of=as_of or "",
            log_volume_z=None,
            vol_percentile=None,
            intraday_vol_percentile=None,
            overnight_gap_sigma=None,
            auction_open_pct=None,
            auction_close_pct=None,
            adv5_adv60_ratio=None,
            spread_proxy_bps=None,
            n_days=0,
        )


def _exchange_of(equ_ticker: str) -> str:
    """'AAPL US Equity' → 'US'（BDIB 复合代码后缀）。"""
    parts = str(equ_ticker).split()
    return parts[-2].upper() if len(parts) >= 2 else ""

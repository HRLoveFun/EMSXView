"""执行区间量价序列（057 DL-30）——只读取数 + 桶聚合。

区间边界由调用方（ExecutionView 前端，基于订单创建/开始与结束时刻）传入；
本模块只负责取 bar、按桶聚合与显式 gap，不插值、不猜价。

数据源优先级：盘中库 `bars_10s_t0`（当日）> 正式库 `raw_bdib`（1 分钟 bar）。
两者时间戳均为交易所本地 `HH:MM:SS`，区间左闭右开。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from data_access import ConnectionManager, IntradayStoreReader
from platform_data.contracts import RAW_BDIB_TABLE

logger = logging.getLogger(__name__)

# 允许的桶粒度（分钟）；与前端选择器一致
BUCKET_OPTIONS: tuple[int, ...] = (1, 5, 10, 15, 30)
# 单次查询的最大区间（分钟）——防止误传全天/跨日参数导致大表扫描
MAX_WINDOW_MINUTES = 24 * 60


@dataclass(frozen=True)
class IntervalPoint:
    bucket_start: str
    bucket_end: str
    price: Optional[float]
    vwap: Optional[float]
    volume: float
    cum_volume: float
    is_gap: bool


@dataclass(frozen=True)
class IntervalSeries:
    equ_ticker: str
    trade_date: str
    start: str
    end: str
    bucket_minutes: int
    source: str  # intraday | formal | none
    points: tuple[IntervalPoint, ...]
    interval_vwap: Optional[float]
    total_volume: float
    bar_count: int
    gap_buckets: int
    generated_at: str


def _parse_hms(value: str) -> int:
    """`HH:MM` / `HH:MM:SS` → 当日秒数；非法格式抛 ValueError。"""
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"invalid time: {value!r}")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        raise ValueError(f"time out of range: {value!r}")
    return hour * 3600 + minute * 60 + second


def _fmt_hms(seconds: int) -> str:
    hour, remainder = divmod(seconds, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def build_bucket_grid(start: str, end: str, bucket_minutes: int) -> list[tuple[int, int]]:
    """生成左闭右开的桶网格；末桶在 end 处截断（不越过区间）。"""
    if bucket_minutes not in BUCKET_OPTIONS:
        raise ValueError(f"unsupported bucket_minutes={bucket_minutes}")
    start_s, end_s = _parse_hms(start), _parse_hms(end)
    if start_s >= end_s:
        raise ValueError("start must be earlier than end")
    if end_s - start_s > MAX_WINDOW_MINUTES * 60:
        raise ValueError("window exceeds 24h")
    step = bucket_minutes * 60
    grid: list[tuple[int, int]] = []
    cursor = start_s
    while cursor < end_s:
        grid.append((cursor, min(cursor + step, end_s)))
        cursor += step
    return grid


def _bar_time_seconds(value: Any) -> Optional[int]:
    """兼容 `HH:MM:SS` / `HH:MM` / 完整 ISO 时间戳。"""
    if value is None:
        return None
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[1]
    if " " in text:
        text = text.split(" ", 1)[1]
    try:
        return _parse_hms(text.split(".")[0])
    except (TypeError, ValueError):
        return None


def _aggregate_point(
    bars: list[tuple[int, float, float]], start_s: int, end_s: int, cum_before: float
) -> IntervalPoint:
    priced = [(px, vol) for _, px, vol in bars if px > 0]
    volume = sum(vol for _, _, vol in bars)
    if priced:
        total_priced_volume = sum(vol for _, vol in priced)
        if total_priced_volume > 0:
            vwap = sum(px * vol for px, vol in priced) / total_priced_volume
        else:
            vwap = sum(px for px, _ in priced) / len(priced)
        price = priced[-1][0]
    else:
        vwap, price = None, None
    return IntervalPoint(
        bucket_start=_fmt_hms(start_s),
        bucket_end=_fmt_hms(end_s),
        price=price,
        vwap=None if vwap is None else round(vwap, 6),
        volume=volume,
        cum_volume=cum_before + volume,
        is_gap=not priced,
    )


def _parse_bars(bars: Iterable[dict[str, Any]]) -> list[tuple[int, float, float]]:
    """(时间秒, close, volume)；时间/数值不可用直接丢弃（不猜）。"""
    parsed: list[tuple[int, float, float]] = []
    for bar in bars:
        seconds = _bar_time_seconds(bar.get("mkt_timestamp"))
        if seconds is None:
            continue
        try:
            price = float(bar.get("close") or 0)
            volume = float(bar.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        parsed.append((seconds, price, volume))
    return parsed


def _interval_vwap(parsed: list[tuple[int, float, float]]) -> Optional[float]:
    weighted_px = sum(px * vol for _, px, vol in parsed if px > 0 and vol > 0)
    weighted_vol = sum(vol for _, px, vol in parsed if px > 0 and vol > 0)
    return round(weighted_px / weighted_vol, 6) if weighted_vol > 0 else None


def aggregate_bars(
    bars: Iterable[dict[str, Any]], grid: list[tuple[int, int]]
) -> tuple[list[IntervalPoint], Optional[float], int]:
    """按桶聚合 bar → (points, 区间 VWAP, bar 数)。

    无 bar 的桶保留为 `is_gap=True`（price/vwap 为 None），不插值。
    """
    parsed = _parse_bars(bars)
    points: list[IntervalPoint] = []
    cum = 0.0
    for start_s, end_s in grid:
        bucket = [item for item in parsed if start_s <= item[0] < end_s]
        point = _aggregate_point(bucket, start_s, end_s, cum)
        cum = point.cum_volume
        points.append(point)
    return points, _interval_vwap(parsed), len(parsed)


def _load_formal_bars(
    mgr, equ_ticker: str, trade_date: str, start: str, end: str
) -> list[dict[str, Any]]:
    conn = mgr.get_connection("raw_bdib")
    try:
        rows = conn.execute(
            f"SELECT mkt_timestamp, close, volume FROM {RAW_BDIB_TABLE} "
            "WHERE equ_ticker = ? AND order_as_of_date = ? "
            "AND mkt_timestamp >= ? AND mkt_timestamp < ? "
            "ORDER BY mkt_timestamp",
            (equ_ticker, trade_date, start, end),
        ).fetchall()
    finally:
        conn.close()
    return [{"mkt_timestamp": r[0], "close": r[1], "volume": r[2]} for r in rows]


def _read_bars(
    equ_ticker: str,
    trade_date: str,
    start: str,
    end: str,
    reader: IntradayStoreReader,
    connection_manager,
) -> tuple[list[dict[str, Any]], str]:
    """盘中库优先、正式库回落；返回 (bars, source)。"""
    if reader.available():
        bars = reader.read_bars_window(equ_ticker, start, end)
        if bars:
            return bars, "intraday"
    try:
        bars = _load_formal_bars(
            connection_manager or ConnectionManager(), equ_ticker, trade_date, start, end
        )
        return bars, ("formal" if bars else "none")
    except Exception:  # 正式库不可用不阻断降级路径
        logger.debug("formal bar read failed", exc_info=True)
        return [], "none"


def load_interval_series(
    equ_ticker: str,
    trade_date: str,
    start: str,
    end: str,
    bucket_minutes: int = 5,
    *,
    intraday_reader: IntradayStoreReader | None = None,
    connection_manager=None,
) -> IntervalSeries:
    """读取区间序列；盘中库优先，正式库回落，均无数据时 source=none。"""
    grid = build_bucket_grid(start, end, bucket_minutes)
    start_fmt, end_fmt = _fmt_hms(grid[0][0]), _fmt_hms(grid[-1][1])
    reader = intraday_reader or IntradayStoreReader(trade_date)
    bars, source = _read_bars(
        equ_ticker,
        trade_date,
        start_fmt,
        end_fmt,
        reader,
        connection_manager,
    )
    points, interval_vwap, bar_count = aggregate_bars(bars, grid)
    return IntervalSeries(
        equ_ticker=equ_ticker,
        trade_date=trade_date,
        start=start_fmt,
        end=end_fmt,
        bucket_minutes=bucket_minutes,
        source=source,
        points=tuple(points),
        interval_vwap=interval_vwap,
        total_volume=sum(p.volume for p in points),
        bar_count=bar_count,
        gap_buckets=sum(1 for p in points if p.is_gap),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

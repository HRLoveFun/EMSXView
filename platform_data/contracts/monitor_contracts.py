"""MarketView 监控台契约（057 节点一重定义）。

监控台 = 高亮信息面板 + 监控表 + 行详情三联图。本模块只定义跨模块数据结构，
不含业务逻辑与数据库访问；取数在 ``platform_data.adapters.monitor``，装配在
``MarketView/routers/monitor_board.py``。

口径约定（与消费方一致）：

- ``last`` 是当日最后一根 bar 的收盘价；``close`` 是日度基线（``bdib_daily_summary``）
  的最新收盘价，用于与 ``last`` 对照。两者日期分别由 ``trade_date`` /
  ``baseline_date`` 标注，缺一则显式为 ``None``，禁止互相顶替。
- ``vol_vs_adv20`` 为百分比数值（55.0 表示 55%），分母缺失时整体为 ``None``。
- 累计量占比一律压到 0–1，除以各自当日总量；前五日均值按同一时间桶对齐，
  只在当日有该桶的交易日上取均值。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MonitorPoolMember:
    """池成员：equ_ticker + 展示名 + 行情交易所码 + 会话市场码。"""

    equ_ticker: str
    name: str | None
    exchange: str
    market_code: str


@dataclass(frozen=True)
class MonitorQuote:
    """单票监控行（表格 14 列 + 来源标注）。"""

    equ_ticker: str
    trade_date: str | None = None
    baseline_date: str | None = None
    last: float | None = None
    prev_close: float | None = None
    chg_pct: float | None = None
    close: float | None = None
    total_volume: float | None = None
    adv_20d: float | None = None
    adv_5d: float | None = None
    vol_vs_adv20: float | None = None
    daily_volatility: float | None = None
    intraday_volatility: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    first_bar_time: str | None = None
    last_bar_time: str | None = None
    bar_count: int = 0
    liquidity: str = "none"
    volatility: str = "none"
    gaps: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetailBucket:
    """详情图共用时间桶：当日量/累计量/占比 + 桶内 OHLC（供逐桶 OHLC 点）。"""

    index: int
    label: str
    volume: float | None = None
    cumulative_volume: float | None = None
    cumulative_pct: float | None = None
    vwap: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    gap: bool = False


@dataclass(frozen=True)
class PrevBucket:
    """前 N 个交易日均值曲线（按同一时间桶对齐）。"""

    index: int
    label: str
    cumulative_volume: float | None = None
    cumulative_pct: float | None = None


@dataclass(frozen=True)
class DetailCell:
    """价格—成交量分布格：某时间桶内落到某价格分档的成交量。"""

    bucket: int
    price_bin: int
    volume: float


@dataclass(frozen=True)
class TickerDetail:
    """行详情三联图数据（价格量分布 / 累计量 / 累计量占比）。"""

    equ_ticker: str
    trade_date: str | None = None
    bucket_minutes: int = 10
    market_code: str | None = None
    session_open: str | None = None
    session_close: str | None = None
    session_note: str = ""
    buckets: tuple[DetailBucket, ...] = ()
    prev_buckets: tuple[PrevBucket, ...] = ()
    prev_days: int = 0
    prev_dates: tuple[str, ...] = ()
    ohlc: dict[str, float | None] = field(default_factory=dict)
    #: 前一交易日收盘（右侧百分比轴的分母）；缺失时前端不画百分比轴
    prev_close: float | None = None
    price_low: float | None = None
    price_high: float | None = None
    price_bin_count: int = 0
    cells: tuple[DetailCell, ...] = ()
    total_volume: float | None = None
    prev_avg_volume: float | None = None
    gaps: tuple[str, ...] = ()
    source: str = "raw_bdib"

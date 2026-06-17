"""S7 阶段的 daily_metrics 模式定义。

对应 bdib_daily_summary 表，包含日均成交量和波动率等日度指标。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DailyMetricsSchema(BaseModel):
    """日度指标模式 — 对应 S7（CalculateDailyMetrics）的输出。

    使用 STRICT 策略。
    """

    # 标识
    equ_ticker: str = Field(min_length=1, description="股票代码")
    date: str = Field(min_length=1, description="日期 (YYYY-MM-DD)")
    Exchange: str | None = Field(default=None, description="交易所")

    # 核心指标
    adv: float = Field(ge=0, description="日均成交量 (ADV)")
    adv_volume: float | None = Field(default=None, description="日均成交量（股数）")
    volatility: float = Field(ge=0, description="日内波动率")
    vwap: float | None = Field(default=None, ge=0, description="成交量加权平均价")
    close_price: float | None = Field(default=None, ge=0, description="收盘价")
    open_price: float | None = Field(default=None, ge=0, description="开盘价")

    # 市场数据
    volume: float | None = Field(default=None, ge=0, description="总成交量")
    high_price: float | None = Field(default=None, ge=0, description="最高价")
    low_price: float | None = Field(default=None, ge=0, description="最低价")
    spread_bps: float | None = Field(default=None, description="价差 (bps)")

    # 其他
    region: str | None = Field(default=None, description="地区")
    num_fills: int | None = Field(default=None, ge=0, description="成交笔数")
    total_fill_amount: float | None = Field(default=None, ge=0, description="总成交金额")

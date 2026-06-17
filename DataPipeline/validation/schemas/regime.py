"""S8/S9 阶段的 regime 模式定义。

RegimeSchema 被 S8（RegimeDailyFeatures）和 S9（RegimeFillTagger）共享使用。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegimeSchema(BaseModel):
    """市场状态模式 — 对应 S8（RegimeDailyFeatures）和 S9（RegimeFillTagger）。

    使用 STRICT 策略。
    """

    # 标识
    equ_ticker: str = Field(min_length=1, description="股票代码")
    date: str = Field(min_length=1, description="日期 (YYYY-MM-DD)")

    # 波动率状态特征
    vol_regime: str | None = Field(default=None, description="波动率状态")
    vol_percentile: float | None = Field(default=None, ge=0, le=100, description="波动率百分位")

    # 流动性状态特征
    liq_regime: str | None = Field(default=None, description="流动性状态")
    liq_percentile: float | None = Field(default=None, ge=0, le=100, description="流动性百分位")

    # 趋势状态特征
    trend_regime: str | None = Field(default=None, description="趋势状态")
    trend_strength: float | None = Field(default=None, description="趋势强度")

    # 综合状态
    composite_regime: str | None = Field(default=None, description="综合状态标签")
    regime_score: float | None = Field(default=None, description="状态评分")

    # 原始特征值
    volatility: float | None = Field(default=None, ge=0, description="波动率")
    adv: float | None = Field(default=None, ge=0, description="日均成交量")
    spread_bps: float | None = Field(default=None, description="价差 (bps)")

    # S9 相关字段（FillTagger 特有）
    FillId: int | None = Field(default=None, gt=0, description="成交 ID")
    fill_regime_tag: str | None = Field(default=None, description="成交状态标签")

"""S10 阶段的 attribution 模式定义。

对应归因分析指标表，包含 Implementation Shortfall、VWAP 偏差、价格反转等归因指标。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AttributionSchema(BaseModel):
    """归因指标模式 — 对应 S10（AttributionMetrics）的输出。

    使用 STRICT 策略。
    """

    # 标识
    FillId: int = Field(gt=0, description="成交 ID")
    OrderId: int = Field(gt=0, description="订单 ID")
    equ_ticker: str | None = Field(default=None, description="股票代码")
    date: str | None = Field(default=None, min_length=1, description="日期")

    # Implementation Shortfall 分解
    is_total_bps: float | None = Field(default=None, description="总 IS (bps)")
    is_delay_bps: float | None = Field(default=None, description="延迟成本 (bps)")
    is_trading_bps: float | None = Field(default=None, description="交易成本 (bps)")
    is_opportunity_bps: float | None = Field(default=None, description="机会成本 (bps)")

    # VWAP 偏差
    vwap_deviation_bps: float | None = Field(default=None, description="VWAP 偏差 (bps)")
    vwap_benchmark_price: float | None = Field(default=None, ge=0, description="VWAP 基准价格")

    # 价格反转
    reversal_bps: float | None = Field(default=None, description="价格反转 (bps)")
    reversal_benchmark_price: float | None = Field(default=None, ge=0, description="反转基准价格")

    # 执行信息
    FillPrice: float = Field(ge=0, description="成交价格")
    FillShares: float = Field(ge=0, description="成交数量")
    Side: str | None = Field(default=None, description="买卖方向")
    arrival_price: float | None = Field(default=None, ge=0, description="到达价格")
    close_price: float | None = Field(default=None, ge=0, description="收盘价")

    # 执行质量
    participation_rate: float | None = Field(default=None, ge=0, le=100, description="参与率 (%)")
    execution_quality_score: float | None = Field(default=None, description="执行质量评分")

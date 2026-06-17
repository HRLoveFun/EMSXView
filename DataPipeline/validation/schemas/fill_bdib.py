"""S5 阶段的 fill_bdib 模式定义。

BDIB（日内 K 线数据）集成后的合并字段，对应 fill_bdib 表。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FillBdibSchema(BaseModel):
    """BDIB 集成后数据模式 — 对应 S5（IntegrateBDIB）的输出，S7/S9 的输入。

    使用 STRICT 策略。
    """

    # 主键
    FillId: int = Field(gt=0, description="成交 ID")
    OrderId: int = Field(gt=0, description="订单 ID")
    RouteId: int = Field(gt=0, description="路由 ID")

    # 成交信息
    FillPrice: float = Field(ge=0, description="成交价格")
    FillShares: float = Field(ge=0, description="成交数量")
    Amount: float = Field(ge=0, description="成交金额")
    Side: str | None = Field(default=None, description="买卖方向")
    ExecType: str | None = Field(default=None, description="执行类型")

    # 证券信息
    equ_ticker: str | None = Field(default=None, description="股票代码")
    Exchange: str | None = Field(default=None, description="交易所")
    region: str | None = Field(default=None, description="地区")

    # 时间
    mkt_timestamp: str | None = Field(default=None, description="市场时间戳")
    order_as_of_date: str | None = Field(default=None, description="订单日期")
    DateTimeOfFill: str | None = Field(default=None, description="成交时间")

    # BDIB 集成字段
    bdib_price: float | None = Field(default=None, description="BDIB 参考价格")
    bdib_volume: float | None = Field(default=None, description="BDIB 成交量")
    bdib_vwap: float | None = Field(default=None, description="BDIB VWAP")
    bdib_arrival_price: float | None = Field(default=None, description="BDIB 到达价格")
    bdib_spread_bps: float | None = Field(default=None, description="BDIB 价差 (bps)")
    bdib_volatility: float | None = Field(default=None, description="BDIB 波动率")
    bdib_adv: float | None = Field(default=None, description="BDIB 日均成交量")

    # 其他
    Broker: str | None = Field(default=None, description="经纪商")
    StrategyType: str | None = Field(default=None, description="策略类型")

"""S1/S2 阶段的 raw_fills 模式定义。

字段名与 ``DataPipeline/storage/schema/columns.py`` 中的
``EMSX_FILL_COLUMNS`` 保持一致。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RawFillsSchema(BaseModel):
    """原始成交数据模式 — 对应 S1（IngestExcel）的输出和 S2 的输入。

    S1 使用 RELAXED 策略：仅校验类型，不校验值域约束和必填字段。
    """

    # 主键字段
    OrderId: int | None = Field(default=None, description="订单 ID")
    FillId: int | None = Field(default=None, description="成交 ID")
    RouteId: int | None = Field(default=None, description="路由 ID")

    # 证券信息
    SecurityName: str | None = Field(default=None, description="证券名称")
    Ticker: str | None = Field(default=None, description="代码")
    Exchange: str | None = Field(default=None, description="交易所")
    Currency: str | None = Field(default=None, description="币种")
    LocalExchangeSymbol: str | None = Field(default=None, description="本地交易所代码")

    # 交易信息
    Side: str | None = Field(default=None, description="买卖方向")
    Amount: float | None = Field(default=None, description="成交金额")
    FillPrice: float | None = Field(default=None, description="成交价格")
    FillShares: float | None = Field(default=None, description="成交数量")
    RouteShares: float | None = Field(default=None, description="路由数量")
    Type: str | None = Field(default=None, description="订单类型")
    LimitPrice: float | None = Field(default=None, description="限价")
    StopPrice: float | None = Field(default=None, description="止损价")

    # 执行信息
    ExecType: str | None = Field(default=None, description="执行类型")
    LastCapacity: str | None = Field(default=None, description="最后容量")
    LastMarket: str | None = Field(default=None, description="最后市场")
    Liquidity: str | None = Field(default=None, description="流动性")

    # 经纪商和策略
    Broker: str | None = Field(default=None, description="经纪商")
    StrategyType: str | None = Field(default=None, description="策略类型")
    TraderName: str | None = Field(default=None, description="交易员名称")
    TraderUuid: str | None = Field(default=None, description="交易员 UUID")

    # 账户
    Account: str | None = Field(default=None, description="账户")

    # 时间字段
    NyOrderCreateAsOfDateTime: str | None = Field(default=None, description="订单创建时间（纽约时间）")
    NyTranCreateAsOfDateTime: str | None = Field(default=None, description="交易创建时间（纽约时间）")
    DateTimeOfFill: str | None = Field(default=None, description="成交时间")

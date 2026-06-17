"""S2/S3/S4 阶段的 processed_fills 模式定义。

ProcessedFillsSchema：S2/S3/S4 共享的基类，字段与 PROCESSED_COLUMNS 一致。
AggregateFillsSchema：S3 专用，扩展聚合特有字段。
OrderLabelsSchema：S4 专用，扩展标签特有字段。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProcessedFillsSchema(BaseModel):
    """处理后成交数据基类模式 — 对应 S2 的输出，S3/S4 的输入。

    使用 STRICT 策略：完整校验（类型+值域+必填）。
    """

    # 主键
    FillId: int = Field(gt=0, description="成交 ID")
    OrderId: int = Field(gt=0, description="订单 ID")
    RouteId: int = Field(gt=0, description="路由 ID")

    # 时间字段
    mkt_timestamp: str | None = Field(default=None, description="市场时间戳")
    order_as_of_date: str | None = Field(default=None, description="订单日期")
    local_fill_datetime: str | None = Field(default=None, description="本地成交时间")
    exchange_exec_time: str | None = Field(default=None, description="交易所执行时间")
    route_as_of_time: str | None = Field(default=None, description="路由时间")
    DateTimeOfFill: str | None = Field(default=None, description="成交时间")

    # 经纪商/策略/交易员
    Broker: str | None = Field(default=None, description="经纪商")
    StrategyType: str | None = Field(default=None, description="策略类型")
    algo: str | None = Field(default=None, description="算法")
    TraderName: str | None = Field(default=None, description="交易员名称")

    # 交易信息
    Exchange: str | None = Field(default=None, description="交易所")
    Amount: float = Field(ge=0, description="成交金额")
    RouteShares: float = Field(ge=0, description="路由数量")
    FillPrice: float = Field(ge=0, description="成交价格")
    FillShares: float = Field(ge=0, description="成交数量")

    # 其他
    is_closing_auction: int = Field(default=0, description="是否收盘竞价")
    ExecType: str | None = Field(default=None, description="执行类型")
    region: str | None = Field(default=None, description="地区")
    equ_ticker: str | None = Field(default=None, description="股票代码")


class AggregateFillsSchema(ProcessedFillsSchema):
    """S3（AggregateFills）专用模式 — 扩展聚合字段。

    在 ProcessedFillsSchema 基础上增加聚合相关字段。
    """

    # 聚合字段（可选，来自 AGG_COLUMNS）
    Ticker: str | None = Field(default=None, description="原始代码")
    Side: str | None = Field(default=None, description="买卖方向")
    Currency: str | None = Field(default=None, description="币种")
    ccy_ticker: str | None = Field(default=None, description="货币代码")


class OrderLabelsSchema(ProcessedFillsSchema):
    """S4（GenerateOrderLabels）专用模式 — 扩展标签字段。

    在 ProcessedFillsSchema 基础上增加订单标签相关字段。
    """

    # 标签字段（可选）
    ccy_ticker: str | None = Field(default=None, description="货币代码")
    Side: str | None = Field(default=None, description="买卖方向")

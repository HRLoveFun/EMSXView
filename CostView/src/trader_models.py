"""交易员复盘台契约模型（与前端 TS 类型一一对应）。

PR-1 范围：订单列表（TraderOrderRow）与筛选项 / 质量探针所需的最小契约。
订单详情（TraderOrderDetail）、peer（PeerStats / Hint）随 PR-2 起补入，
不在本批定义未使用的模型（懒惰协议：只写解决问题所需）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class TraderFilters:
    """订单列表筛选与分页参数（trader_query / trader_service 共用）。

    维度筛选（trader/ticker/side/strategy_type/algo/broker）为多值 IN 语义，
    订单级命中 = **任一路由命中**（方案 §4.1）；指标仍按全部路由聚合。
    """

    start_date: str
    end_date: str
    trader: Optional[tuple[str, ...]] = None
    ticker: Optional[tuple[str, ...]] = None
    side: Optional[tuple[str, ...]] = None
    strategy_type: Optional[tuple[str, ...]] = None
    algo: Optional[tuple[str, ...]] = None
    broker: Optional[tuple[str, ...]] = None
    completion_bucket: Optional[str] = None
    quality: Optional[str] = None
    sort: str = "date"
    sort_dir: str = "desc"
    limit: int = 50
    offset: int = 0

    def to_payload(self) -> dict[str, Any]:
        """回显给前端的筛选快照（响应 `filters` 字段）。"""
        payload: dict[str, Any] = {
            "start_date": self.start_date,
            "end_date": self.end_date,
        }
        for key in ("trader", "ticker", "side", "strategy_type", "algo", "broker"):
            values = getattr(self, key)
            if values:
                payload[key] = list(values)
        for key in ("completion_bucket", "quality", "sort", "sort_dir"):
            payload[key] = getattr(self, key)
        return payload


@dataclass
class TraderOrderRow:
    """订单列表行（P0 复盘台主表）。None 表示不可得，前端显示「—」，禁止用 0 代替。"""

    order_id: str
    order_as_of_date: str
    trader_name: Optional[str]
    equ_ticker: Optional[str]
    exchange: Optional[str]
    side: Optional[str]
    strategy_type: Optional[str]
    algo: Optional[str]
    broker: Optional[str]
    route_count: int
    fill_count: Optional[int]
    route_shares: Optional[float]
    fill: Optional[float]
    completion: Optional[float]
    vwap: Optional[float]
    arrival_cost_bps: Optional[float]
    opportunity_cost: Optional[float]
    order_duration_sec: Optional[float]
    mixed: bool
    quality_level: str
    quality_flags: list[str] = field(default_factory=list)
    #: 当前页逐笔补充列（PR-2 接入 processed_fills / raw_fills 后填充）
    fill_span_sec: Optional[float] = None
    speed_shares_per_min: Optional[float] = None
    passive_ratio: Optional[float] = None

    def to_payload(self) -> dict[str, Any]:
        """序列化为 API 行（quality 合并为 {level, flags}，与契约示例一致）。"""
        return {
            "order_id": self.order_id,
            "order_as_of_date": self.order_as_of_date,
            "trader_name": self.trader_name,
            "equ_ticker": self.equ_ticker,
            "exchange": self.exchange,
            "side": self.side,
            "strategy_type": self.strategy_type,
            "algo": self.algo,
            "broker": self.broker,
            "route_count": self.route_count,
            "fill_count": self.fill_count,
            "route_shares": self.route_shares,
            "fill": self.fill,
            "completion": self.completion,
            "vwap": self.vwap,
            "arrival_cost_bps": self.arrival_cost_bps,
            "opportunity_cost": self.opportunity_cost,
            "order_duration_sec": self.order_duration_sec,
            "fill_span_sec": self.fill_span_sec,
            "speed_shares_per_min": self.speed_shares_per_min,
            "passive_ratio": self.passive_ratio,
            "mixed": self.mixed,
            "quality": {"level": self.quality_level, "flags": self.quality_flags},
        }


@dataclass
class ProbeCheck:
    """质量探针单条检查（全局横幅 4 类，始终返回，0 触发也可见）。"""

    id: str
    checked: bool
    triggered: Optional[int]
    affected_kpis: list[str]
    note: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "checked": self.checked,
            "triggered": self.triggered,
            "affected_kpis": self.affected_kpis,
            "note": self.note,
        }

"""TCA cross-module contracts.

Defines the stable data types for Transaction Cost Analysis that CostView
publishes and ExecutionView consumes. Each contract is a pure dataclass
with no business logic, no DB imports, and no external dependencies beyond
the standard library.

Ownership:
  - CostView owns the data; these contracts are the projection it publishes.
  - Consumers (ExecutionView, MarketView) import from this package only.
  - When CostView's internal DTOs evolve, contracts are updated here with
    an explicit version bump so downstream breakage is caught early.

Canonical source of TCA cross-module types (Iteration 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── Scorecard cohort dimension registry ────────────────────────────────────────

SCORECARD_COHORTS: tuple[str, ...] = (
    "broker",
    "strategy",
    "broker_strategy",
    "asset_class",
    "time_of_day",
    "liquidity_adv20",
    "volatility",
)


# ── TCA filter / report contracts ─────────────────────────────────────────────

@dataclass
class TcaFilters:
    """Filter specification for a TCA query.

    All fields are optional. An empty TcaFilters instance defaults to the
    most recent available trading day.
    """
    order_ids: Optional[list[str]] = None
    algo: Optional[str] = None
    start_date: Optional[str] = None   # YYYYMMDD
    end_date: Optional[str] = None     # YYYYMMDD
    broker: Optional[str] = None
    symbol: Optional[str] = None       # equ_ticker  e.g. "AAPL US Equity"
    aggregation: str = "per_order"     # "per_order" | "aggregated"
    limit: int = 50
    offset: int = 0


@dataclass
class TcaRouteSummary:
    """路由级 TCA 汇总，严格匹配新 schema 55 个字段（17 源值 + 38 计算指标）。"""
    # ── Group 1: Source values (17) ──
    OrderId: str
    RouteId: str
    order_as_of_date: str
    Exchange: Optional[str]
    Account: Optional[str]
    equ_ticker: Optional[str]
    Currency: Optional[str]
    Side: Optional[str]
    Amount: Optional[float]
    RouteShares: Optional[float]
    Type: Optional[str]
    LimitPrice: Optional[float]
    StopPrice: Optional[float]
    Broker: Optional[str]
    StrategyType: Optional[str]
    algo: Optional[str]
    TraderName: Optional[str]
    # ── Group 2-7: Computed metrics (18) ──
    # fill_count 为该路由下 FillId 的去重计数，位于 fill 左侧
    fill_count: Optional[int]
    fill: Optional[float]
    fill_continuous: Optional[float]
    fill_close: Optional[float]
    par_rate: Optional[float]
    par_rate_continuous: Optional[float]
    par_rate_close: Optional[float]
    p_avg: Optional[float]
    p_avg_continuous: Optional[float]
    pnl_vwap: Optional[float]
    pnl_vwap_continuous: Optional[float]
    RPM: Optional[float]
    RPM_continuous: Optional[float]
    pwp_5: Optional[str | float]
    pwp_10: Optional[str | float]
    pwp_15: Optional[str | float]
    pwp_20: Optional[str | float]
    pwp_25: Optional[str | float]
    # ── 003-tca-core-benchmarks: Phase 0 核心基准 (5) ──
    p_arrival: Optional[float] = None
    p_close: Optional[float] = None
    arrival_cost_bps: Optional[float] = None
    close_cost_bps: Optional[float] = None
    opportunity_cost: Optional[float] = None
    # ── 003-tca-core-benchmarks: Phase 1 Wagner IS / 风险 / 冲击 (15) ──
    p_decision: Optional[float] = None
    delay_cost: Optional[float] = None
    trading_cost: Optional[float] = None
    wagner_is: Optional[float] = None
    wagner_is_bps: Optional[float] = None
    cost_stddev: Optional[float] = None
    cost_p95: Optional[float] = None
    cost_cvar: Optional[float] = None
    order_duration_sec: Optional[float] = None
    exec_rate_shares_per_min: Optional[float] = None
    temp_impact_5min_bps: Optional[float] = None
    temp_impact_10min_bps: Optional[float] = None
    temp_impact_30min_bps: Optional[float] = None
    perm_impact_bps: Optional[float] = None
    recovery_truncated: Optional[int] = None
    # 附加时序数据（非数据库列，供前端图表使用）
    time_series: list[dict] = field(default_factory=list)



@dataclass
class TcaRouteDetail:
    """TCA metrics for a single broker route (legacy nested detail).

    Deprecated: 新 /api/tca/analyze 返回扁平 TcaRouteSummary，本类型保留仅用于
    兼容旧归档代码与历史序列化数据。
    """
    order_id: str
    route_id: str
    order_as_of_date: str
    broker: Optional[str]
    side: Optional[str]
    start_time: Optional[str]          # Local exchange HH:MM:SS
    end_time: Optional[str]            # Local exchange HH:MM:SS
    fill_pct: Optional[float]          # 0-100
    exec_price: Optional[float]        # cum_fill_vwap (execution VWAP)
    interval_vwap: Optional[float]     # cum_vwap (market VWAP = benchmark)
    tracking_error_bps: Optional[float]
    volume_pct_interval: Optional[float]  # % of interval traded volume
    time_series: list[dict] = field(default_factory=list)


@dataclass
class TcaOrderSummary:
    """TCA summary for a single order (may contain multiple routes).

    Deprecated: 新 /api/tca/analyze 返回扁平路由列表 (TcaRouteSummary)，本类型保留仅
    用于兼容旧归档代码与历史序列化数据。
    """
    order_id: str
    order_as_of_date: str
    equ_ticker: Optional[str]
    side: Optional[str]
    algo: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    fill_pct: Optional[float]
    exec_price: Optional[float]
    interval_vwap: Optional[float]
    tracking_error_bps: Optional[float]
    volume_pct_interval: Optional[float]
    volume_pct_adv5: Optional[float]
    volume_pct_adv20: Optional[float]
    daily_volatility: Optional[float]
    intraday_volatility: Optional[float]
    price_movement_pct: Optional[float]
    data_quality_warning: bool = False
    routes: list[TcaRouteDetail] = field(default_factory=list)


@dataclass
class TcaOrderAggregate:
    """Order 级 TCA 汇总（由 route 值按聚合策略合并，003-tca-core-benchmarks）。

    聚合规则（详见 specs/003-tca-core-benchmarks/plan.md §3.2）:
    - 货币成本 (delay/trading/opportunity/wagner_is): SUM
    - 价格基准 (p_arrival/p_decision/p_close): 最早 route 取值
    - bps 绩效 (arrival/close/temp/perm_impact): 成交额加权平均
    - 完成率 (fill): Σfill / Σroute_shares
    - 风险 (cost_stddev/p95/cvar): 各 route 独立，order 取 max（保守）
    - 时点 (order_duration_sec): min(route_as_of) → max(last_fill)
    - 执行速率: Σfill / (duration/60)
    """
    OrderId: str
    order_as_of_date: str
    equ_ticker: Optional[str]
    Exchange: Optional[str]
    Side: Optional[str]
    Broker: Optional[str]
    algo: Optional[str]
    TraderName: Optional[str]
    route_count: int
    fill_count: Optional[int] = None
    # 货币成本（SUM）
    delay_cost: Optional[float] = None
    trading_cost: Optional[float] = None
    opportunity_cost: Optional[float] = None
    wagner_is: Optional[float] = None
    # 价格基准（最早 route）
    p_arrival: Optional[float] = None
    p_decision: Optional[float] = None
    p_close: Optional[float] = None
    # bps 绩效（成交额加权）
    arrival_cost_bps: Optional[float] = None
    close_cost_bps: Optional[float] = None
    wagner_is_bps: Optional[float] = None
    temp_impact_5min_bps: Optional[float] = None
    temp_impact_10min_bps: Optional[float] = None
    temp_impact_30min_bps: Optional[float] = None
    perm_impact_bps: Optional[float] = None
    # 完成率 / 参与率
    fill: Optional[float] = None
    route_shares: Optional[float] = None
    par_rate: Optional[float] = None
    # 风险（order 取 max，保守）
    cost_stddev: Optional[float] = None
    cost_p95: Optional[float] = None
    cost_cvar: Optional[float] = None
    # 时点 / 速率
    order_duration_sec: Optional[float] = None
    exec_rate_shares_per_min: Optional[float] = None
    # 附加
    recovery_truncated: Optional[int] = None


@dataclass
class TcaReport:
    """Full TCA report for a set of filtered orders.

    orders 字段现在为路由级扁平列表 (TcaRouteSummary)，每个元素对应一条
    独立路由；旧的订单嵌套结构 (TcaOrderSummary) 已弃用。
    """
    filters: dict
    total_orders: int
    offset: int
    limit: int
    orders: list[TcaRouteSummary]
    generated_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )
    data_source_warning: Optional[str] = None



@dataclass
class ScorecardFilters:
    """Filter specification for a broker/strategy scorecard query."""
    cohort: str = "broker_strategy"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    broker: Optional[str] = None
    algo: Optional[str] = None
    symbol: Optional[str] = None
    order_ids: Optional[list[str]] = None
    min_sample_size: int = 10
    max_orders: int = 2000


@dataclass
class ScorecardCohortMetrics:
    """Aggregated TCA metrics for a single cohort."""
    cohort_key: str
    cohort_label: str
    sample_size: int
    order_count: int
    avg_tracking_error_bps: Optional[float]
    median_tracking_error_bps: Optional[float]
    p95_tracking_error_bps: Optional[float]
    stddev_tracking_error_bps: Optional[float]
    avg_fill_pct: Optional[float]
    avg_volume_pct_interval: Optional[float]
    avg_volume_pct_adv20: Optional[float]
    avg_daily_volatility: Optional[float]
    avg_intraday_volatility: Optional[float]
    avg_price_movement_pct: Optional[float]
    data_quality_ratio: float = 0.0
    sample_size_warning: bool = False
    anomaly_flags: list[str] = field(default_factory=list)


@dataclass
class ScorecardReport:
    """Full scorecard output for a cohort dimension."""
    filters: dict
    cohort: str
    min_sample_size: int
    total_orders_considered: int
    total_orders_capped: bool = False
    cohorts: list[ScorecardCohortMetrics] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    data_source_warning: Optional[str] = None

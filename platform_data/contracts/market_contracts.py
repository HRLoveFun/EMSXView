"""Market-view data contracts — pure dataclasses with no business logic.

Ownership: CostView market-data pipeline publishes these contracts.
Consumers: MarketView, ExecutionView (handoff).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarketAlert:
    code: str
    category: str  # "liquidity" | "volatility"
    severity: str  # "normal" | "warning" | "critical"
    message: str


@dataclass(frozen=True)
class MarketStockPool:
    pool_id: str
    label: str
    description: str
    default_sort_by: str = "total_volume"
    default_sort_direction: str = "desc"


@dataclass(frozen=True)
class MarketSnapshotFilters:
    min_adv_20d: float | None = None
    min_total_volume: float | None = None
    min_daily_volatility: float | None = None
    min_intraday_volatility: float | None = None
    liquidity_alert: str = "all"
    volatility_alert: str = "all"


@dataclass(frozen=True)
class MarketSnapshotSort:
    field: str = "total_volume"
    direction: str = "desc"


@dataclass(frozen=True)
class MarketDailySnapshotRow:
    equ_ticker: str
    trade_date: str
    daily_close: float | None
    daily_volatility: float | None
    intraday_volatility: float | None
    total_volume: float | None
    adv_5d: float | None
    adv_20d: float | None
    volume_vs_adv20_pct: float | None = None
    liquidity_alert: str = "none"
    volatility_alert: str = "none"
    alert_count: int = 0
    alerts: list[MarketAlert] = field(default_factory=list)


@dataclass(frozen=True)
class MarketCandidateRow:
    equ_ticker: str
    trade_date: str
    daily_close: float | None
    total_volume: float | None
    adv_20d: float | None
    daily_volatility: float | None
    intraday_volatility: float | None
    liquidity_alert: str
    volatility_alert: str
    alerts: list[MarketAlert] = field(default_factory=list)


@dataclass(frozen=True)
class MarketCandidatePayload:
    source: str
    handoff_target: str
    trade_date: str | None
    pool_id: str
    pool_label: str | None
    filters: MarketSnapshotFilters
    sort: MarketSnapshotSort
    row_count: int
    candidates: list[MarketCandidateRow]


@dataclass(frozen=True)
class MarketSnapshot:
    trade_date: str | None
    row_count: int
    available_pools: list[MarketStockPool]
    active_pool_id: str
    filters: MarketSnapshotFilters
    sort: MarketSnapshotSort
    rows: list[MarketDailySnapshotRow]
    candidate_payload: MarketCandidatePayload


# ── 057 DL-10：日度基线契约（个股 60 日稳健分布，替代全局常数阈值） ──────────

# 契约版本：口径变更或 DL-09 快照源切换时升版
BASELINE_SCHEMA_VERSION = "market-baseline-v1"

# 基线窗口（交易日）；稳健统计最少天数（不足则回落并披露 n_days）
BASELINE_WINDOW_DAYS = 60
BASELINE_MIN_DAYS = 20


@dataclass(frozen=True)
class MarketBaseline:
    """逐票日度基线（父计划 §4.1 A 层产出，MarketStateSnapshot 的日度部分）。

    全部特征为个股自身 60 日分布的稳健口径；None = 数据不足或该特征不可得
    （消费方据此回落，不静默填 0）。量纲：vol_percentile 为百分比空间
    （daily_volatility 口径），intraday_vol_percentile 已由小数对齐为百分比。
    """

    equ_ticker: str
    as_of: str  # 基线数据截止日（最近交易日 YYYYMMDD）
    log_volume_z: float | None
    vol_percentile: float | None
    intraday_vol_percentile: float | None
    overnight_gap_sigma: float | None
    auction_open_pct: float | None
    auction_close_pct: float | None
    adv5_adv60_ratio: float | None
    spread_proxy_bps: float | None
    n_days: int
    excluded_dates: tuple[str, ...] = ()
    schema_version: str = BASELINE_SCHEMA_VERSION


# ── 057 DL-11：事件与市场级状态契约 ──────────────────────────────────────────

# 契约版本：口径变更或数据源切换时升版
REGIME_SCHEMA_VERSION = "market-regime-v1"


@dataclass(frozen=True)
class EventFlag:
    """单个事件标记（宏观事件 / 财报除息 / 半日市）。

    source：macro-calendar（regime.db 宏观日历）/ emsx-export（EMSX 导出字段，
    填充率未经真实导出验证——尽力而为维度）/ half-day-table（DL-03 静态表）。
    evidence：命中值或描述（如财报时间、半日市收盘时刻）。
    """

    code: str
    severity: str
    window_days: int
    source: str
    evidence: str | None = None


@dataclass(frozen=True)
class MarketRegimeState:
    """市场级日级状态（父计划 §4.1 D 层日级部分；盘中截面叠加属 DL-15）。

    liq/vol/trend 为管道 S8 regime 口径（regime.db，带 config_version 审计）；
    macro_events 为当日事件窗口内的宏观事件；未知市场/无数据由适配器返回
    None（消费方降级可见，不静默填常态）。
    """

    market_code: str
    as_of: str
    liq_regime: str | None
    vol_regime: str | None
    trend_regime: str | None
    macro_events: tuple[EventFlag, ...] = ()
    config_version: str | None = None
    schema_version: str = REGIME_SCHEMA_VERSION


# ── 057 DL-13：预期成本模型契约（评估标准化分母 + 盘前算账；K3 边界内） ──────

# 模型版本：与 CostView/src/evaluation/expected_cost.py::COST_MODEL_VERSION
# 同名互锁（契约测试断言两侧一致）；口径变更时两侧同步升版
COST_MODEL_VERSION = "cost-model-v1"


@dataclass(frozen=True)
class OrderDifficulty:
    """逐单执行难度（父计划 §4.1 B 层产出）。

    expected_cost_bps / timing_risk_bps：模型域内值；域外（in_domain=False）
    或数据不足时为 None——消费方据此回落，不静默填 0。
    用途限定：评估标准化（z 分母）与盘前单内部展示；不对外作事前预测（K3）。
    """

    expected_cost_bps: float | None
    timing_risk_bps: float | None
    required_duration_min: float | None
    close_capacity_pct: float | None
    model_version: str
    in_domain: bool
    notes: str = ""

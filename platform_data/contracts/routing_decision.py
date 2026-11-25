"""路由决策日志契约（057 DL-21/075）——纯数据，无 IO。

决策日志是 057 闭环的脊柱：每笔路由决策的候选集、参数摘要、可读理由与
四个版本号（注册表/约束/参数/决策 schema）不可变记录，供 DL-22 影子运行
对照、DL-23/24 得分快照与 lift 回检归因。

**影子方式**：本契约只描述「引擎会怎么决策」，记录不改变既有路由行为
（D-3 默认人工确认；接管评估留 DL-22/2c）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 决策 schema 版本：字段结构变更时升版（v2 = 057 DL-22/214 影子运行字段）
DECISION_SCHEMA_VERSION = "routing-decision-v2"

# 约束矩阵版本（071/072/073 定稿口径；矩阵条目变更时升版）
CONSTRAINT_MATRIX_VERSION = "constraint-matrix-v1"

# 模式：SHADOW = 影子记录（不接管）；ASSIST = 建议模式（2c 启用）
MODE_SHADOW = "SHADOW"
MODE_ASSIST = "ASSIST"

# 决策来源（DL-22/214）：人工 / 计划 / 引擎；无匹配计划时的引擎默认记录
SOURCE_MANUAL = "MANUAL"
SOURCE_PLAN = "PLAN"
SOURCE_ENGINE = "ENGINE"
SOURCE_ENGINE_DEFAULT = "ENGINE_DEFAULT"
DECISION_SOURCES: tuple[str, ...] = (
    SOURCE_MANUAL, SOURCE_PLAN, SOURCE_ENGINE, SOURCE_ENGINE_DEFAULT,
)

# 改写原因（实际 vs 建议的事后归类；不臆造交易员主观原因）
REWRITE_BROKER_CHANGED = "BROKER_CHANGED"
REWRITE_QUANTITY_CHANGED = "QUANTITY_CHANGED"
REWRITE_PARAMS_CHANGED = "PARAMS_CHANGED"
REWRITE_EXTRA_ROUTE = "EXTRA_ROUTE"
REWRITE_UNCLASSIFIED = "UNCLASSIFIED"
REWRITE_REASONS: tuple[str, ...] = (
    REWRITE_BROKER_CHANGED, REWRITE_QUANTITY_CHANGED, REWRITE_PARAMS_CHANGED,
    REWRITE_EXTRA_ROUTE, REWRITE_UNCLASSIFIED,
)


@dataclass(frozen=True)
class DecisionCandidate:
    """单个候选（一笔提案）的决策上下文。"""

    broker: str
    quantity: int
    participation_pct: float | None = None
    strategy_params: dict = field(default_factory=dict)
    rationale: str = ""
    # v2（DL-22/214）：决策时点报价价差 / 预期成本（如可得；缺失为 None）
    quote_spread_bps: float | None = None
    estimated_cost_bps: float | None = None


@dataclass(frozen=True)
class RoutingDecision:
    """一笔订单的路由决策记录（不可变；versions 供事后归因）。

    versions 固定四键：registry（策略注册表版本）、constraints（约束矩阵
    版本）、params（参数模板版本）、decision（本 schema 版本）。
    """

    decision_id: str
    trace_id: str
    order_id: str
    ticker: str
    side: str
    as_of: str
    plan_id: int | None
    split_type: str
    mode: str
    candidates: tuple[DecisionCandidate, ...]
    versions: dict = field(default_factory=dict)
    rationale: str = ""
    schema_version: str = DECISION_SCHEMA_VERSION
    # ── v2（DL-22/214）：影子运行上下文（全部可选，v1 记录读取兼容） ──
    #: 订单意图（可选；来自 PM Note/导出，缺失为空）
    intent: str = ""
    intent_source: str = ""
    #: 决策来源 MANUAL/PLAN/ENGINE/ENGINE_DEFAULT
    source: str = SOURCE_ENGINE
    #: 决策时点报价价差（bps；不可得为 None）
    quote_spread_bps: float | None = None
    #: 决策时点市场状态快照（可序列化 dict）
    market_state: dict = field(default_factory=dict)
    #: 逐提案约束检查结果（[{code, severity, message}]）
    constraint_violations: tuple[dict, ...] = ()
    #: 交易员实际路由（事后从路由订阅关联；[{route_id, broker, quantity, ...}]）
    actual_routes: tuple[dict, ...] = ()
    #: 改写原因（REWRITE_REASONS 之一；无实际路由时为空）
    rewrite_reason: str = ""
    #: 实际路由回填时间（ISO；仅 actual_routes/rewrite_reason 允许后更新）
    updated_at: str = ""

    def candidate_count(self) -> int:
        return len(self.candidates)

    def total_quantity(self) -> int:
        return sum(int(c.quantity) for c in self.candidates)

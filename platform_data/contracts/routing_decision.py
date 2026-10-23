"""路由决策日志契约（057 DL-21/075）——纯数据，无 IO。

决策日志是 057 闭环的脊柱：每笔路由决策的候选集、参数摘要、可读理由与
四个版本号（注册表/约束/参数/决策 schema）不可变记录，供 DL-22 影子运行
对照、DL-23/24 得分快照与 lift 回检归因。

**影子方式**：本契约只描述「引擎会怎么决策」，记录不改变既有路由行为
（D-3 默认人工确认；接管评估留 DL-22/2c）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 决策 schema 版本：字段结构变更时升版
DECISION_SCHEMA_VERSION = "routing-decision-v1"

# 约束矩阵版本（071/072/073 定稿口径；矩阵条目变更时升版）
CONSTRAINT_MATRIX_VERSION = "constraint-matrix-v1"

# 模式：SHADOW = 影子记录（不接管）；ASSIST = 建议模式（2c 启用）
MODE_SHADOW = "SHADOW"
MODE_ASSIST = "ASSIST"


@dataclass(frozen=True)
class DecisionCandidate:
    """单个候选（一笔提案）的决策上下文。"""

    broker: str
    quantity: int
    participation_pct: float | None = None
    strategy_params: dict = field(default_factory=dict)
    rationale: str = ""


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

    def candidate_count(self) -> int:
        return len(self.candidates)

    def total_quantity(self) -> int:
        return sum(int(c.quantity) for c in self.candidates)

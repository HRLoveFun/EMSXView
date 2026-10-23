"""路由决策日志服务（057 DL-21/075，影子方式）。

- `build_shadow_decision`：从 order/plan/proposal dict 组装不可变决策记录（纯函数）；
- `record_decision`：写运营库；**任何失败返回 False + 日志，绝不阻断提案**；
- `load_decisions`：只读查询（order_id 可选）。

影子语义：记录不改变既有路由行为（D-3）；开关 `EMSXVIEW_DECISION_LOG_ENABLED`
默认关闭（G2），开启后每次 `generate_proposals` 旁路写入一条决策。
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from platform_data.contracts import (
    CONSTRAINT_MATRIX_VERSION,
    DECISION_SCHEMA_VERSION,
    MODE_SHADOW,
    PARAM_TEMPLATE_VERSION,
    REGISTRY_VERSION,
    DecisionCandidate,
    RoutingDecision,
)

logger = logging.getLogger(__name__)


def decision_log_enabled() -> bool:
    """影子决策日志开关（默认关闭；EMSXVIEW_DECISION_LOG_ENABLED=true 开启）。"""
    return os.getenv("EMSXVIEW_DECISION_LOG_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def build_shadow_decision(
    order: Any,
    plan: Any,
    proposals: list[dict],
    *,
    trace_id: str | None = None,
) -> RoutingDecision:
    """组装影子决策记录（纯函数；proposals 为 route_engine 的提案 dict）。"""
    candidates = tuple(
        DecisionCandidate(
            broker=str(props.get("broker") or ""),
            quantity=int(props.get("quantity") or 0),
            participation_pct=(
                float(plan.participation_rate) if getattr(plan, "participation_rate", None) else None
            ),
            strategy_params=dict(props.get("strategy_params") or {}),
            rationale=f"slice_index={props.get('slice_index')}",
        )
        for props in proposals
    )
    return RoutingDecision(
        decision_id=uuid.uuid4().hex,
        trace_id=trace_id or uuid.uuid4().hex,
        order_id=str(getattr(order, "id", "") or ""),
        ticker=str(getattr(order, "symbol", "") or ""),
        side=str(getattr(order, "side", "") or ""),
        as_of=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        plan_id=getattr(plan, "id", None),
        split_type=str(getattr(plan, "split_type", "") or ""),
        mode=MODE_SHADOW,
        candidates=candidates,
        versions={
            "registry": REGISTRY_VERSION,
            "constraints": CONSTRAINT_MATRIX_VERSION,
            "params": PARAM_TEMPLATE_VERSION,
            "decision": DECISION_SCHEMA_VERSION,
        },
        rationale=f"shadow split_type={getattr(plan, 'split_type', '')} n={len(candidates)}",
    )


async def record_decision(decision: RoutingDecision) -> bool:
    """写入决策记录；失败返回 False（影子语义：绝不阻断提案）。"""
    try:
        from db import get_db_session
        from models.execution_state import RoutingDecisionRecord

        payload = {
            "order_id": decision.order_id,
            "ticker": decision.ticker,
            "side": decision.side,
            "plan_id": decision.plan_id,
            "split_type": decision.split_type,
            "mode": decision.mode,
            "candidates": [
                {
                    "broker": c.broker,
                    "quantity": c.quantity,
                    "participation_pct": c.participation_pct,
                    "strategy_params": c.strategy_params,
                    "rationale": c.rationale,
                }
                for c in decision.candidates
            ],
            "versions": dict(decision.versions),
            "rationale": decision.rationale,
            "schema_version": decision.schema_version,
        }
        async with get_db_session() as session:
            session.add(
                RoutingDecisionRecord(
                    decision_id=decision.decision_id,
                    trace_id=decision.trace_id,
                    order_id=decision.order_id,
                    as_of=decision.as_of,
                    mode=decision.mode,
                    schema_version=decision.schema_version,
                    payload=payload,
                )
            )
            await session.commit()
        return True
    except Exception:  # 影子记录失败不阻断（DB 不可用/表未建等）
        logger.warning("routing decision record not persisted (shadow mode)", exc_info=True)
        return False


async def load_decisions(order_id: str | None = None, limit: int = 50) -> list[dict]:
    """按订单查询决策记录（只读；按 as_of 倒序）。"""
    from db import get_db_session
    from models.execution_state import RoutingDecisionRecord
    from sqlalchemy import select

    limit = max(1, min(int(limit or 50), 500))
    async with get_db_session() as session:
        stmt = select(RoutingDecisionRecord).order_by(RoutingDecisionRecord.id.desc()).limit(limit)
        if order_id:
            stmt = stmt.where(RoutingDecisionRecord.order_id == order_id)
        result = await session.execute(stmt)
        return [
            {
                "decision_id": record.decision_id,
                "trace_id": record.trace_id,
                "order_id": record.order_id,
                "as_of": record.as_of,
                "mode": record.mode,
                "schema_version": record.schema_version,
                "payload": record.payload,
            }
            for record in result.scalars().all()
        ]

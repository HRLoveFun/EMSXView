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
    SOURCE_ENGINE,
    DecisionCandidate,
    RoutingDecision,
)

logger = logging.getLogger(__name__)


def decision_log_enabled() -> bool:
    """影子决策日志开关（默认关闭；EMSXVIEW_DECISION_LOG_ENABLED=true 开启）。"""
    return os.getenv("EMSXVIEW_DECISION_LOG_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def shadow_run_enabled() -> bool:
    """DL-22/214 影子运行开关（默认关闭；EMSXVIEW_SHADOW_RUN_ENABLED=true 开启）。"""
    return os.getenv("EMSXVIEW_SHADOW_RUN_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def build_shadow_decision(
    order: Any,
    plan: Any,
    proposals: list[dict],
    *,
    trace_id: str | None = None,
    context: dict | None = None,
) -> RoutingDecision:
    """组装影子决策记录（纯函数；proposals 为 route_engine 的提案 dict）。

    ``context``（214）携带影子运行上下文：intent/intent_source/source/
    quote_spread_bps/market_state/constraint_violations/actual_routes/rewrite_reason。
    """
    ctx = dict(context or {})
    candidates = tuple(
        DecisionCandidate(
            broker=str(props.get("broker") or ""),
            quantity=int(props.get("quantity") or 0),
            participation_pct=(
                float(plan.participation_rate) if getattr(plan, "participation_rate", None) else None
            ),
            strategy_params=dict(props.get("strategy_params") or {}),
            rationale=f"slice_index={props.get('slice_index')}",
            quote_spread_bps=_float_or_none(props.get("quote_spread_bps")),
            estimated_cost_bps=_float_or_none(props.get("estimated_cost_bps")),
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
        rationale=str(ctx.get("rationale") or f"shadow split_type={getattr(plan, 'split_type', '')} n={len(candidates)}"),
        intent=str(ctx.get("intent") or ""),
        intent_source=str(ctx.get("intent_source") or ""),
        source=str(ctx.get("source") or SOURCE_ENGINE),
        quote_spread_bps=_float_or_none(ctx.get("quote_spread_bps")),
        market_state=dict(ctx.get("market_state") or {}),
        constraint_violations=tuple(ctx.get("constraint_violations") or ()),
        actual_routes=tuple(ctx.get("actual_routes") or ()),
        rewrite_reason=str(ctx.get("rewrite_reason") or ""),
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
                    "quote_spread_bps": c.quote_spread_bps,
                    "estimated_cost_bps": c.estimated_cost_bps,
                }
                for c in decision.candidates
            ],
            "versions": dict(decision.versions),
            "rationale": decision.rationale,
            "schema_version": decision.schema_version,
            # v2（214）
            "intent": decision.intent,
            "intent_source": decision.intent_source,
            "source": decision.source,
            "quote_spread_bps": decision.quote_spread_bps,
            "market_state": dict(decision.market_state),
            "constraint_violations": list(decision.constraint_violations),
            "actual_routes": list(decision.actual_routes),
            "rewrite_reason": decision.rewrite_reason,
            "updated_at": decision.updated_at,
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
                    source=decision.source or SOURCE_ENGINE,
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
                "source": record.source,
                "updated_at": record.updated_at.isoformat() if record.updated_at else None,
                "payload": record.payload,
            }
            for record in result.scalars().all()
        ]


async def update_actual_routes(
    order_id: str,
    routes: list[dict],
    rewrite_reason: str = "",
) -> bool:
    """把实际路由回填到该订单最新的决策记录（214；失败返回 False）。

    仅更新 ``payload.actual_routes / payload.rewrite_reason / updated_at``，
    其余字段保持不可变（075 语义的唯一例外，见契约注释）。
    """
    if not order_id:
        return False
    try:
        from db import get_db_session
        from models.execution_state import RoutingDecisionRecord
        from sqlalchemy import select

        now = datetime.now(timezone.utc)
        async with get_db_session() as session:
            result = await session.execute(
                select(RoutingDecisionRecord)
                .where(RoutingDecisionRecord.order_id == order_id)
                .order_by(RoutingDecisionRecord.id.desc())
                .limit(1)
            )
            record = result.scalars().first()
            if record is None:
                return False
            payload = dict(record.payload or {})
            payload["actual_routes"] = list(routes)
            payload["rewrite_reason"] = rewrite_reason
            payload["updated_at"] = now.isoformat(timespec="seconds")
            record.payload = payload
            record.updated_at = now
            await session.commit()
        return True
    except Exception:  # 影子关联失败不阻断路由主流程
        logger.warning("routing decision actual-route update failed", exc_info=True)
        return False


async def link_submission(
    order_id: str,
    *,
    decision_id: str | None = None,
    rewrite_reason: str | None = None,
) -> bool:
    """提交成功后把 decision_id 与交易员改写原因回写到决策记录（219）。

    仅更新 `payload.submission_decision_id / trader_rewrite_reason /
    submitted_at` 与 `updated_at`；失败返回 False，不阻断提交。
    """
    from platform_data.contracts import REWRITE_REASONS
    from db import get_db_session
    from models.execution_state import RoutingDecisionRecord
    from sqlalchemy import select

    reason = str(rewrite_reason or "").strip().upper()
    if reason and reason not in REWRITE_REASONS:
        reason = ""  # 非法枚举忽略，保留原记录
    if not order_id and not decision_id:
        return False
    now = datetime.now(timezone.utc)
    try:
        async with get_db_session() as session:
            record = None
            if decision_id:
                result = await session.execute(
                    select(RoutingDecisionRecord).where(
                        RoutingDecisionRecord.decision_id == decision_id
                    ).limit(1)
                )
                record = result.scalars().first()
            if record is None and order_id:
                result = await session.execute(
                    select(RoutingDecisionRecord)
                    .where(RoutingDecisionRecord.order_id == order_id)
                    .order_by(RoutingDecisionRecord.id.desc())
                    .limit(1)
                )
                record = result.scalars().first()
            if record is None:
                return False
            payload = dict(record.payload or {})
            if decision_id:
                payload["submission_decision_id"] = decision_id
            if reason:
                payload["trader_rewrite_reason"] = reason
            payload["submitted_at"] = now.isoformat(timespec="seconds")
            record.payload = payload
            record.updated_at = now
            await session.commit()
        return True
    except Exception:
        logger.warning("routing decision submission link failed", exc_info=True)
        return False


def _day_bounds(start_date: str | None, end_date: str | None) -> tuple[Any, Any]:
    from datetime import datetime as _dt

    start = end = None
    if start_date:
        try:
            start = _dt.strptime(str(start_date), "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            start = None
    if end_date:
        try:
            end = _dt.strptime(str(end_date), "%Y%m%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError:
            end = None
    return start, end


async def coverage(start_date: str | None = None, end_date: str | None = None) -> dict:
    """影子运行覆盖率（214）：决策数/来源/硬违例/实际关联/无建议。"""
    from db import get_db_session
    from models.execution_state import RoutingDecisionRecord
    from sqlalchemy import select

    start, end = _day_bounds(start_date, end_date)
    stmt = select(RoutingDecisionRecord)
    if start is not None:
        stmt = stmt.where(RoutingDecisionRecord.created_at >= start)
    if end is not None:
        stmt = stmt.where(RoutingDecisionRecord.created_at <= end)
    async with get_db_session() as session:
        result = await session.execute(stmt)
        records = result.scalars().all()

    by_source: dict[str, int] = {}
    hard_violations = 0
    actual_linked = 0
    no_suggestion = 0
    for record in records:
        source = record.source or "UNKNOWN"
        by_source[source] = by_source.get(source, 0) + 1
        payload = record.payload or {}
        for violation in payload.get("constraint_violations") or []:
            if str(violation.get("severity")).upper() == "BLOCK":
                hard_violations += 1
        if payload.get("actual_routes"):
            actual_linked += 1
        if not payload.get("candidates"):
            no_suggestion += 1
    total = len(records)
    return {
        "total_decisions": total,
        "by_source": by_source,
        "hard_violations": hard_violations,
        "actual_linked": actual_linked,
        "actual_linked_pct": round(actual_linked / total * 100.0, 2) if total else None,
        "no_suggestion": no_suggestion,
        "no_suggestion_pct": round(no_suggestion / total * 100.0, 2) if total else None,
        "start_date": start_date,
        "end_date": end_date,
    }

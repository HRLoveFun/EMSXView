"""
Repository-backed service provider with in-memory fallback.

Provides a thin layer between API handlers and the persistence repositories.
When ``ENABLE_DB_PERSISTENCE`` is true **and** the database is reachable,
write-through and read-from-DB paths are used.  Otherwise everything falls
back silently to the existing in-memory Bloomberg subscription caches.

This provider is the live execution persistence boundary only. Fills-centric
execution history remains a CostView-owned contract exposed through
``platform_data.execution_history``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _iso(value) -> Optional[str]:
    """datetime → ISO 字符串（建议持久化的模型 ↔ 内存形态转换）。"""
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()

# ---------------------------------------------------------------------------
# Lazy imports — avoid ImportError when running without database libs
# ---------------------------------------------------------------------------

_DB_AVAILABLE = False
try:
    from db import get_db_session
    from repositories.orders import OrderProjectionRepository
    from repositories.routes import RouteProjectionRepository
    from repositories.audit import AuditEventRepository
    from repositories.proposal import SubOrderProposalRepository
    from repositories.parent_child_repository import ParentChildRepository
    from repositories.authorization import AuthorizationRepository
    from repositories.route_plan import RoutePlanRepository
    _DB_AVAILABLE = True
except Exception:  # pragma: no cover
    pass


class RepositoryProvider:
    """Facade that handles DB ↔ in-memory switching per call.

    * ``enabled``  – master switch (mapped to ``Settings.ENABLE_DB_PERSISTENCE``)
    * ``db_ready`` – runtime flag flipped by the lifespan probe; guards
      every DB call so that a down database never blocks normal operation.

        The provider is intentionally scoped to current-state order/route/audit
        persistence and warm-start reads. It is not the execution-history warehouse.
    """

    def __init__(self, *, enabled: bool = False):
        self.enabled: bool = enabled and _DB_AVAILABLE
        self.db_ready: bool = False  # set True after lifespan health check
        self._write_errors: int = 0
        self._max_write_errors: int = 10  # circuit breaker

    # ------------------------------------------------------------------
    #  Lifecycle helpers
    # ------------------------------------------------------------------

    def mark_db_ready(self, ready: bool = True) -> None:
        self.db_ready = ready
        if ready:
            self._write_errors = 0

    @property
    def is_active(self) -> bool:
        """Return True when DB persistence is both enabled and healthy."""
        return self.enabled and self.db_ready and self._write_errors < self._max_write_errors

    # ------------------------------------------------------------------
    #  Write-through: orders
    # ------------------------------------------------------------------

    async def persist_order(
        self,
        *,
        sequence: int,
        order_id: str,
        status: str,
        trader: str,
        payload: dict,
    ) -> bool:
        if not self.is_active:
            return False
        try:
            async with get_db_session() as session:
                repo = OrderProjectionRepository(session)
                await repo.upsert(
                    sequence=sequence,
                    order_id=order_id,
                    status=status,
                    trader=trader,
                    payload=payload,
                )
                await session.commit()
            return True
        except Exception as exc:
            self._write_errors += 1
            logger.warning("persist_order failed (err#%d): %s", self._write_errors, exc)
            return False

    # ------------------------------------------------------------------
    #  Write-through: routes
    # ------------------------------------------------------------------

    async def persist_route(
        self,
        *,
        sequence: int,
        route_id: int,
        status: str,
        broker: str,
        payload: dict,
    ) -> bool:
        if not self.is_active:
            return False
        try:
            async with get_db_session() as session:
                repo = RouteProjectionRepository(session)
                await repo.upsert(
                    sequence=sequence,
                    route_id=route_id,
                    status=status,
                    broker=broker,
                    payload=payload,
                )
                await session.commit()
            return True
        except Exception as exc:
            self._write_errors += 1
            logger.warning("persist_route failed (err#%d): %s", self._write_errors, exc)
            return False

    # ------------------------------------------------------------------
    #  Write-through: audit events
    # ------------------------------------------------------------------

    async def persist_audit_event(
        self,
        *,
        action: str,
        actor: str,
        endpoint: str,
        result: str,
        correlation_id: str | None = None,
        payload_summary: str | None = None,
    ) -> bool:
        if not self.is_active:
            return False
        try:
            async with get_db_session() as session:
                repo = AuditEventRepository(session)
                await repo.create_event(
                    action=action,
                    actor=actor,
                    endpoint=endpoint,
                    result=result,
                    correlation_id=correlation_id,
                    payload_summary=payload_summary,
                )
                await session.commit()
            return True
        except Exception as exc:
            self._write_errors += 1
            logger.warning("persist_audit_event failed (err#%d): %s", self._write_errors, exc)
            return False

    async def update_audit_result(
        self,
        *,
        correlation_id: str,
        result: str,
    ) -> bool:
        """按 correlation_id 回填审计结果 (S6/036)。

        两阶段审计的后半段：ok / fail / unknown（如请求超时）。
        """
        if not self.is_active:
            return False
        try:
            async with get_db_session() as session:
                repo = AuditEventRepository(session)
                updated = await repo.update_result_by_correlation_id(correlation_id, result)
                await session.commit()
            return updated
        except Exception as exc:
            self._write_errors += 1
            logger.warning("update_audit_result failed (err#%d): %s", self._write_errors, exc)
            return False

    # ------------------------------------------------------------------
    #  Write-through: sub-order proposals (S8/038)
    # ------------------------------------------------------------------

    async def persist_proposals_bulk(self, proposals: List[Dict[str, Any]]) -> List[int]:
        """批量写入新建议，返回数据库分配的主键（幂等键）。

        失败返回空列表——调用方回退内存 id（此时该建议重启后不可恢复，
        由调用方记录告警）。
        """
        if not self.is_active:
            return []
        try:
            async with get_db_session() as session:
                repo = SubOrderProposalRepository(session)
                ids = await repo.create_many(proposals)
                await session.commit()
            return ids
        except Exception as exc:
            self._write_errors += 1
            logger.warning("persist_proposals_bulk failed (err#%d): %s", self._write_errors, exc)
            return []

    async def update_proposal_result(
        self,
        proposal_id: int,
        *,
        status: str,
        route_id: Any = None,
        confirmed_at: Any = None,
        submitted_at: Any = None,
        updated_at: Any = None,
    ) -> bool:
        """按主键回写建议状态迁移（确认/拒绝）。"""
        if not self.is_active:
            return False
        try:
            async with get_db_session() as session:
                repo = SubOrderProposalRepository(session)
                updated = await repo.update_result(
                    proposal_id,
                    status=status,
                    route_id=route_id,
                    confirmed_at=confirmed_at,
                    submitted_at=submitted_at,
                    updated_at=updated_at,
                )
                await session.commit()
            return updated
        except Exception as exc:
            self._write_errors += 1
            logger.warning("update_proposal_result failed (err#%d): %s", self._write_errors, exc)
            return False

    def parent_child_available(self) -> bool:
        """父子单持久化是否可用 (S9/039)。"""
        return self.is_active

    # ------------------------------------------------------------------
    #  Write-through: route plans (S15/055)
    # ------------------------------------------------------------------

    async def persist_route_plan(self, plan) -> Optional[int]:
        """写入路由计划，返回数据库主键；失败返回 None（调用方回退内存 id）。"""
        if not self.is_active:
            return None
        try:
            async with get_db_session() as session:
                repo = RoutePlanRepository(session)
                created = await repo.create_from_dict(dict(plan))
                await session.commit()
            return created.id
        except Exception as exc:
            self._write_errors += 1
            logger.warning("persist_route_plan failed (err#%d): %s", self._write_errors, exc)
            return None

    async def update_route_plan_row(self, plan_id: int, values: Dict[str, Any]) -> bool:
        """按主键回写路由计划字段（write-through）。"""
        if not self.is_active:
            return False
        try:
            async with get_db_session() as session:
                repo = RoutePlanRepository(session)
                updated = await repo.update(plan_id, values)
                await session.commit()
            return updated
        except Exception as exc:
            self._write_errors += 1
            logger.warning("update_route_plan_row failed (err#%d): %s", self._write_errors, exc)
            return False

    async def delete_route_plan_row(self, plan_id: int) -> bool:
        if not self.is_active:
            return False
        try:
            async with get_db_session() as session:
                repo = RoutePlanRepository(session)
                deleted = await repo.delete(plan_id)
                await session.commit()
            return deleted
        except Exception as exc:
            self._write_errors += 1
            logger.warning("delete_route_plan_row failed (err#%d): %s", self._write_errors, exc)
            return False

    async def load_route_plans(self, limit: int = 500) -> List[Dict[str, Any]]:
        """启动恢复：读取路由计划（模型 → 内存 dict 形态）。"""
        if not self.is_active:
            return []
        try:
            async with get_db_session() as session:
                repo = RoutePlanRepository(session)
                rows = await repo.list_all(limit)
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "match_market": r.match_market,
                    "match_symbol": r.match_symbol,
                    "match_side": r.match_side,
                    "match_portfolio": r.match_portfolio,
                    "match_trader": r.match_trader,
                    "match_exchange": r.match_exchange,
                    "match_currency": r.match_currency,
                    "activation_mode": r.activation_mode,
                    "submission_mode": r.submission_mode,
                    "split_type": r.split_type,
                    "schedule_type": r.schedule_type,
                    "num_slices": r.num_slices,
                    "default_start_offset_min": r.default_start_offset_min,
                    "default_end_time_local": r.default_end_time_local,
                    "participation_rate": r.participation_rate,
                    "default_broker": r.default_broker,
                    "default_order_type": r.default_order_type,
                    "default_tif": r.default_tif,
                    "default_strategy_params": r.default_strategy_params,
                    "enabled": r.enabled,
                    "priority": r.priority,
                    "created_at": _iso(r.created_at) or "",
                    "updated_at": _iso(r.updated_at) or "",
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("load_route_plans failed, falling back to empty: %s", exc)
            return []

    # ------------------------------------------------------------------
    #  Write-through: PM authorization intents (S12/042)
    # ------------------------------------------------------------------

    async def create_authorization(self, intent) -> Optional[int]:
        """写入 PM 授权意图，返回数据库主键；失败返回 None。"""
        if not self.is_active:
            return None
        try:
            async with get_db_session() as session:
                repo = AuthorizationRepository(session)
                created = await repo.create(intent)
                await session.commit()
            return created.id
        except Exception as exc:
            self._write_errors += 1
            logger.warning("create_authorization failed (err#%d): %s", self._write_errors, exc)
            return None

    async def load_authorizations(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """读取授权意图（模型 → 内存 dict 形态）。"""
        if not self.is_active:
            return []
        try:
            async with get_db_session() as session:
                repo = AuthorizationRepository(session)
                rows = await repo.list_active() if active_only else await repo.list_all()
            return [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "side": r.side,
                    "portfolio": r.portfolio,
                    "target_quantity": r.target_quantity,
                    "status": r.status,
                    "created_by": r.created_by,
                    "note": r.note,
                    "created_at": _iso(r.created_at) or "",
                    "updated_at": _iso(r.updated_at) or "",
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("load_authorizations failed, falling back to empty: %s", exc)
            return []

    async def run_parent_child_op(self, op_name: str, *args, **kwargs):
        """在独立会话中执行 ParentChildRepository 方法 (S9/039)。

        每次调用一个事务；DB 不可用时返回 None（调用方回退内存模式）。
        """
        if not self.is_active:
            return None
        try:
            async with get_db_session() as session:
                repo = ParentChildRepository(session)
                result = await getattr(repo, op_name)(*args, **kwargs)
                await session.commit()
            return result
        except Exception as exc:
            self._write_errors += 1
            logger.warning("parent_child op %s failed (err#%d): %s", op_name, self._write_errors, exc)
            return None

    async def load_proposals(self, limit: int = 2000) -> List[Dict[str, Any]]:
        """启动恢复：读取建议（模型 → 内存 dict 形态），供内存缓存重建。"""
        if not self.is_active:
            return []
        try:
            async with get_db_session() as session:
                repo = SubOrderProposalRepository(session)
                rows = await repo.load_all(limit)
            return [
                {
                    "id": r.id,
                    "route_plan_id": r.route_plan_id,
                    "parent_order_id": r.parent_order_id,
                    "route_id": r.route_id,
                    "broker": r.broker,
                    "quantity": r.quantity,
                    "order_type": r.order_type,
                    "limit_price": r.limit_price,
                    "tif": r.tif,
                    "strategy_params": r.strategy_params,
                    "slice_index": r.slice_index,
                    "scheduled_start": _iso(r.scheduled_start),
                    "scheduled_end": _iso(r.scheduled_end),
                    "parent_symbol": r.parent_symbol,
                    "parent_side": r.parent_side,
                    "parent_trader": r.parent_trader,
                    "parent_portfolio": r.parent_portfolio,
                    "status": r.status,
                    "confirmed_at": _iso(r.confirmed_at),
                    "submitted_at": _iso(r.submitted_at),
                    "created_at": _iso(r.created_at) or "",
                    "updated_at": _iso(r.updated_at) or "",
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("load_proposals from DB failed, falling back to empty: %s", exc)
            return []

    # ------------------------------------------------------------------
    #  Read path: warm-start order cache from DB
    # ------------------------------------------------------------------

    async def load_orders(self, limit: int = 5000) -> List[Dict[str, Any]]:
        """Return order payloads from DB (newest first).

        Falls back to an empty list on any error so callers can safely
        merge the result with the live subscription cache.
        """
        if not self.is_active:
            return []
        try:
            async with get_db_session() as session:
                # Fetch all statuses — caller decides how to merge
                from sqlalchemy import select
                from models.execution_state import OrderProjection
                stmt = (
                    select(OrderProjection)
                    .order_by(OrderProjection.sequence.desc())
                    .limit(limit)
                )
                rows = await session.execute(stmt)
                return [r.payload for r in rows.scalars().all() if r.payload]
        except Exception as exc:
            logger.warning("load_orders from DB failed, falling back to empty: %s", exc)
            return []

    async def load_routes(self, limit: int = 10000) -> List[Dict[str, Any]]:
        """Return route payloads from DB (newest first)."""
        if not self.is_active:
            return []
        try:
            async with get_db_session() as session:
                from sqlalchemy import select
                from models.execution_state import RouteProjection
                stmt = (
                    select(RouteProjection)
                    .order_by(RouteProjection.sequence.desc())
                    .limit(limit)
                )
                rows = await session.execute(stmt)
                return [r.payload for r in rows.scalars().all() if r.payload]
        except Exception as exc:
            logger.warning("load_routes from DB failed, falling back to empty: %s", exc)
            return []


    async def load_audit_events(
        self,
        limit: int = 5000,
        *,
        action: str | None = None,
        correlation_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Return request journal rows as a secondary execution-history seed."""
        if not self.is_active:
            return []
        try:
            async with get_db_session() as session:
                from sqlalchemy import select
                from models.execution_state import AuditEvent

                stmt = select(AuditEvent)
                if action:
                    stmt = stmt.where(AuditEvent.action == action)
                if correlation_id:
                    stmt = stmt.where(AuditEvent.correlation_id == correlation_id)
                stmt = stmt.order_by(AuditEvent.created_at.desc()).limit(limit)

                rows = await session.execute(stmt)
                events = []
                for event in rows.scalars().all():
                    events.append(
                        {
                            "action": event.action,
                            "actor": event.actor,
                            "endpoint": event.endpoint,
                            "result": event.result,
                            "correlation_id": event.correlation_id,
                            "payload_summary": event.payload_summary,
                            "created_at": event.created_at.isoformat() if event.created_at else None,
                        }
                    )
                return events
        except Exception as exc:
            logger.warning("load_audit_events from DB failed, falling back to empty: %s", exc)
            return []

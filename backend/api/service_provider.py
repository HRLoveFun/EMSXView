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
import os
import time
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
    from repositories.watermark import WatermarkRepository
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
        # 连续写失败阈值与冷却窗口（env 可覆盖）。改为「连续失败」语义：
        # 任一次写入成功即复位——原实现只在进程启动时清零，一次池耗尽
        # 就把 provider 永久锁在内存回退态，必须重启才能恢复落盘。
        self._max_write_errors: int = max(
            1, int(os.getenv("DB_WRITE_ERROR_THRESHOLD", "10"))
        )
        self._circuit_cooldown: float = max(
            1.0, float(os.getenv("DB_CIRCUIT_COOLDOWN_SECONDS", "30"))
        )
        self._circuit_opened_at: Optional[float] = None
        self._half_open_in_flight: bool = False
        self._clock = time.monotonic

    # ------------------------------------------------------------------
    #  Lifecycle helpers
    # ------------------------------------------------------------------

    def mark_db_ready(self, ready: bool = True) -> None:
        self.db_ready = ready
        if ready:
            self._reset_circuit()

    def _reset_circuit(self) -> None:
        """回到 CLOSED：清零连续失败计数并释放 half-open 探针占用。"""
        self._write_errors = 0
        self._circuit_opened_at = None
        self._half_open_in_flight = False

    @property
    def circuit_state(self) -> str:
        """熔断三态：closed / open / half_open（与网关 CircuitBreaker 同构）。

        冷却窗口到期后进入 half_open，只放行一个写探针；探针成功回 closed，
        失败重新计时。原实现（累计失败、无自动复位）不再保留。
        """
        if self._circuit_opened_at is None:
            # 兼容直接改写 _write_errors 的旧调用/测试路径
            return "open" if self._write_errors >= self._max_write_errors else "closed"
        if self._clock() - self._circuit_opened_at >= self._circuit_cooldown:
            return "half_open"
        return "open"

    def _allow_write(self) -> bool:
        """是否放行本次写：CLOSED 全放行，OPEN 全拒，HALF_OPEN 只放行一个探针。"""
        if not (self.enabled and self.db_ready):
            return False
        state = self.circuit_state
        if state == "closed":
            return True
        if state == "open":
            return False
        if self._half_open_in_flight:
            return False
        self._half_open_in_flight = True
        return True

    def _record_success(self) -> None:
        """任一写入成功即复位熔断（连续失败语义）。"""
        self._reset_circuit()

    def _record_failure(self, op: str, exc: Exception) -> None:
        """累计连续失败；达阈值打开熔断，half-open 探针失败则重新计时。

        OPEN 期间的失败（已放行的写陆续超时）不得刷新打开时刻，否则持续
        失败会让熔断永远等不到复位——与网关 CircuitBreaker 同款约束。
        """
        self._half_open_in_flight = False
        self._write_errors += 1
        if self._circuit_opened_at is None:
            if self._write_errors >= self._max_write_errors:
                self._circuit_opened_at = self._clock()
        elif self.circuit_state == "half_open":
            self._circuit_opened_at = self._clock()
        logger.warning("%s failed (err#%d): %s", op, self._write_errors, exc)

    @property
    def is_active(self) -> bool:
        """DB 持久化是否可用：enabled + ready + 非 OPEN。

        HALF_OPEN 视为可用，写方法内部再用 _allow_write 限制为单探针；
        否则调用方（subscriptions / routers）在 is_active 处的预检会把
        探针一并挡掉，熔断永不复位。
        """
        return self.enabled and self.db_ready and self.circuit_state != "open"

    # DL-02/060：熔断状态公开只读——/api/health 增报，写入失败不再静默
    # （数据不落盘但界面显示正常是 053 审计发现的风险面）

    @property
    def write_error_count(self) -> int:
        """连续写入失败次数（任一次成功或 mark_db_ready 即清零）。"""
        return self._write_errors

    @property
    def max_write_errors(self) -> int:
        """写入失败熔断阈值。"""
        return self._max_write_errors

    @property
    def circuit_open(self) -> bool:
        """写入熔断是否未闭合（OPEN 或 HALF_OPEN 待探针复位）。"""
        return self.circuit_state != "closed"

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
        if not self._allow_write():
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
            self._record_success()
            return True
        except Exception as exc:
            self._record_failure("persist_order", exc)
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
        if not self._allow_write():
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
            self._record_success()
            return True
        except Exception as exc:
            self._record_failure("persist_route", exc)
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
        if not self._allow_write():
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
            self._record_success()
            return True
        except Exception as exc:
            self._record_failure("persist_audit_event", exc)
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
        if not self._allow_write():
            return False
        try:
            async with get_db_session() as session:
                repo = AuditEventRepository(session)
                updated = await repo.update_result_by_correlation_id(correlation_id, result)
                await session.commit()
            self._record_success()
            return updated
        except Exception as exc:
            self._record_failure("update_audit_result", exc)
            return False

    # ------------------------------------------------------------------
    #  Write-through: sub-order proposals (S8/038)
    # ------------------------------------------------------------------

    async def persist_proposals_bulk(self, proposals: List[Dict[str, Any]]) -> List[int]:
        """批量写入新建议，返回数据库分配的主键（幂等键）。

        失败返回空列表——调用方回退内存 id（此时该建议重启后不可恢复，
        由调用方记录告警）。
        """
        if not self._allow_write():
            return []
        try:
            async with get_db_session() as session:
                repo = SubOrderProposalRepository(session)
                ids = await repo.create_many(proposals)
                await session.commit()
            self._record_success()
            return ids
        except Exception as exc:
            self._record_failure("persist_proposals_bulk", exc)
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
        if not self._allow_write():
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
            self._record_success()
            return updated
        except Exception as exc:
            self._record_failure("update_proposal_result", exc)
            return False

    def parent_child_available(self) -> bool:
        """父子单持久化是否可用 (S9/039)。"""
        return self.is_active

    # ------------------------------------------------------------------
    #  Watermark (S16/056) —— 交易请求序号持久化
    # ------------------------------------------------------------------

    async def upsert_watermark(self, stream_name: str, last_sequence: int) -> bool:
        """持久化序号水位（只升不降）；失败返回 False（调用方告警）。"""
        if not self._allow_write():
            return False
        try:
            async with get_db_session() as session:
                repo = WatermarkRepository(session)
                await repo.upsert(stream_name, last_sequence)
                await session.commit()
            self._record_success()
            return True
        except Exception as exc:
            self._record_failure("upsert_watermark", exc)
            return False

    async def load_watermark(self, stream_name: str) -> int:
        """读取序号水位；无记录/不可用返回 0。"""
        if not self.is_active:
            return 0
        try:
            async with get_db_session() as session:
                repo = WatermarkRepository(session)
                return await repo.get(stream_name)
        except Exception as exc:
            logger.warning("load_watermark failed: %s", exc)
            return 0

    # ------------------------------------------------------------------
    #  Write-through: route plans (S15/055)
    # ------------------------------------------------------------------

    async def persist_route_plan(self, plan) -> Optional[int]:
        """写入路由计划，返回数据库主键；失败返回 None（调用方回退内存 id）。"""
        if not self._allow_write():
            return None
        try:
            async with get_db_session() as session:
                repo = RoutePlanRepository(session)
                created = await repo.create_from_dict(dict(plan))
                await session.commit()
            self._record_success()
            return created.id
        except Exception as exc:
            self._record_failure("persist_route_plan", exc)
            return None

    async def update_route_plan_row(self, plan_id: int, values: Dict[str, Any]) -> bool:
        """按主键回写路由计划字段（write-through）。"""
        if not self._allow_write():
            return False
        try:
            async with get_db_session() as session:
                repo = RoutePlanRepository(session)
                updated = await repo.update(plan_id, values)
                await session.commit()
            self._record_success()
            return updated
        except Exception as exc:
            self._record_failure("update_route_plan_row", exc)
            return False

    async def delete_route_plan_row(self, plan_id: int) -> bool:
        if not self._allow_write():
            return False
        try:
            async with get_db_session() as session:
                repo = RoutePlanRepository(session)
                deleted = await repo.delete(plan_id)
                await session.commit()
            self._record_success()
            return deleted
        except Exception as exc:
            self._record_failure("delete_route_plan_row", exc)
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
        if not self._allow_write():
            return None
        try:
            async with get_db_session() as session:
                repo = AuthorizationRepository(session)
                created = await repo.create(intent)
                await session.commit()
            self._record_success()
            return created.id
        except Exception as exc:
            self._record_failure("create_authorization", exc)
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
        if not self._allow_write():
            return None
        try:
            async with get_db_session() as session:
                repo = ParentChildRepository(session)
                result = await getattr(repo, op_name)(*args, **kwargs)
                await session.commit()
            self._record_success()
            return result
        except Exception as exc:
            self._record_failure(f"parent_child op {op_name}", exc)
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

    async def load_order_payloads_by_ids(
        self, order_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Load only the requested parent order payloads (A08).

        Authorization checks only need the parents returned by
        ``list_active_parents``; scanning ``limit=5000`` newest projections
        wastes work and can miss older parents.
        """
        ids = [str(order_id) for order_id in order_ids if order_id]
        if not self.is_active or not ids:
            return {}
        try:
            async with get_db_session() as session:
                from sqlalchemy import select
                from models.execution_state import OrderProjection

                stmt = select(OrderProjection).where(OrderProjection.order_id.in_(ids))
                rows = await session.execute(stmt)
                return {
                    str(row.order_id): row.payload
                    for row in rows.scalars().all()
                    if row.payload
                }
        except Exception as exc:
            logger.warning(
                "load_order_payloads_by_ids failed, falling back to empty: %s", exc,
            )
            return {}

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

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

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — avoid ImportError when running without database libs
# ---------------------------------------------------------------------------

_DB_AVAILABLE = False
try:
    from db import get_db_session
    from repositories.orders import OrderProjectionRepository
    from repositories.routes import RouteProjectionRepository
    from repositories.audit import AuditEventRepository
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
                repo = OrderProjectionRepository(session)
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

    async def load_order_snapshots(self, limit: int = 5000) -> List[Dict[str, Any]]:
        """Return latest order projections as a read-only history backfill seed."""
        return await self.load_orders(limit=limit)

    # ------------------------------------------------------------------
    #  Read path: warm-start route cache from DB
    # ------------------------------------------------------------------

    async def load_routes(self, limit: int = 10000) -> List[Dict[str, Any]]:
        """Return route payloads from DB (newest first)."""
        if not self.is_active:
            return []
        try:
            async with get_db_session() as session:
                repo = RouteProjectionRepository(session)
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

    async def load_route_snapshots(self, limit: int = 10000) -> List[Dict[str, Any]]:
        """Return latest route projections as a read-only history backfill seed."""
        return await self.load_routes(limit=limit)

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

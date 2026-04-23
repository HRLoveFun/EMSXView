from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.execution_state import AuditEvent


class AuditEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_event(
        self,
        *,
        action: str,
        actor: str,
        endpoint: str,
        result: str,
        correlation_id: str | None = None,
        payload_summary: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            action=action,
            actor=actor,
            endpoint=endpoint,
            result=result,
            correlation_id=correlation_id,
            payload_summary=payload_summary,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_recent(self, limit: int = 200) -> list[AuditEvent]:
        result = await self.session.execute(
            select(AuditEvent)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

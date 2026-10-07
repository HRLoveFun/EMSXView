from __future__ import annotations

from sqlalchemy import select, update
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

    async def update_result_by_correlation_id(
        self,
        correlation_id: str,
        result: str,
    ) -> bool:
        """按 correlation_id 回填操作结果 (S6/036)。

        两阶段审计的后半段：操作完成（成功/失败/结果未知）后把
        PENDING 更新为真实结果。返回是否命中事件。
        """
        stmt = (
            update(AuditEvent)
            .where(AuditEvent.correlation_id == correlation_id)
            .values(result=result)
        )
        res = await self.session.execute(stmt)
        return bool(res.rowcount)

    async def list_recent(self, limit: int = 200) -> list[AuditEvent]:
        result = await self.session.execute(
            select(AuditEvent)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

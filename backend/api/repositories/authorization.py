"""AuthorizationIntent repository (S12/042)。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.authorization import AuthorizationIntent


class AuthorizationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, intent: AuthorizationIntent) -> AuthorizationIntent:
        self.session.add(intent)
        await self.session.flush()
        return intent

    async def list_active(self, limit: int = 500) -> list[AuthorizationIntent]:
        result = await self.session.execute(
            select(AuthorizationIntent)
            .where(AuthorizationIntent.status == "ACTIVE")
            .order_by(AuthorizationIntent.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all(self, limit: int = 500) -> list[AuthorizationIntent]:
        result = await self.session.execute(
            select(AuthorizationIntent).order_by(AuthorizationIntent.id.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def get(self, intent_id: int) -> AuthorizationIntent | None:
        return await self.session.get(AuthorizationIntent, intent_id)

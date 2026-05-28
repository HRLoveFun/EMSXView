from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.execution_state import OrderProjection


class OrderProjectionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(
        self,
        *,
        sequence: int,
        order_id: str,
        status: str,
        trader: str,
        payload: dict,
    ) -> None:
        stmt = insert(OrderProjection).values(
            sequence=sequence,
            order_id=order_id,
            status=status,
            trader=trader,
            payload=payload,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[OrderProjection.sequence],
            set_={
                "order_id": order_id,
                "status": status,
                "trader": trader,
                "payload": payload,
            },
        )
        await self.session.execute(stmt)

    async def get_by_sequence(self, sequence: int) -> OrderProjection | None:
        result = await self.session.execute(
            select(OrderProjection).where(OrderProjection.sequence == sequence)
        )
        return result.scalar_one_or_none()

    async def list_by_status(self, status: str, limit: int = 200) -> list[OrderProjection]:
        result = await self.session.execute(
            select(OrderProjection)
            .where(OrderProjection.status == status)
            .order_by(OrderProjection.sequence.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

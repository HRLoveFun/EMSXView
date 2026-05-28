from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.execution_state import RouteProjection


class RouteProjectionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(
        self,
        *,
        sequence: int,
        route_id: int,
        status: str,
        broker: str,
        payload: dict,
    ) -> None:
        stmt = insert(RouteProjection).values(
            sequence=sequence,
            route_id=route_id,
            status=status,
            broker=broker,
            payload=payload,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_routes_projection_sequence_route_id",
            set_={
                "status": status,
                "broker": broker,
                "payload": payload,
            },
        )
        await self.session.execute(stmt)

    async def get_by_keys(self, sequence: int, route_id: int) -> RouteProjection | None:
        result = await self.session.execute(
            select(RouteProjection).where(
                RouteProjection.sequence == sequence,
                RouteProjection.route_id == route_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_sequence(self, sequence: int) -> list[RouteProjection]:
        result = await self.session.execute(
            select(RouteProjection)
            .where(RouteProjection.sequence == sequence)
            .order_by(RouteProjection.route_id.asc())
        )
        return list(result.scalars().all())

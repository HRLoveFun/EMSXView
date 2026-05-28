"""Repository for parent-child execution records."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.parent_child_orders import ChildSlice, ParentExecution


class ParentChildRepository:
    """Async CRUD for ParentExecution and ChildSlice rows."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # ParentExecution
    # ------------------------------------------------------------------

    async def create_parent(self, **kwargs) -> ParentExecution:
        parent = ParentExecution(**kwargs)
        self.session.add(parent)
        await self.session.flush()
        return parent

    async def get_parent(self, parent_id: int) -> ParentExecution | None:
        result = await self.session.execute(
            select(ParentExecution).where(ParentExecution.id == parent_id)
        )
        return result.scalar_one_or_none()

    async def get_parent_by_order(self, sequence: int, order_id: str) -> ParentExecution | None:
        result = await self.session.execute(
            select(ParentExecution)
            .where(ParentExecution.sequence == sequence, ParentExecution.order_id == order_id)
            .order_by(ParentExecution.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_active_parents(self, trader: str | None = None, limit: int = 200) -> list[ParentExecution]:
        stmt = (
            select(ParentExecution)
            .where(ParentExecution.status.in_(["PENDING", "ACTIVE", "PAUSED"]))
            .order_by(ParentExecution.created_at.desc())
            .limit(limit)
        )
        if trader:
            stmt = stmt.where(ParentExecution.trader == trader)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_parent_status(self, parent_id: int, status: str) -> None:
        await self.session.execute(
            update(ParentExecution)
            .where(ParentExecution.id == parent_id)
            .values(status=status)
        )

    async def update_parent_filled(self, parent_id: int, filled_quantity: int) -> None:
        await self.session.execute(
            update(ParentExecution)
            .where(ParentExecution.id == parent_id)
            .values(filled_quantity=filled_quantity)
        )

    # ------------------------------------------------------------------
    # ChildSlice
    # ------------------------------------------------------------------

    async def create_slice(self, **kwargs) -> ChildSlice:
        child = ChildSlice(**kwargs)
        self.session.add(child)
        await self.session.flush()
        return child

    async def create_slices_bulk(self, slices: list[dict]) -> list[ChildSlice]:
        objs = [ChildSlice(**s) for s in slices]
        self.session.add_all(objs)
        await self.session.flush()
        return objs

    async def get_slice(self, slice_id: int) -> ChildSlice | None:
        result = await self.session.execute(
            select(ChildSlice).where(ChildSlice.id == slice_id)
        )
        return result.scalar_one_or_none()

    async def list_slices_for_parent(self, parent_id: int) -> list[ChildSlice]:
        result = await self.session.execute(
            select(ChildSlice)
            .where(ChildSlice.parent_id == parent_id)
            .order_by(ChildSlice.slice_index)
        )
        return list(result.scalars().all())

    async def update_slice_status(self, slice_id: int, status: str, **kwargs) -> None:
        await self.session.execute(
            update(ChildSlice)
            .where(ChildSlice.id == slice_id)
            .values(status=status, **kwargs)
        )

    async def update_slice_route(self, slice_id: int, route_id: int) -> None:
        await self.session.execute(
            update(ChildSlice)
            .where(ChildSlice.id == slice_id)
            .values(route_id=route_id)
        )

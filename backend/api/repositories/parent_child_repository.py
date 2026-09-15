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

    async def get_parent(self, parent_id: int) -> ParentExecution | None:
        result = await self.session.execute(
            select(ParentExecution).where(ParentExecution.id == parent_id)
        )
        return result.scalar_one_or_none()

    async def update_parent_status(self, parent_id: int, status: str) -> None:
        await self.session.execute(
            update(ParentExecution)
            .where(ParentExecution.id == parent_id)
            .values(status=status)
        )


    # ------------------------------------------------------------------
    # ChildSlice
    # ------------------------------------------------------------------

    async def create_slices_bulk(self, slices: list[dict]) -> list[ChildSlice]:
        objs = [ChildSlice(**s) for s in slices]
        self.session.add_all(objs)
        await self.session.flush()
        return objs

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


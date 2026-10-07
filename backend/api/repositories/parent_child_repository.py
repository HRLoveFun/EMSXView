"""Repository for parent-child execution records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.parent_child_orders import (
    ChildSlice,
    ExecutionStatus,
    ParentExecution,
    SliceStatus,
)


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

    async def create_parent(self, parent: ParentExecution) -> ParentExecution:
        """写入父单并取回数据库主键 (S9/039)。"""
        self.session.add(parent)
        await self.session.flush()
        return parent

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

    async def list_active_parents(self) -> list[ParentExecution]:
        """重启恢复：ACTIVE/PAUSED 父单 (S9/039)。"""
        result = await self.session.execute(
            select(ParentExecution).where(
                ParentExecution.status.in_(
                    [ExecutionStatus.ACTIVE.value, ExecutionStatus.PAUSED.value]
                )
            )
        )
        return list(result.scalars().all())

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

    async def list_due_slices(self, now: datetime, limit: int = 100) -> list[ChildSlice]:
        """驱动循环 (S9/039)：到达提交时间的 PENDING 切片。"""
        result = await self.session.execute(
            select(ChildSlice)
            .where(
                ChildSlice.status == SliceStatus.PENDING.value,
                ChildSlice.scheduled_start.isnot(None),
                ChildSlice.scheduled_start <= now,
            )
            .order_by(ChildSlice.scheduled_start)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_slice_by_route_id(self, route_id: int) -> ChildSlice | None:
        """成交反馈 (S9/039)：按路由 id 定位切片（人工路由不命中）。"""
        result = await self.session.execute(
            select(ChildSlice).where(ChildSlice.route_id == route_id)
        )
        return result.scalar_one_or_none()

    async def update_slice_fill(self, slice_id: int, filled_quantity: int, status: str) -> None:
        """成交反馈 (S9/039)：回填切片成交量与状态。"""
        await self.session.execute(
            update(ChildSlice)
            .where(ChildSlice.id == slice_id)
            .values(filled_quantity=filled_quantity, status=status)
        )


"""SubOrderProposal repository — 建议持久化 (S8/038).

提供子订单建议的 write-through 持久化与启动恢复读取。
幂等键 = SubOrderProposal 数据库主键：确认状态机（PENDING_CONFIRM →
CONFIRMING → SUBMITTED）经此层回写，进程重启后状态可恢复、
重复确认可识别。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.route_plan import SubOrderProposal


def _to_datetime(value):
    """内存 dict 中的 ISO 字符串 → datetime（失败返回 None）。"""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _to_iso(value):
    """datetime → ISO 字符串（内存 dict 形态）。"""
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()


class SubOrderProposalRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_many(self, proposals: list[dict]) -> list[int]:
        """批量写入新建议，返回数据库分配的主键（幂等键）。"""
        ids: list[int] = []
        for p in proposals:
            event = SubOrderProposal(
                route_plan_id=p.get("route_plan_id"),
                parent_order_id=p.get("parent_order_id", ""),
                route_id=p.get("route_id"),
                broker=p.get("broker", ""),
                quantity=p.get("quantity", 0),
                order_type=p.get("order_type"),
                limit_price=p.get("limit_price"),
                tif=p.get("tif"),
                strategy_params=p.get("strategy_params"),
                slice_index=p.get("slice_index"),
                scheduled_start=_to_datetime(p.get("scheduled_start")),
                scheduled_end=_to_datetime(p.get("scheduled_end")),
                parent_symbol=p.get("parent_symbol"),
                parent_side=p.get("parent_side"),
                parent_trader=p.get("parent_trader"),
                parent_portfolio=p.get("parent_portfolio"),
                status=p.get("status", "PENDING_CONFIRM"),
            )
            self.session.add(event)
            await self.session.flush()
            ids.append(event.id)
        return ids

    async def update_result(
        self,
        proposal_id: int,
        *,
        status: str,
        route_id: Optional[int] = None,
        confirmed_at=None,
        submitted_at=None,
        updated_at=None,
    ) -> bool:
        """按主键回写确认状态机的状态迁移。返回是否命中。"""
        event = await self.session.get(SubOrderProposal, proposal_id)
        if event is None:
            return False
        event.status = status
        if route_id is not None:
            event.route_id = route_id
        event.confirmed_at = _to_datetime(confirmed_at)
        event.submitted_at = _to_datetime(submitted_at)
        event.updated_at = _to_datetime(updated_at) or datetime.now(timezone.utc)
        return True

    async def load_all(self, limit: int = 2000) -> list[SubOrderProposal]:
        result = await self.session.execute(
            select(SubOrderProposal).order_by(SubOrderProposal.id.desc()).limit(limit)
        )
        return list(result.scalars().all())

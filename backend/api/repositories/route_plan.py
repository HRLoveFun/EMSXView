"""RoutePlan repository (S15/055) —— 路由计划持久化。

S8 只持久化了建议侧；建议表的 route_plan_id 外键指向本表，
计划不落库时建议写入必然 FK 失败（第二份审计发现 4）。
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.route_plan import RoutePlan


def _to_datetime(value):
    """内存 dict 的 ISO 字符串 → datetime（DateTime 列不接受字符串）。"""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


class RoutePlanRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, plan: RoutePlan) -> RoutePlan:
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def create_from_dict(self, data: dict) -> RoutePlan:
        """内存 plan dict → 模型（ISO 时间转换；id 剔除交由自增）。"""
        data = {k: v for k, v in data.items() if k != "id"}
        data["created_at"] = _to_datetime(data.get("created_at"))
        data["updated_at"] = _to_datetime(data.get("updated_at"))
        return await self.create(RoutePlan(**data))

    async def update(self, plan_id: int, values: dict) -> bool:
        plan = await self.session.get(RoutePlan, plan_id)
        if plan is None:
            return False
        for k, v in values.items():
            if v is None or not hasattr(plan, k):
                continue
            if k in ("created_at", "updated_at"):
                v = _to_datetime(v)
            setattr(plan, k, v)
        return True

    async def delete(self, plan_id: int) -> bool:
        plan = await self.session.get(RoutePlan, plan_id)
        if plan is None:
            return False
        await self.session.delete(plan)
        return True

    async def list_all(self, limit: int = 500) -> list[RoutePlan]:
        result = await self.session.execute(
            select(RoutePlan).order_by(RoutePlan.id.desc()).limit(limit)
        )
        return list(result.scalars().all())

"""SubscriptionWatermark repository (S16/056) —— 请求序号持久化。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.execution_state import SubscriptionWatermark


class WatermarkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, stream_name: str, last_sequence: int) -> None:
        row = await self.session.get(SubscriptionWatermark, stream_name)
        if row is None:
            self.session.add(SubscriptionWatermark(
                stream_name=stream_name,
                last_sequence=last_sequence,
                last_event_time=datetime.now(timezone.utc),
            ))
        else:
            # 只升不降（与 restore_request_seq 语义一致）
            if last_sequence > row.last_sequence:
                row.last_sequence = last_sequence
            row.last_event_time = datetime.now(timezone.utc)
        await self.session.flush()

    async def get(self, stream_name: str) -> int:
        row = await self.session.get(SubscriptionWatermark, stream_name)
        return row.last_sequence if row else 0

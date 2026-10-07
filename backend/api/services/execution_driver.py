"""Execution driver (S9/039) — 父子单调度驱动循环、成交反馈、重启恢复。

补齐 029 报告指出的缺失链路：「持续驱动切片提交、接收成交反馈、重启恢复」。

设计要点：
- **repo duck-type**：与 ParentChildRepository 同接口；生产用
  ProviderParentChildRepo（经 provider 会话执行，见 service_provider），
  测试用内存替身。
- **submit_slice 注入**：切片提交 = 真实下单路径。默认 None（tick 对到期
  切片记 ERROR 不提交）——实盘接线须显式经 lifespan 注入，防止驱动循环
  意外自动下单。
- **成交反馈**：record_fill 按路由 id 定位切片回填成交量，人工路由不命中
  返回 False；父单 filled_quantity 汇总更新。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from models.parent_child_orders import ExecutionStatus, SliceStatus

logger = logging.getLogger(__name__)


class ProviderParentChildRepo:
    """把 duck-typed repo 方法调用包装为 provider 会话事务 (S9/039)。

    属性访问返回 async 包装：每次方法调用 = 独立 DB 会话 + 提交；
    DB 不可用时返回 None（调用方判断降级）。
    """

    def __init__(self, provider):
        self._provider = provider

    def __getattr__(self, name: str):
        async def _op(*args, **kwargs):
            return await self._provider.run_parent_child_op(name, *args, **kwargs)
        return _op


class ExecutionDriver:
    """切片提交驱动循环 + 成交反馈。

    repo：duck-typed（list_due_slices / get_parent / update_slice_status /
    get_slice_by_route_id / update_slice_fill / list_slices_for_parent /
    update_parent_filled）。
    submit_slice：async (parent, slice) -> route_id | None；None = 未接线。
    """

    def __init__(
        self,
        repo: Any,
        submit_slice: Optional[Callable[[Any, Any], Awaitable[Optional[int]]]] = None,
        tick_interval: float = 5.0,
    ):
        self._repo = repo
        self._submit_slice = submit_slice
        self._tick_interval = tick_interval
        self._running = False

    # ── 驱动循环 ────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """lifespan 后台任务：周期 tick 直到 stop。"""
        self._running = True
        logger.info("Execution driver started (tick=%.1fs)", self._tick_interval)
        while self._running:
            try:
                await self.tick()
            except Exception as exc:
                logger.error("Execution driver tick failed: %s: %s", type(exc).__name__, exc)
            await asyncio.sleep(self._tick_interval)
        logger.info("Execution driver stopped")

    def stop(self) -> None:
        self._running = False

    # ── 到期切片提交 ────────────────────────────────────────────────────

    async def tick(self) -> int:
        """提交到达计划时间的 PENDING 切片。返回本次提交数。"""
        now = datetime.now(timezone.utc)
        due = await self._repo.list_due_slices(now)
        if not due:
            return 0

        if self._submit_slice is None:
            # 提交函数未接线（实盘接线须显式注入）——可见化，不静默丢弃
            logger.error(
                "%d due slice(s) await submission but no submit function is "
                "configured — driver will retry; wire submit_slice to enable",
                len(due),
            )
            return 0

        submitted = 0
        for s in due:
            parent = await self._repo.get_parent(s.parent_id)
            if parent is None or getattr(parent, "status", "") != ExecutionStatus.ACTIVE.value:
                continue
            route_id = await self._submit_slice(parent, s)
            if route_id:
                await self._repo.update_slice_status(s.id, SliceStatus.SENT.value, route_id=route_id)
                submitted += 1
                logger.info(
                    "Driver submitted slice %d (parent=%d index=%d qty=%s) as route %s",
                    s.id, s.parent_id, s.slice_index, s.planned_quantity, route_id,
                )
            else:
                await self._repo.update_slice_status(s.id, SliceStatus.FAILED.value)
                logger.error("Driver failed to submit slice %d (parent=%d)", s.id, s.parent_id)
        return submitted

    # ── 成交反馈 ────────────────────────────────────────────────────────

    async def record_fill(self, route_id: int, filled_qty: int) -> bool:
        """按路由 id 回填切片成交；父单 filled_quantity 汇总更新。

        返回 False 表示该路由不属于任何切片（人工路由等）——正常情况。
        """
        s = await self._repo.get_slice_by_route_id(route_id)
        if s is None:
            return False

        planned = getattr(s, "planned_quantity", 0) or 0
        status = (
            SliceStatus.FILLED.value if filled_qty >= planned else SliceStatus.WORKING.value
        )
        await self._repo.update_slice_fill(s.id, filled_qty, status)

        children = await self._repo.list_slices_for_parent(s.parent_id)
        total = sum(getattr(c, "filled_quantity", 0) or 0 for c in children)
        await self._repo.update_parent_filled(s.parent_id, total)
        logger.info(
            "Fill recorded: route=%d slice=%d filled=%d/%s parent=%d total=%d",
            route_id, s.id, filled_qty, planned, s.parent_id, total,
        )
        return True

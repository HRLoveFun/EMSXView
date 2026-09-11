"""TCA 查询并发护栏 — 信号量限流 + 线程池卸载 + 查询超时。

解决的问题（README §5.2 已知瓶颈④）：
1. async 端点直接调用同步重查询（SQLite 全表扫描 / 时序拉取）会阻塞
   事件循环，单用户重查询即可冻结整个服务；
2. 多用户并发查询无上限，IO 争抢导致尾延迟失控。

护栏参数（环境变量可覆盖）：
  TCA_MAX_CONCURRENT_QUERIES — 并发查询信号量上限（默认 4）
  TCA_QUERY_TIMEOUT_S        — 单次查询超时秒数（默认 120，覆盖大区间时序拉取）

超时/限流语义与 analyze 端点的降级约定一致：抛 QueryTimeoutError，
由 router 映射为 HTTP 503（数据源暂时不可用），绝不静默返回空结果。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable

from starlette.concurrency import run_in_threadpool

# 并发上限（进程级，懒初始化以绑定运行中的事件循环）
_MAX_CONCURRENT_QUERIES: int = int(os.getenv("TCA_MAX_CONCURRENT_QUERIES", "4"))
# 单次查询超时（秒）
_QUERY_TIMEOUT_S: float = float(os.getenv("TCA_QUERY_TIMEOUT_S", "120"))

_semaphore: asyncio.Semaphore | None = None


class QueryTimeoutError(Exception):
    """TCA 查询超时 — router 应映射为 HTTP 503。"""


def _get_semaphore() -> asyncio.Semaphore:
    """懒初始化信号量（首次调用绑定当前事件循环）。"""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(_MAX_CONCURRENT_QUERIES)
    return _semaphore


async def run_bounded(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """在有界并发槽内于线程池执行同步查询函数。

    - 信号量限制同时在途的查询数，超出者排队等待；
    - run_in_threadpool 把同步阻塞从事件循环卸载到工作线程；
    - wait_for 强制超时，防止慢查询无限占用槽位与线程。
    """
    semaphore = _get_semaphore()
    async with semaphore:
        try:
            return await asyncio.wait_for(
                run_in_threadpool(fn, *args, **kwargs),
                timeout=_QUERY_TIMEOUT_S,
            )
        except asyncio.TimeoutError as exc:
            raise QueryTimeoutError(
                f"查询超时 (>{_QUERY_TIMEOUT_S:.0f}s)，请缩小时间范围或稍后重试"
            ) from exc

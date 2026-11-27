"""监控端点并发护栏（2026-11-27 连接池耗尽 / 健康探针误报事故回归）。

- 同 key 并发请求合并为一次重计算（cache-miss 风暴）
- 同步全量扫描放工作线程，事件循环在计算期间仍可调度
"""

from __future__ import annotations

import asyncio
import threading
import time

import CostView.api.routers.monitoring as monitoring
from CostView.src.tca_cache import CacheConfig, TcaCacheManager


def _no_redis_cache() -> TcaCacheManager:
    return TcaCacheManager(CacheConfig(enable_redis=False))


def test_report_build_coalesces_concurrent_requests(monkeypatch):
    monkeypatch.setattr(monitoring, "_cache", _no_redis_cache())
    calls: list[dict] = []

    def fake_build(params: dict) -> dict:
        calls.append(params)
        return {"kpi": {"route_count": 1}}

    monkeypatch.setattr(monitoring, "_build_report_sync", fake_build)
    params = {"start": "20261101", "end": "20261127", "probe": "coalesce"}

    async def main():
        return await asyncio.gather(
            *(monitoring._build_report_cached(dict(params)) for _ in range(4))
        )

    results = asyncio.run(main())

    assert len(calls) == 1, "并发未命中只应触发一次全量计算"
    assert all(data == {"kpi": {"route_count": 1}} for data, _ in results)
    assert [cached for _, cached in results].count(False) == 1, "只有发起方不是缓存命中"


def test_report_build_runs_off_event_loop(monkeypatch):
    """同步聚合在工作线程执行：计算未完成时事件循环仍可调度其他协程。"""
    monkeypatch.setattr(monitoring, "_cache", _no_redis_cache())
    started = threading.Event()
    released = threading.Event()

    def slow_build(params: dict) -> dict:
        started.set()
        released.wait(timeout=5)
        return {"kpi": {}}

    monkeypatch.setattr(monitoring, "_build_report_sync", slow_build)
    params = {"start": "20261101", "end": "20261127", "probe": "offloop"}

    async def main():
        task = asyncio.create_task(monitoring._build_report_cached(params))
        # 若聚合占用事件循环，本循环要等 slow_build 返回后才能推进
        while not started.is_set():
            await asyncio.sleep(0.01)
        released.set()
        return await task

    started_at = time.perf_counter()
    result = asyncio.run(main())
    elapsed = time.perf_counter() - started_at

    assert result == ({"kpi": {}}, False)
    assert elapsed < 1.5, f"事件循环被同步聚合阻塞 {elapsed:.2f}s"

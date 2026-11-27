"""SingleFlight 并发合并测试（2026-11-27 连接池耗尽事故护栏）。

同一缓存 key 并发未命中时只允许一次真实计算；失败广播给等待者且不残留，
后续调用可重新成为发起方。
"""

from __future__ import annotations

import asyncio

from CostView.src.tca_cache import SingleFlight


def test_coalesces_concurrent_calls_to_one_execution():
    sf = SingleFlight()
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return {"v": 1}

    async def main():
        return await asyncio.gather(*(sf.run("k", factory) for _ in range(5)))

    results = asyncio.run(main())

    assert calls == 1
    assert [result for result, _ in results] == [{"v": 1}] * 5
    assert [owner for _, owner in results].count(True) == 1, "只应有一个发起方"


def test_different_keys_run_independently():
    sf = SingleFlight()
    calls: list[str] = []

    def make_factory(key: str):
        async def factory():
            calls.append(key)
            await asyncio.sleep(0.01)
            return key
        return factory

    async def main():
        return await asyncio.gather(
            sf.run("a", make_factory("a")),
            sf.run("b", make_factory("b")),
        )

    results = asyncio.run(main())

    assert sorted(calls) == ["a", "b"]
    assert {result for result, _ in results} == {"a", "b"}


def test_failure_is_broadcast_to_waiters_and_not_cached():
    sf = SingleFlight()
    calls = 0

    async def bad():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        raise RuntimeError("boom")

    async def main():
        return await asyncio.gather(
            *(sf.run("k", bad) for _ in range(3)),
            return_exceptions=True,
        )

    results = asyncio.run(main())

    assert calls == 1
    assert all(isinstance(result, RuntimeError) for result in results)

    async def good():
        return "ok"

    assert asyncio.run(sf.run("k", good)) == ("ok", True), "失败后不应残留 in-flight"

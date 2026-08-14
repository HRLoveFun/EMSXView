"""H4 回归测试: handoff 内存容量防护 (2026-08-14)。

背景:
    HandoffExchangeAdapter._execution_to_cost 为无上限 dict, 配合
    无认证的 post-trade 端点可被持续写入撑爆进程内存。

校验:
    1. Execution→Cost 映射达上限时淘汰最旧条目
    2. 过期条目 (TTL) 惰性清理
"""

from __future__ import annotations

import pytest

from platform_data.adapters.handoff import (
    HandoffExchangeAdapter,
    _HANDOFF_TTL,
    _MAX_EXECUTION_TO_COST,
)


def _publish(ex: HandoffExchangeAdapter, order_id: str) -> None:
    ex.publish_execution_to_cost(
        order_id=order_id, parent_execution_id=None, broker=None,
        strategy=None, asset_class=None, urgency=None,
        route_ids=[], strategy_params=None,
    )


def test_execution_to_cost_evicts_oldest_at_capacity():
    """映射达上限时淘汰最旧条目, 总数不超过上限。"""
    ex = HandoffExchangeAdapter()
    for i in range(_MAX_EXECUTION_TO_COST + 5):
        _publish(ex, f"order-{i}")

    assert len(ex.list_execution_to_cost(limit=10_000)) <= _MAX_EXECUTION_TO_COST
    assert ex.get_execution_to_cost("order-0") is None, "最旧条目未被淘汰"
    assert ex.get_execution_to_cost(f"order-{_MAX_EXECUTION_TO_COST + 4}") is not None


def test_expired_entries_pruned_on_access():
    """过期条目在读取时被惰性清理。"""
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone

    ex = HandoffExchangeAdapter()
    _publish(ex, "fresh-order")
    _publish(ex, "stale-order")

    # 手工构造过期条目: generated_at 超过 TTL (HandoffMetadata 为 frozen dataclass)
    with ex._lock:
        for oid, handoff in ex._execution_to_cost.items():
            if handoff.order_id == "stale-order":
                stale_time = datetime.now(timezone.utc) - _HANDOFF_TTL - timedelta(hours=1)
                ex._execution_to_cost[oid] = replace(
                    handoff, metadata=replace(
                        handoff.metadata, generated_at=stale_time.isoformat()
                    )
                )

    # 读取触发清理
    assert ex.get_execution_to_cost("stale-order") is None
    assert ex.get_execution_to_cost("fresh-order") is not None

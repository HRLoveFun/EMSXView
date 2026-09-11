"""P3 整改回归测试: handoff 元数据成熟度 + newest-wins 乱序守卫。

背景:
    1. HandoffMetadata 此前无 source_maturity — MarketView（Scaffold）写入的
       handoff 与 GA 模块数据在消费端无差别展示，数据质量无信号；
    2. publish 为 blind last-write-wins — 乱序发布可用旧快照覆盖新快照。

校验:
    1. 三条通道的 metadata 均携带发布方模块成熟度
    2. Market→Execution: 乱序发布保留较新条目
    3. Execution→Cost (同一 order_id): 乱序发布保留较新条目
"""

from __future__ import annotations

from dataclasses import replace

from platform_data.adapters.handoff import HandoffExchangeAdapter
from platform_data.contracts import (
    MATURITY_GA,
    MATURITY_SCAFFOLD,
    MarketCandidatePayload,
)


def _publish(ex: HandoffExchangeAdapter, order_id: str):
    return ex.publish_execution_to_cost(
        order_id=order_id, parent_execution_id=None, broker=None,
        strategy=None, asset_class=None, urgency=None,
        route_ids=[], strategy_params=None,
    )


def test_metadata_carries_source_maturity():
    """三条 publish 通道均携带发布方模块成熟度。"""
    ex = HandoffExchangeAdapter()

    rec = ex.publish_cost_to_execution(
        cohort="broker_strategy", asset_class=None, broker="BrokerA",
        strategy="VWAP", urgency=None, sample_size=42,
        arrival_bps=None, implementation_bps=None,
        severity="normal", rationale="",
    )
    assert rec.metadata.source_maturity == MATURITY_GA

    post_trade = _publish(ex, "order-x")
    assert post_trade.metadata.source_maturity == MATURITY_GA


def test_market_to_execution_scaffold_maturity():
    """MarketView 发布方当前为 Scaffold，成熟度必须透出供消费方降信任。"""
    ex = HandoffExchangeAdapter()
    payload = MarketCandidatePayload(
        source="test", handoff_target="ExecutionView",
        trade_date=None, pool_id="p1", pool_label=None,
        filters=None, sort=None, row_count=0, candidates=[],
    )
    handoff = ex.publish_market_to_execution(payload)
    assert handoff.metadata.source_maturity == MATURITY_SCAFFOLD


def test_market_to_execution_out_of_order_keeps_newer():
    """乱序发布（incoming generated_at 更旧）时保留已存的新条目。"""
    ex = HandoffExchangeAdapter()

    def _payload(pool_id: str) -> MarketCandidatePayload:
        return MarketCandidatePayload(
            source="test", handoff_target="ExecutionView",
            trade_date=None, pool_id=pool_id, pool_label=None,
            filters=None, sort=None, row_count=0, candidates=[],
        )

    first = ex.publish_market_to_execution(_payload("pool-new"))
    # 手工把已存条目的 generated_at 推到未来，模拟"已存条目较新"
    with ex._lock:
        ex._market_to_execution = replace(
            first,
            metadata=replace(first.metadata, generated_at="2999-01-01T00:00:00+00:00"),
        )

    incoming = ex.publish_market_to_execution(_payload("pool-old"))
    stored = ex.get_market_to_execution()
    assert stored.pool_id == "pool-new", "旧快照覆盖了新快照"
    assert incoming.pool_id == "pool-new", "返回值应与实际存储一致"


def test_execution_to_cost_out_of_order_keeps_newer():
    """同一订单的乱序发布保留较新的 Execution→Cost 条目。"""
    ex = HandoffExchangeAdapter()

    _publish(ex, "order-y")
    with ex._lock:
        existing = ex._execution_to_cost["order-y"]
        ex._execution_to_cost["order-y"] = replace(
            existing,
            metadata=replace(existing.metadata, generated_at="2999-01-01T00:00:00+00:00"),
        )

    result = _publish(ex, "order-y")
    stored = ex.get_execution_to_cost("order-y")
    assert stored is not None and stored.metadata.generated_at == "2999-01-01T00:00:00+00:00"
    assert result.metadata.generated_at == "2999-01-01T00:00:00+00:00"


def test_normal_sequential_publish_still_overwrites():
    """正常时序（incoming 更新）仍以后到者为准，守卫不改变常规语义。"""
    ex = HandoffExchangeAdapter()
    _publish(ex, "order-z")
    result = _publish(ex, "order-z")
    stored = ex.get_execution_to_cost("order-z")
    assert stored is not None
    assert stored.metadata.trace_id == result.metadata.trace_id

"""Redis-backed handoff exchange adapter (cross-process).

Extracted from the formerly monolithic adapters.py (lines 1159-1471).
Implements the same interface as HandoffExchangeAdapter but uses Redis keys
so the exchange survives process restarts and works across microservice boundaries.

Keys:
  emsxview:handoff:mv-to-ev    (String — Market → Execution, single value)
  emsxview:handoff:ev-to-cv    (Hash  — Execution → Cost, by order_id)
  emsxview:handoff:cv-to-ev    (List  — Cost → Execution, capped at 200)
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from platform_data.contracts.handoff_contracts import (
    SOURCE_MODULE_MATURITY,
    BrokerStrategyRecommendation,
    ExecutionCandidateHandoff,
    ExecutionPostTradeHandoff,
    HandoffMetadata,
    _new_trace_id,
    _now_iso,
)
from platform_data.contracts.market_contracts import (
    MarketCandidatePayload,
    MarketCandidateRow,
    MarketSnapshotFilters,
    MarketSnapshotSort,
)

_log = logging.getLogger(__name__)


class RedisHandoffExchangeAdapter:
    """Redis-backed cross-module handoff exchange.

    Implements the same interface as HandoffExchangeAdapter but uses Redis keys
    so that the exchange survives process restarts and works across microservice
    boundaries.

    Keys:
      emsxview:handoff:mv-to-ev    (String — Market → Execution, single value)
      emsxview:handoff:ev-to-cv    (Hash  — Execution → Cost, by order_id)
      emsxview:handoff:cv-to-ev    (List  — Cost → Execution, capped at 200)
    """

    _MARKET_CONTRACT_VERSION = "v1"
    _EXECUTION_CONTRACT_VERSION = "v1"
    _COST_CONTRACT_VERSION = "v1"

    _KEY_MV_TO_EV = "emsxview:handoff:mv-to-ev"
    _KEY_EV_TO_CV = "emsxview:handoff:ev-to-cv"
    _KEY_CV_TO_EV = "emsxview:handoff:cv-to-ev"

    _MAX_CV_TO_EV = 200

    # 条目过期时间（秒）— 与内存后端 _HANDOFF_TTL (7 天) 对齐。
    # 此前 Redis 后端三条通道均无 TTL，条目永久存活，消费方可能读到
    # 过期结论而无任何新鲜度信号（跨模块一致性缺陷）。
    _TTL_SECONDS = 7 * 24 * 3600

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        import redis
        self._redis = redis.from_url(redis_url, decode_responses=False)

    def describe(self) -> dict[str, str]:
        return {
            "domain": "handoff-exchange",
            "owner": "platform_data",
            "storage": "Redis",
            "entrypoint": "RedisHandoffExchangeAdapter",
        }

    # — Serialization helpers —

    def _serialize(self, obj: Any) -> bytes:
        """Serialize a dataclass or dict to JSON bytes."""
        import json
        from dataclasses import asdict
        payload = asdict(obj) if hasattr(obj, '__dataclass_fields__') else obj
        return json.dumps(payload, default=str, ensure_ascii=False).encode('utf-8')

    def _deserialize_handoff(self, raw: bytes | None) -> ExecutionCandidateHandoff | None:
        """Deserialize a Market→Execution handoff from JSON bytes."""
        import json
        if raw is None:
            return None
        data = json.loads(raw.decode('utf-8'))
        return self._rebuild_handoff(data)

    def _rebuild_handoff(self, data: dict[str, Any]) -> ExecutionCandidateHandoff:
        """Rebuild an ExecutionCandidateHandoff from serialized JSON, mapping
        persisted keys back to the canonical MarketCandidatePayload dataclass fields.

        BUG2-FIX: Previously used ``rows`` (nonexistent) & ``generated_at`` (nonexistent)
        and omitted the required ``source``, ``handoff_target``, ``filters``, ``sort`` fields.
        """
        meta = HandoffMetadata(**data["metadata"])
        cp_data = data["candidate_payload"]
        filters_data = cp_data.get("filters", {})
        filters = MarketSnapshotFilters(
            min_adv_20d=filters_data.get("min_adv_20d"),
            min_total_volume=filters_data.get("min_total_volume"),
            min_daily_volatility=filters_data.get("min_daily_volatility"),
            min_intraday_volatility=filters_data.get("min_intraday_volatility"),
            liquidity_alert=filters_data.get("liquidity_alert", "all"),
            volatility_alert=filters_data.get("volatility_alert", "all"),
        )
        sort_data = cp_data.get("sort", {})
        sort_spec = MarketSnapshotSort(
            field=sort_data.get("field", "total_volume"),
            direction=sort_data.get("direction", "desc"),
        )
        cp = MarketCandidatePayload(
            source=cp_data.get("source", "marketview-candidate-v1"),
            handoff_target=cp_data.get("handoff_target", "ExecutionView"),
            trade_date=cp_data.get("trade_date"),
            pool_id=cp_data.get("pool_id", ""),
            pool_label=cp_data.get("pool_label"),
            filters=filters,
            sort=sort_spec,
            row_count=cp_data.get("row_count", 0),
            candidates=[MarketCandidateRow(**r) for r in cp_data.get("candidates", [])],
        )
        return ExecutionCandidateHandoff(
            metadata=meta,
            trade_date=data.get("trade_date"),
            pool_id=data.get("pool_id", ""),
            pool_label=data.get("pool_label"),
            candidate_payload=cp,
            execution_hint=data.get("execution_hint", {}),
        )

    def _deserialize_post_trade(self, raw: bytes | None) -> ExecutionPostTradeHandoff | None:
        import json
        if raw is None:
            return None
        data = json.loads(raw.decode('utf-8'))
        meta = HandoffMetadata(**data["metadata"])
        return ExecutionPostTradeHandoff(
            metadata=meta,
            order_id=data["order_id"],
            parent_execution_id=data.get("parent_execution_id"),
            broker=data.get("broker"),
            strategy=data.get("strategy"),
            asset_class=data.get("asset_class"),
            urgency=data.get("urgency"),
            route_ids=data.get("route_ids", []),
            strategy_params=data.get("strategy_params"),
        )

    def _deserialize_recommendation(self, data: dict[str, Any]) -> BrokerStrategyRecommendation:
        """BUG2-FIX: Map from persisted Redis keys to the canonical
        BrokerStrategyRecommendation dataclass fields.
        """
        meta = HandoffMetadata(**data["metadata"])
        cohort = data.get("cohort") or data.get("cohort_id") or ""
        strategy = data.get("strategy") or data.get("strategy_alias")
        severity = (
            data.get("severity")
            or data.get("recommendation_assessment")
            or "normal"
        )
        rationale = (
            data.get("rationale")
            or data.get("cross_reference_note")
            or ""
        )
        return BrokerStrategyRecommendation(
            metadata=meta,
            cohort=cohort,
            asset_class=data.get("asset_class"),
            broker=data.get("broker"),
            strategy=strategy,
            urgency=data.get("urgency"),
            sample_size=data.get("sample_size", 0),
            arrival_bps=data.get("arrival_bps"),
            implementation_bps=data.get("implementation_bps"),
            severity=severity,
            rationale=rationale,
            source_report_trace_id=data.get("source_report_trace_id"),
        )

    # — Market → Execution —

    def publish_market_to_execution(
        self,
        candidate_payload: MarketCandidatePayload,
        *,
        execution_hint: dict[str, Any] | None = None,
        origin_trace_id: str | None = None,
    ) -> ExecutionCandidateHandoff:
        metadata = HandoffMetadata(
            contract_version=self._MARKET_CONTRACT_VERSION,
            source="MarketView",
            handoff_target="ExecutionView",
            generated_at=_now_iso(),
            trace_id=_new_trace_id("mv-ev"),
            origin_trace_id=origin_trace_id,
            source_maturity=SOURCE_MODULE_MATURITY.get("MarketView"),
        )
        handoff = ExecutionCandidateHandoff(
            metadata=metadata,
            trade_date=candidate_payload.trade_date,
            pool_id=candidate_payload.pool_id,
            pool_label=candidate_payload.pool_label,
            candidate_payload=candidate_payload,
            execution_hint=dict(execution_hint or {}),
        )
        # newest-wins 守卫（与内存后端对齐）：乱序发布保留较新条目。
        # get+set 非原子（无 WATCH/Lua），极端并发下守卫可被穿透，
        # 属尽力防护——语义仍优于 blind last-write-wins。
        current = self.get_market_to_execution()
        if (
            current is not None
            and current.metadata.generated_at > handoff.metadata.generated_at
        ):
            _log.warning(
                "handoff: 乱序发布检测 — 保留较新的 Market→Execution 条目 "
                "(existing=%s incoming=%s)",
                current.metadata.generated_at, handoff.metadata.generated_at,
            )
            return current
        # pipeline 原子写入 + TTL，防止进程在 set 与 expire 之间崩溃留下永久条目
        pipe = self._redis.pipeline()
        pipe.set(self._KEY_MV_TO_EV, self._serialize(handoff))
        pipe.expire(self._KEY_MV_TO_EV, self._TTL_SECONDS)
        pipe.execute()
        return handoff

    def get_market_to_execution(self) -> ExecutionCandidateHandoff | None:
        raw = self._redis.get(self._KEY_MV_TO_EV)
        return self._deserialize_handoff(raw)

    def clear_market_to_execution(self) -> None:
        self._redis.delete(self._KEY_MV_TO_EV)

    # — Execution → Cost —

    def publish_execution_to_cost(
        self,
        *,
        order_id: str,
        parent_execution_id: str | None,
        broker: str | None,
        strategy: str | None,
        asset_class: str | None,
        urgency: str | None,
        route_ids: Iterable[str],
        strategy_params: dict[str, Any] | None,
        candidate_trace_id: str | None = None,
        origin_trace_id: str | None = None,
    ) -> ExecutionPostTradeHandoff:
        metadata = HandoffMetadata(
            contract_version=self._EXECUTION_CONTRACT_VERSION,
            source="ExecutionView",
            handoff_target="CostView",
            generated_at=_now_iso(),
            trace_id=_new_trace_id("ev-cv"),
            origin_trace_id=origin_trace_id,
            source_maturity=SOURCE_MODULE_MATURITY.get("ExecutionView"),
        )
        handoff = ExecutionPostTradeHandoff(
            metadata=metadata,
            order_id=order_id,
            parent_execution_id=parent_execution_id,
            broker=broker,
            strategy=strategy,
            asset_class=asset_class,
            urgency=urgency,
            route_ids=list(route_ids),
            strategy_params=strategy_params,
        )
        # newest-wins 守卫：同一订单的乱序发布保留较新条目（尽力防护，非原子）
        existing = self.get_execution_to_cost(order_id)
        if (
            existing is not None
            and existing.metadata.generated_at > handoff.metadata.generated_at
        ):
            _log.warning(
                "handoff: 乱序发布检测 — 保留 order %s 较新的 Execution→Cost 条目 "
                "(existing=%s incoming=%s)",
                order_id,
                existing.metadata.generated_at, handoff.metadata.generated_at,
            )
            return existing
        # Hash 级 TTL：每次 publish 刷新整个 Hash 的过期时间（条目活跃即续期，
        # 停止写入 7 天后整体过期，避免陈旧 order→post-trade 映射被无限期消费）
        pipe = self._redis.pipeline()
        pipe.hset(self._KEY_EV_TO_CV, order_id, self._serialize(handoff))
        pipe.expire(self._KEY_EV_TO_CV, self._TTL_SECONDS)
        pipe.execute()
        return handoff

    def get_execution_to_cost(self, order_id: str) -> ExecutionPostTradeHandoff | None:
        raw = self._redis.hget(self._KEY_EV_TO_CV, order_id)
        return self._deserialize_post_trade(raw)

    # — Cost → Execution —

    def publish_cost_to_execution(
        self,
        *,
        cohort: str,
        asset_class: str | None,
        broker: str | None,
        strategy: str | None,
        urgency: str | None,
        sample_size: int,
        arrival_bps: float | None,
        implementation_bps: float | None,
        severity: str,
        rationale: str,
        source_report_trace_id: str | None = None,
        origin_trace_id: str | None = None,
    ) -> BrokerStrategyRecommendation:
        metadata = HandoffMetadata(
            contract_version=self._COST_CONTRACT_VERSION,
            source="CostView",
            handoff_target="ExecutionView",
            generated_at=_now_iso(),
            trace_id=_new_trace_id("cv-ev"),
            origin_trace_id=origin_trace_id,
            source_maturity=SOURCE_MODULE_MATURITY.get("CostView"),
        )
        rec = BrokerStrategyRecommendation(
            metadata=metadata,
            cohort=cohort,
            asset_class=asset_class,
            broker=broker,
            strategy=strategy,
            urgency=urgency,
            sample_size=sample_size,
            arrival_bps=arrival_bps,
            implementation_bps=implementation_bps,
            severity=severity,
            rationale=rationale,
            source_report_trace_id=source_report_trace_id,
        )
        # pipeline 原子写入 + 容量裁剪 + TTL，防止崩溃窗口留下无 TTL 条目
        pipe = self._redis.pipeline()
        pipe.rpush(self._KEY_CV_TO_EV, self._serialize(rec))
        pipe.ltrim(self._KEY_CV_TO_EV, -self._MAX_CV_TO_EV, -1)
        pipe.expire(self._KEY_CV_TO_EV, self._TTL_SECONDS)
        pipe.execute()
        return rec

    def list_cost_to_execution(
        self,
        *,
        asset_class: str | None = None,
        broker: str | None = None,
        limit: int = 20,
    ) -> list[BrokerStrategyRecommendation]:
        raw_items = self._redis.lrange(self._KEY_CV_TO_EV, -limit * 10, -1)
        import json
        items: list[BrokerStrategyRecommendation] = []
        for raw in raw_items:
            data = json.loads(raw.decode('utf-8'))
            items.append(self._deserialize_recommendation(data))
        filtered = [
            r for r in items
            if (asset_class is None or (r.asset_class or "") == asset_class)
            and (broker is None or (r.broker or "") == broker)
        ]
        filtered.sort(key=lambda r: r.metadata.generated_at, reverse=True)
        return filtered[:limit]

    def clear_cost_to_execution(self) -> None:
        self._redis.delete(self._KEY_CV_TO_EV)

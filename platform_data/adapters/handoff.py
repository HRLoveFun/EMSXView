"""Handoff exchange adapter (in-memory) — cross-module handoff exchange.

Extracted from the formerly monolithic adapters.py (lines 968-1157, 1473-1502).
Contains HandoffExchangeAdapter and get_shared_handoff_exchange() singleton factory.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from platform_data.config import HANDOFF_BACKEND, REDIS_URL
from platform_data.contracts.handoff_contracts import (
    BrokerStrategyRecommendation,
    ExecutionCandidateHandoff,
    ExecutionPostTradeHandoff,
    HandoffMetadata,
    _new_trace_id,
    _now_iso,
)
from platform_data.contracts.market_contracts import MarketCandidatePayload

_log = logging.getLogger(__name__)

# 防护 (H4): 内存后端的容量边界 — 防止无界写入撑爆进程内存
_MAX_EXECUTION_TO_COST = 500        # Execution→Cost 映射条目上限
_MAX_COST_TO_EXECUTION = 200        # Cost→Execution 列表上限 (与既有实现对齐)
_HANDOFF_TTL = timedelta(days=7)    # 条目过期时间, 读取/写入时惰性清理

# 防护 (M3): 跨模块策略参数载荷大小上限 64KB (API 层 schema 校验的适配器侧双保险)
_MAX_STRATEGY_PARAMS_BYTES = 64 * 1024


def _bounded_strategy_params(strategy_params: dict[str, Any] | None) -> dict[str, Any]:
    """校验并复制策略参数, 超限抛 ValueError。"""
    params = dict(strategy_params or {})
    try:
        size = len(json.dumps(params, default=str))
    except (TypeError, ValueError):
        raise ValueError("strategy_params 无法序列化") from None
    if size > _MAX_STRATEGY_PARAMS_BYTES:
        raise ValueError(
            f"strategy_params 大小超限 (max {_MAX_STRATEGY_PARAMS_BYTES // 1024}KB)"
        )
    return params


class HandoffExchangeAdapter:
    """In-memory cross-module handoff exchange.

    Holds the latest version of each of the three handoff contracts. The
    store is intentionally small and process-local; persistence is the
    responsibility of the owner domain (MarketView snapshots, ExecutionView
    parent execution records, CostView scorecards), not of the exchange
    itself.
    """

    _MARKET_CONTRACT_VERSION = "v1"
    _EXECUTION_CONTRACT_VERSION = "v1"
    _COST_CONTRACT_VERSION = "v1"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._market_to_execution: ExecutionCandidateHandoff | None = None
        self._execution_to_cost: dict[str, ExecutionPostTradeHandoff] = {}
        self._cost_to_execution: list[BrokerStrategyRecommendation] = []

    def describe(self) -> dict[str, str]:
        return {
            "domain": "handoff-exchange",
            "owner": "platform_data",
            "storage": "in-memory process-local store",
            "entrypoint": "HandoffExchangeAdapter",
        }

    # — 容量防护 (H4) —

    @staticmethod
    def _expired(handoff: ExecutionPostTradeHandoff) -> bool:
        """判定条目是否超过 TTL (解析失败按过期处理, 保守清理)。"""
        try:
            generated = datetime.fromisoformat(handoff.metadata.generated_at)
        except (TypeError, ValueError):
            return True
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        else:
            generated = generated.astimezone(timezone.utc)
        return datetime.now(timezone.utc) - generated > _HANDOFF_TTL

    def _prune_execution_to_cost(self) -> None:
        """惰性清理过期条目 (调用方需持有 _lock)。"""
        expired_keys = [
            oid for oid, h in self._execution_to_cost.items() if self._expired(h)
        ]
        for oid in expired_keys:
            del self._execution_to_cost[oid]
        if expired_keys:
            _log.debug("handoff: 清理 %d 条过期 Execution→Cost 条目", len(expired_keys))

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
        )
        handoff = ExecutionCandidateHandoff(
            metadata=metadata,
            trade_date=candidate_payload.trade_date,
            pool_id=candidate_payload.pool_id,
            pool_label=candidate_payload.pool_label,
            candidate_payload=candidate_payload,
            execution_hint=dict(execution_hint or {}),
        )
        with self._lock:
            self._market_to_execution = handoff
        return handoff

    def get_market_to_execution(self) -> ExecutionCandidateHandoff | None:
        with self._lock:
            return self._market_to_execution

    def clear_market_to_execution(self) -> None:
        with self._lock:
            self._market_to_execution = None

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
        )
        handoff = ExecutionPostTradeHandoff(
            metadata=metadata,
            order_id=str(order_id),
            parent_execution_id=parent_execution_id,
            broker=broker,
            strategy=strategy,
            asset_class=asset_class,
            urgency=urgency,
            route_ids=[str(rid) for rid in route_ids],
            strategy_params=_bounded_strategy_params(strategy_params),
            candidate_trace_id=candidate_trace_id,
        )
        with self._lock:
            self._prune_execution_to_cost()
            if len(self._execution_to_cost) >= _MAX_EXECUTION_TO_COST:
                # 容量上限: 按 generated_at 淘汰最旧条目, 防止无界增长
                oldest = min(
                    self._execution_to_cost,
                    key=lambda oid: self._execution_to_cost[oid].metadata.generated_at,
                )
                del self._execution_to_cost[oldest]
                _log.warning(
                    "handoff: Execution→Cost 映射达上限 %d, 淘汰最旧条目 %s",
                    _MAX_EXECUTION_TO_COST, oldest,
                )
            self._execution_to_cost[str(order_id)] = handoff
        return handoff

    def get_execution_to_cost(self, order_id: str) -> ExecutionPostTradeHandoff | None:
        with self._lock:
            self._prune_execution_to_cost()
            return self._execution_to_cost.get(str(order_id))

    def list_execution_to_cost(self, limit: int = 50) -> list[ExecutionPostTradeHandoff]:
        with self._lock:
            self._prune_execution_to_cost()
            values = list(self._execution_to_cost.values())
        values.sort(key=lambda h: h.metadata.generated_at, reverse=True)
        return values[:limit]

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
        with self._lock:
            self._cost_to_execution.append(rec)
            if len(self._cost_to_execution) > _MAX_COST_TO_EXECUTION:
                self._cost_to_execution = self._cost_to_execution[-_MAX_COST_TO_EXECUTION:]
        return rec

    def list_cost_to_execution(
        self,
        *,
        asset_class: str | None = None,
        broker: str | None = None,
        limit: int = 20,
    ) -> list[BrokerStrategyRecommendation]:
        with self._lock:
            items = list(self._cost_to_execution)
        items = [
            r
            for r in items
            if (asset_class is None or (r.asset_class or "") == asset_class)
            and (broker is None or (r.broker or "") == broker)
        ]
        items.sort(key=lambda r: r.metadata.generated_at, reverse=True)
        return items[:limit]

    def clear_cost_to_execution(self) -> None:
        with self._lock:
            self._cost_to_execution.clear()


# ── Exchange singleton — configurable backend ─────────────────────────────────

_EXCHANGE: HandoffExchangeAdapter | None = None


def get_shared_handoff_exchange():
    """Return the process-wide handoff exchange singleton.

    Backend is controlled by EMSXVIEW_HANDOFF_BACKEND env var:
      - "memory" (default): in-process HandoffExchangeAdapter
      - "redis": cross-process RedisHandoffExchangeAdapter
    """
    global _EXCHANGE
    if _EXCHANGE is not None:
        return _EXCHANGE

    if HANDOFF_BACKEND == "redis":
        from platform_data.adapters.redis_handoff import RedisHandoffExchangeAdapter
        _log.info("Handoff exchange: Redis backend at %s", REDIS_URL)
        _EXCHANGE = RedisHandoffExchangeAdapter(redis_url=REDIS_URL)
    else:
        _log.info("Handoff exchange: in-memory backend (single-process mode)")
        _EXCHANGE = HandoffExchangeAdapter()

    return _EXCHANGE

"""Handoff exchange adapter (in-memory) — cross-module handoff exchange.

Extracted from the formerly monolithic adapters.py (lines 968-1157, 1473-1502).
Contains HandoffExchangeAdapter and get_shared_handoff_exchange() singleton factory.
"""

from __future__ import annotations

import logging
import threading
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
            strategy_params=dict(strategy_params or {}),
            candidate_trace_id=candidate_trace_id,
        )
        with self._lock:
            self._execution_to_cost[str(order_id)] = handoff
        return handoff

    def get_execution_to_cost(self, order_id: str) -> ExecutionPostTradeHandoff | None:
        with self._lock:
            return self._execution_to_cost.get(str(order_id))

    def list_execution_to_cost(self, limit: int = 50) -> list[ExecutionPostTradeHandoff]:
        with self._lock:
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
            if len(self._cost_to_execution) > 200:
                self._cost_to_execution = self._cost_to_execution[-200:]
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

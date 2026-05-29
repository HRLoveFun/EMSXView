"""Handoff contract types (WBS-08) — pure dataclasses with factory helpers.

Ownership: platform_data (cross-module exchange contracts).
Consumers: MarketView, ExecutionView, CostView.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_trace_id(prefix: str) -> str:
    """Generate a trace id with the given prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class HandoffMetadata:
    contract_version: str
    source: str
    handoff_target: str
    generated_at: str
    trace_id: str
    origin_trace_id: str | None = None


@dataclass(frozen=True)
class ExecutionCandidateHandoff:
    """MarketView -> ExecutionView contract.

    Wraps a MarketView candidate list with an execution hint block so that
    ExecutionView can pre-fill order/route forms without requiring per-page
    local state plumbing.
    """

    metadata: HandoffMetadata
    trade_date: str | None
    pool_id: str
    pool_label: str | None
    candidate_payload: Any  # MarketCandidatePayload (avoid circular import)
    execution_hint: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPostTradeHandoff:
    """ExecutionView -> CostView contract.

    Captures the execution context of a completed order (parent execution,
    strategy parameters, child routes) that CostView needs to correlate with
    TCA metrics. The actual fill data stays in CostView stores — this
    contract only carries identifiers and policy context.
    """

    metadata: HandoffMetadata
    order_id: str
    parent_execution_id: str | None
    broker: str | None
    strategy: str | None
    asset_class: str | None
    urgency: str | None
    route_ids: list[str]
    strategy_params: dict[str, Any]
    candidate_trace_id: str | None = None  # back-pointer to MarketView handoff


@dataclass(frozen=True)
class BrokerStrategyRecommendation:
    """CostView -> ExecutionView contract.

    Represents a broker/strategy recommendation derived from the CostView
    scorecard cohort metrics. The payload is intentionally narrow: only the
    dimensions ExecutionView can act on (broker, strategy, urgency hint) plus
    the statistics that justify the recommendation.
    """

    metadata: HandoffMetadata
    cohort: str
    asset_class: str | None
    broker: str | None
    strategy: str | None
    urgency: str | None
    sample_size: int
    arrival_bps: float | None
    implementation_bps: float | None
    severity: str  # "normal" | "warning" | "critical"
    rationale: str
    source_report_trace_id: str | None = None

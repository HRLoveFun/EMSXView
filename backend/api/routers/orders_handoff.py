"""WBS-08 Handoff Contract endpoints — cross-module data handoff routes.

Extracted from the formerly mixed-domain orders.py (lines 440-545).
Phase 5: Separated handoff from CRUD and execution operations. Uses canonical
import paths per the plan's import path specification.
"""

from __future__ import annotations

from fastapi import APIRouter

from schemas.handoff import (
    HandoffMetadataResponse,
    MarketCandidatePayloadResponse,
    MarketCandidateRowResponse,
    MarketToExecutionHandoffEnvelope,
    MarketToExecutionHandoffPayload,
    PostTradeHandoffRequest,
    PostTradeHandoffPayload,
    PostTradeHandoffResponse,
)
# Phase 5: Use canonical import path (not compatibility re-export)
from platform_data.adapters.handoff import get_shared_handoff_exchange

router = APIRouter(tags=["Handoff"])


def _serialize_metadata(metadata) -> HandoffMetadataResponse:
    """Serialize handoff metadata domain object to Pydantic response model."""
    return HandoffMetadataResponse(
        contract_version=metadata.contract_version,
        source=metadata.source,
        handoff_target=metadata.handoff_target,
        generated_at=metadata.generated_at,
        trace_id=metadata.trace_id,
        origin_trace_id=metadata.origin_trace_id,
    )


# Contract 1 (inbound): MarketView → ExecutionView — peek candidates

@router.get(
    "/api/executions/handoff/candidates",
    response_model=MarketToExecutionHandoffEnvelope,
)
async def get_active_candidate_handoff():
    """Peek the latest MarketView → ExecutionView candidate handoff."""
    handoff = get_shared_handoff_exchange().get_market_to_execution()
    if handoff is None:
        return MarketToExecutionHandoffEnvelope(
            success=True, data=None, message="No active MarketView → ExecutionView handoff"
        )
    payload = handoff.candidate_payload
    data = MarketToExecutionHandoffPayload(
        metadata=_serialize_metadata(handoff.metadata),
        trade_date=handoff.trade_date,
        pool_id=handoff.pool_id,
        pool_label=handoff.pool_label,
        candidate_payload=MarketCandidatePayloadResponse(
            source=payload.source,
            handoff_target=payload.handoff_target,
            trade_date=payload.trade_date,
            pool_id=payload.pool_id,
            pool_label=payload.pool_label,
            row_count=payload.row_count,
            candidates=[
                MarketCandidateRowResponse(
                    equ_ticker=c.equ_ticker,
                    trade_date=c.trade_date,
                    daily_close=c.daily_close,
                    total_volume=c.total_volume,
                    adv_20d=c.adv_20d,
                    daily_volatility=c.daily_volatility,
                    intraday_volatility=c.intraday_volatility,
                    liquidity_alert=c.liquidity_alert,
                    volatility_alert=c.volatility_alert,
                )
                for c in payload.candidates
            ],
        ),
        execution_hint=dict(handoff.execution_hint),
    )
    return MarketToExecutionHandoffEnvelope(
        success=True,
        data=data,
        message=f"Handoff trace_id={handoff.metadata.trace_id}",
    )


# Contract 2 (outbound): ExecutionView → CostView — publish post-trade context

@router.post(
    "/api/executions/handoff/post-trade",
    response_model=PostTradeHandoffResponse,
)
async def publish_post_trade_handoff(request: PostTradeHandoffRequest):
    """Publish an ExecutionView → CostView post-trade context handoff."""
    handoff = get_shared_handoff_exchange().publish_execution_to_cost(
        order_id=request.order_id,
        parent_execution_id=request.parent_execution_id,
        broker=request.broker,
        strategy=request.strategy,
        asset_class=request.asset_class,
        urgency=request.urgency,
        route_ids=request.route_ids,
        strategy_params=request.strategy_params,
        candidate_trace_id=request.candidate_trace_id,
    )
    return PostTradeHandoffResponse(
        success=True,
        data=PostTradeHandoffPayload(
            metadata=_serialize_metadata(handoff.metadata),
            order_id=handoff.order_id,
            parent_execution_id=handoff.parent_execution_id,
            broker=handoff.broker,
            strategy=handoff.strategy,
            asset_class=handoff.asset_class,
            urgency=handoff.urgency,
            route_ids=list(handoff.route_ids),
            strategy_params=dict(handoff.strategy_params),
            candidate_trace_id=handoff.candidate_trace_id,
        ),
        message=(
            f"Published post-trade handoff for order {handoff.order_id} "
            f"(trace_id={handoff.metadata.trace_id})"
        ),
    )

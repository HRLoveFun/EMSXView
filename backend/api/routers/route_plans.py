"""Route Plan & RouteEngine domain router — /api/route-plans* and /api/route-engine* endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from schemas import (
    ApiResponse,
    BatchConfirmRequest,
    RoutePlanCreate,
    RoutePlanResponse,
    RoutePlanUpdate,
    SubOrderProposalResponse,
    TestMatchResponse,
)
from deps import verify_token, audit_log, get_bloomberg_service
from services.route_engine import RouteEngine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Route Plans & RouteEngine"])

# ---------------------------------------------------------------------------
# In-memory stores — simple dicts, same pattern as orders.py _parent_store
# ---------------------------------------------------------------------------

_plans: dict[int, dict] = {}
_allocations: dict[int, list[dict]] = {}
_proposals: dict[int, dict] = {}
_next_plan_id = 1
_next_proposal_id = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Thin object providing the 5 methods RouteEngine needs.
# Follows the existing orders.py pattern (duck-typed, no ABC).
_engine_repo = type("_EngineRepo", (), {
    "get_plan": staticmethod(lambda pid: _plans.get(pid)),
    "list_active_auto_plans": staticmethod(lambda: [
        p for p in _plans.values()
        if p.get("enabled", True) and p.get("activation_mode") == "AUTO"
    ]),
    "get_allocations_for_plan": staticmethod(lambda pid: _allocations.get(pid, [])),
    "delete_proposals_for_order": staticmethod(lambda oid: [
        _proposals.pop(pid, None)
        for pid, p in list(_proposals.items())
        if p.get("parent_order_id") == oid and p.get("status") == "PENDING_CONFIRM"
    ]),
    "create_proposals_bulk": staticmethod(lambda pds: _create_proposals(pds)),
})


def _create_proposals(pds: list[dict]) -> list[dict]:
    global _next_proposal_id
    now = _now()
    for p in pds:
        pid = _next_proposal_id
        _next_proposal_id += 1
        p["id"] = pid
        p["created_at"] = now
        p["updated_at"] = now
        _proposals[pid] = p
    return pds


def _plan_to_response(plan: dict, allocations: list[dict] | None = None) -> dict:
    """Convert a plan dict to a RoutePlanResponse-compatible dict."""
    allocs = allocations or _allocations.get(plan["id"], [])
    return {
        "id": plan["id"],
        "name": plan.get("name", ""),
        "description": plan.get("description"),
        "matchMarket": plan.get("match_market", ""),
        "matchSymbol": plan.get("match_symbol"),
        "matchSide": plan.get("match_side", "BOTH"),
        "matchPortfolio": plan.get("match_portfolio"),
        "matchTrader": plan.get("match_trader"),
        "matchExchange": plan.get("match_exchange"),
        "matchCurrency": plan.get("match_currency"),
        "activationMode": plan.get("activation_mode", "MANUAL"),
        "submissionMode": plan.get("submission_mode", "MANUAL_CONFIRM"),
        "splitType": plan.get("split_type", "BROKER_SPLIT"),
        "scheduleType": plan.get("schedule_type"),
        "numSlices": plan.get("num_slices"),
        "defaultStartOffsetMin": plan.get("default_start_offset_min"),
        "defaultEndTimeLocal": plan.get("default_end_time_local"),
        "participationRate": plan.get("participation_rate"),
        "defaultBroker": plan.get("default_broker"),
        "defaultOrderType": plan.get("default_order_type"),
        "defaultTif": plan.get("default_tif"),
        "defaultStrategyParams": plan.get("default_strategy_params"),
        "enabled": plan.get("enabled", True),
        "priority": plan.get("priority", 0),
        "allocations": [
            {
                "broker": a.get("broker", ""),
                "allocationType": a.get("allocation_type", "PERCENTAGE"),
                "allocationValue": a.get("allocation_value", 0),
                "orderType": a.get("order_type"),
                "limitPriceOffset": a.get("limit_price_offset"),
                "strategyParams": a.get("strategy_params"),
                "sortOrder": a.get("sort_order", 0),
            }
            for a in allocs
        ],
        "createdAt": plan.get("created_at", ""),
        "updatedAt": plan.get("updated_at", ""),
    }


def _proposal_to_response(p: dict) -> dict:
    """Convert a proposal dict to SubOrderProposalResponse-compatible dict."""
    return {
        "id": p["id"],
        "routePlanId": p.get("route_plan_id"),
        "parentOrderId": p.get("parent_order_id", ""),
        "routeId": p.get("route_id"),
        "broker": p.get("broker", ""),
        "quantity": p.get("quantity", 0),
        "orderType": p.get("order_type"),
        "limitPrice": p.get("limit_price"),
        "tif": p.get("tif"),
        "strategyParams": p.get("strategy_params"),
        "sliceIndex": p.get("slice_index"),
        "scheduledStart": p.get("scheduled_start"),
        "scheduledEnd": p.get("scheduled_end"),
        "parentSymbol": p.get("parent_symbol"),
        "parentSide": p.get("parent_side"),
        "parentTrader": p.get("parent_trader"),
        "parentPortfolio": p.get("parent_portfolio"),
        "status": p.get("status", ""),
        "confirmedAt": p.get("confirmed_at"),
        "submittedAt": p.get("submitted_at"),
        "createdAt": p.get("created_at", ""),
        "updatedAt": p.get("updated_at", ""),
    }


# ========================================================================
# Route Plan CRUD
# ========================================================================


@router.get("/api/route-plans", response_model=ApiResponse)
async def list_route_plans(
    enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
    user: dict = Depends(verify_token),
):
    """List all route plans, optionally filtered."""
    plans = list(_plans.values())
    if enabled:
        plans = [p for p in plans if p.get("enabled", True)]
    plans.sort(key=lambda p: (-p.get("priority", 0), p.get("created_at", "")))

    result = [_plan_to_response(p, _allocations.get(p["id"], [])) for p in plans]
    return ApiResponse(success=True, data=result, message=f"Retrieved {len(result)} route plans")


@router.post("/api/route-plans", response_model=ApiResponse)
async def create_route_plan(
    request: RoutePlanCreate,
    user: dict = Depends(verify_token),
):
    """Create a new route plan."""
    audit_log("CREATE_ROUTE_PLAN", user.get("sub"), {
        "name": request.name, "splitType": request.splitType, "activationMode": request.activationMode,
    })

    # Validate percentage allocations sum to ~100%
    if request.allocations:
        pct_total = sum(a.allocationValue for a in request.allocations if a.allocationType == "PERCENTAGE")
        if abs(pct_total - 100.0) > 0.01:
            return ApiResponse(success=False, error=f"Percentage allocations sum to {pct_total:.1f}%, expected 100%")

    global _next_plan_id
    pid = _next_plan_id
    _next_plan_id += 1
    now = _now()
    plan = {
        "id": pid,
        "name": request.name, "description": request.description,
        "match_market": request.matchMarket, "match_symbol": request.matchSymbol,
        "match_side": request.matchSide, "match_portfolio": request.matchPortfolio,
        "match_trader": request.matchTrader, "match_exchange": request.matchExchange,
        "match_currency": request.matchCurrency,
        "activation_mode": request.activationMode, "submission_mode": request.submissionMode,
        "split_type": request.splitType, "schedule_type": request.scheduleType,
        "num_slices": request.numSlices,
        "default_start_offset_min": request.defaultStartOffsetMin,
        "default_end_time_local": request.defaultEndTimeLocal,
        "participation_rate": request.participationRate,
        "default_broker": request.defaultBroker, "default_order_type": request.defaultOrderType,
        "default_tif": request.defaultTif, "default_strategy_params": request.defaultStrategyParams,
        "enabled": request.enabled, "priority": request.priority,
        "created_at": now, "updated_at": now,
    }
    _plans[pid] = plan

    if request.allocations:
        alloc_dicts = [
            {**a.model_dump(), "route_plan_id": pid,
             "allocation_type": a.allocationType, "allocation_value": a.allocationValue,
             "order_type": a.orderType, "limit_price_offset": a.limitPriceOffset,
             "strategy_params": a.strategyParams, "sort_order": a.sortOrder}
            for a in request.allocations
        ]
        _allocations[pid] = alloc_dicts

    return ApiResponse(success=True, data=_plan_to_response(plan, _allocations.get(pid, [])),
                       message=f"Route plan '{request.name}' created")


@router.get("/api/route-plans/{plan_id}", response_model=ApiResponse)
async def get_route_plan(plan_id: int, user: dict = Depends(verify_token)):
    """Get a single route plan by ID."""
    plan = _plans.get(plan_id)
    if plan is None:
        raise HTTPException(404, f"Route plan {plan_id} not found")
    return ApiResponse(success=True, data=_plan_to_response(plan, _allocations.get(plan_id, [])))


@router.put("/api/route-plans/{plan_id}", response_model=ApiResponse)
async def update_route_plan(
    plan_id: int, request: RoutePlanUpdate, user: dict = Depends(verify_token),
):
    """Update an existing route plan (partial update)."""
    audit_log("UPDATE_ROUTE_PLAN", user.get("sub"), {"planId": plan_id})

    plan = _plans.get(plan_id)
    if plan is None:
        raise HTTPException(404, f"Route plan {plan_id} not found")

    # Apply only non-None fields from request → snake_case
    _apply_updates(plan, request)

    if request.allocations is not None:
        if request.allocations:
            _allocations[plan_id] = [
                {**a.model_dump(), "route_plan_id": plan_id,
                 "allocation_type": a.allocationType, "allocation_value": a.allocationValue,
                 "order_type": a.orderType, "limit_price_offset": a.limitPriceOffset,
                 "strategy_params": a.strategyParams, "sort_order": a.sortOrder}
                for a in request.allocations
            ]
        else:
            _allocations.pop(plan_id, None)

    plan["updated_at"] = _now()
    return ApiResponse(success=True, data=_plan_to_response(plan, _allocations.get(plan_id, [])),
                       message=f"Route plan {plan_id} updated")


@router.delete("/api/route-plans/{plan_id}", response_model=ApiResponse)
async def delete_route_plan(plan_id: int, user: dict = Depends(verify_token)):
    """Delete a route plan and its allocations."""
    audit_log("DELETE_ROUTE_PLAN", user.get("sub"), {"planId": plan_id})
    if plan_id not in _plans:
        raise HTTPException(404, f"Route plan {plan_id} not found")
    _plans.pop(plan_id, None)
    _allocations.pop(plan_id, None)
    return ApiResponse(success=True, message=f"Route plan {plan_id} deleted")


# Map camelCase request fields → snake_case dict keys
_FIELD_MAP = [
    ("name", "name"), ("description", "description"),
    ("matchMarket", "match_market"), ("matchSymbol", "match_symbol"),
    ("matchSide", "match_side"), ("matchPortfolio", "match_portfolio"),
    ("matchTrader", "match_trader"), ("matchExchange", "match_exchange"),
    ("matchCurrency", "match_currency"),
    ("activationMode", "activation_mode"), ("submissionMode", "submission_mode"),
    ("splitType", "split_type"), ("scheduleType", "schedule_type"),
    ("numSlices", "num_slices"),
    ("defaultStartOffsetMin", "default_start_offset_min"),
    ("defaultEndTimeLocal", "default_end_time_local"),
    ("participationRate", "participation_rate"),
    ("defaultBroker", "default_broker"), ("defaultOrderType", "default_order_type"),
    ("defaultTif", "default_tif"), ("defaultStrategyParams", "default_strategy_params"),
    ("enabled", "enabled"), ("priority", "priority"),
]


def _apply_updates(plan: dict, request) -> None:
    for req_field, db_field in _FIELD_MAP:
        val = getattr(request, req_field, None)
        if val is not None:
            plan[db_field] = val


# ========================================================================
# Test Match
# ========================================================================


@router.post("/api/route-plans/{plan_id}/test-match", response_model=ApiResponse)
async def test_match_route_plan(
    plan_id: int,
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Test a route plan against current orders — returns matching order IDs."""
    plan = _plans.get(plan_id)
    if plan is None:
        raise HTTPException(404, f"Route plan {plan_id} not found")
    orders = await bloomberg.get_orders()

    engine = RouteEngine(_engine_repo)

    # Build a lightweight proxy for _order_matches_plan
    plan_proxy = type("_P", (), {k: v for k, v in plan.items()})()
    matched_ids = [o.id for o in orders if engine._order_matches_plan(o, plan_proxy)]

    result = TestMatchResponse(
        planId=plan_id, planName=plan.get("name", ""),
        matchedOrders=matched_ids, matchCount=len(matched_ids),
    )
    return ApiResponse(success=True, data=result.model_dump(),
                       message=f"Plan matches {len(matched_ids)} orders")


# ========================================================================
# RouteEngine — Apply
# ========================================================================


@router.post("/api/route-engine/apply/{order_id}", response_model=ApiResponse)
async def apply_route_engine(
    order_id: str,
    plan_id: Optional[int] = Query(None, description="Specific plan ID (MANUAL mode); omit for AUTO matching"),
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Apply RouteEngine to a specific order."""
    audit_log("APPLY_ROUTE_ENGINE", user.get("sub"), {"orderId": order_id, "planId": plan_id})
    parent_order = None
    if hasattr(bloomberg, "_orders") and hasattr(bloomberg, "_data_lock"):
        with bloomberg._data_lock:
            parent_order = bloomberg._orders.get(order_id)
    if parent_order is None:
        raise HTTPException(404, f"Order {order_id} not found in subscription cache")

    engine = RouteEngine(_engine_repo)

    try:
        proposals = await engine.process_order(parent_order, plan_id=plan_id)
    except Exception as exc:
        logger.exception("RouteEngine failed for order %s", order_id)
        return ApiResponse(success=False, error=str(exc))

    result = [_proposal_to_response(p) for p in proposals]
    return ApiResponse(success=True, data=result,
                       message=f"Generated {len(result)} sub-order proposals for order {order_id}")


# ========================================================================
# Sub-Order Proposals
# ========================================================================


@router.get("/api/sub-order-proposals", response_model=ApiResponse)
async def list_sub_order_proposals(
    status: Optional[str] = Query(None),
    trader: Optional[str] = Query(None),
    user: dict = Depends(verify_token),
):
    """List sub-order proposals, defaulting to PENDING_CONFIRM."""
    proposals = [_proposal_to_response(p) for p in _proposals.values()
                 if (not status or p.get("status") == status)
                 and (not trader or p.get("parent_trader") == trader)]
    proposals.sort(key=lambda p: p["createdAt"], reverse=True)
    return ApiResponse(success=True, data=proposals[:200],
                       message=f"Retrieved {len(proposals)} proposals")


@router.post("/api/sub-order-proposals/{proposal_id}/confirm", response_model=ApiResponse)
async def confirm_proposal(
    proposal_id: int,
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Confirm and submit a single sub-order proposal via RouteEx."""
    audit_log("CONFIRM_PROPOSAL", user.get("sub"), {"proposalId": proposal_id})

    proposal = _proposals.get(proposal_id)
    if proposal is None:
        raise HTTPException(404, f"Proposal {proposal_id} not found")
    if proposal.get("status") != "PENDING_CONFIRM":
        raise HTTPException(400, f"Proposal {proposal_id} has status '{proposal.get('status')}', not PENDING_CONFIRM")
    try:
        from schemas import RouteOrderRequest
        route_req = RouteOrderRequest(
            orderId=proposal["parent_order_id"],
            broker=proposal["broker"],
            quantity=proposal["quantity"],
            orderType=proposal.get("order_type") or "LIMIT",
            price=proposal.get("limit_price"),
            timeInForce=proposal.get("tif") or "DAY",
            strategyParams=proposal.get("strategy_params"),
        )
        result = await bloomberg.route_order(route_req)
        route_id = result.get("routeId") if isinstance(result, dict) else None

        now = _now()
        proposal.update(status="SUBMITTED", route_id=route_id, confirmed_at=now, submitted_at=now, updated_at=now)
        return ApiResponse(success=True, message=f"Proposal {proposal_id} submitted as route {route_id}")
    except Exception as exc:
        logger.exception("Failed to submit proposal %d", proposal_id)
        return ApiResponse(success=False, error=str(exc))


@router.post("/api/sub-order-proposals/batch-confirm")
async def batch_confirm_proposals(
    request: BatchConfirmRequest,
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Batch confirm and submit multiple proposals.

    - ``dryRun=true`` -> sync JSON BatchOperationResult (validation only).
    - ``dryRun=false`` -> NDJSON stream via batch_route_service.
    """
    audit_log("BATCH_CONFIRM_PROPOSALS", user.get("sub"), {
        "proposalIds": request.proposalIds, "dryRun": request.dryRun,
    })

    # Validate all proposals exist and are PENDING_CONFIRM
    route_items = []
    for pid in request.proposalIds:
        proposal = _proposals.get(pid)
        if proposal is None:
            raise HTTPException(404, f"Proposal {pid} not found")
        if proposal.get("status") != "PENDING_CONFIRM":
            raise HTTPException(400, f"Proposal {pid} has status '{proposal.get('status')}', not PENDING_CONFIRM")

        from schemas import BatchRouteOrderItem
        route_items.append(BatchRouteOrderItem(
            orderId=proposal["parent_order_id"], clientKey=str(pid),
            override={
                "broker": proposal["broker"], "quantity": proposal["quantity"],
                "orderType": proposal.get("order_type") or "LIMIT",
                "price": proposal.get("limit_price"),
                "timeInForce": proposal.get("tif") or "DAY",
                "strategyParams": proposal.get("strategy_params"),
            },
        ))

    from schemas import BatchRouteOrderRequest
    batch_req = BatchRouteOrderRequest(template={}, items=route_items, dryRun=request.dryRun)

    from services import batch_route_service
    terminal_trader = (
        bloomberg.get_terminal_trader_name()
        if hasattr(bloomberg, "get_terminal_trader_name") else None
    )

    if request.dryRun:
        result = await batch_route_service.dry_run_batch_route(
            bloomberg, batch_req, terminal_trader=terminal_trader,
        )
        return ApiResponse(success=True, data=result.model_dump(),
                           message=f"Dry-run: {result.succeeded} ready, {result.blocked} blocked")

    async def _stream_with_status_update():
        now = _now()
        submitted_ids: set[int] = set()
        import json

        async for line in batch_route_service.stream_batch_route(
            bloomberg, batch_req, terminal_trader=terminal_trader,
        ):
            try:
                obj = json.loads(line) if isinstance(line, str) else line
                if isinstance(obj, dict):
                    if obj.get("status") == "SUCCESS":
                        try:
                            pid = int(obj.get("key", "0"))
                            if pid > 0:
                                submitted_ids.add(pid)
                        except ValueError:
                            pass
                    elif "summary" in obj:
                        for pid in submitted_ids:
                            p = _proposals.get(pid)
                            if p:
                                p.update(status="SUBMITTED", confirmed_at=now, submitted_at=now, updated_at=now)
            except Exception:
                pass
            yield line if isinstance(line, str) else json.dumps(line) + "\n"

    return StreamingResponse(_stream_with_status_update(), media_type="application/x-ndjson")


@router.post("/api/sub-order-proposals/{proposal_id}/reject", response_model=ApiResponse)
async def reject_proposal(proposal_id: int, user: dict = Depends(verify_token)):
    """Reject a sub-order proposal."""
    audit_log("REJECT_PROPOSAL", user.get("sub"), {"proposalId": proposal_id})

    proposal = _proposals.get(proposal_id)
    if proposal is None:
        raise HTTPException(404, f"Proposal {proposal_id} not found")

    proposal["status"] = "REJECTED"
    proposal["updated_at"] = _now()
    return ApiResponse(success=True, message=f"Proposal {proposal_id} rejected")

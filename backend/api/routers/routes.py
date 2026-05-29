"""Routes domain router — /api/routes* endpoints."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from schemas import (
    ApiResponse,
    BatchModifyRouteRequest,
    CancelRouteRequest,
    ModifyRouteRequest,
)
from deps import verify_token, audit_log, get_bloomberg
from services import batch_route_service, compliance_service

router = APIRouter(tags=["Routes"])


@router.get("/api/routes", response_model=ApiResponse)
async def get_routes(user: dict = Depends(verify_token)):
    """Get routes from EMSX subscription cache."""
    routes = await get_bloomberg().get_routes()
    return ApiResponse(success=True, data=routes, message=f"Retrieved {len(routes)} routes")


@router.post("/api/routes/cancel", response_model=ApiResponse)
async def cancel_route(request: CancelRouteRequest, user: dict = Depends(verify_token)):
    """Cancel a route via CancelRouteEx."""
    audit_log("CANCEL_ROUTE", user.get("sub"), {
        "sequence": request.sequence, "routeId": request.routeId,
    })
    await get_bloomberg().cancel_route(request)
    return ApiResponse(success=True, message=f"Route {request.routeId} cancel request sent")


@router.post("/api/routes/modify", response_model=ApiResponse)
async def modify_route(request: ModifyRouteRequest, user: dict = Depends(verify_token)):
    """Modify a route via ModifyRouteEx."""
    audit_log("MODIFY_ROUTE", user.get("sub"), {
        "sequence": request.sequence, "routeId": request.routeId,
        "fields": request.model_dump(exclude_none=True, exclude={"sequence", "routeId"}),
    })
    bloomberg = get_bloomberg()
    # Pre-trade compliance check using the cached route + parent order.
    cached_route = None
    parent_order = None
    if hasattr(bloomberg, "_routes") and hasattr(bloomberg, "_data_lock"):
        key = f"{request.sequence}.{request.routeId}"
        with bloomberg._data_lock:
            cached_route = bloomberg._routes.get(key)
            if cached_route is not None:
                parent_order = bloomberg._orders.get(str(request.sequence))
    if cached_route is not None:
        new_limit = request.limitPrice if "limitPrice" in request.model_fields_set else None
        new_stop = request.stopPrice if "stopPrice" in request.model_fields_set else None
        violations = compliance_service.check_modify(
            cached_route, parent_order,
            new_qty=request.amount,
            new_limit_price=new_limit,
            new_stop_price=new_stop,
            new_order_type=request.orderType,
        )
        if violations:
            raise HTTPException(
                400,
                detail={
                    "message": "Pre-trade compliance check failed",
                    "violations": [v.model_dump() for v in violations],
                },
            )
    await bloomberg.modify_route(request)
    return ApiResponse(success=True, message=f"Route {request.routeId} modify request sent")


@router.post("/api/routes/batch-modify")
async def batch_modify_routes(request: BatchModifyRouteRequest, user: dict = Depends(verify_token)):
    """Batch-modify N existing routes.

    - ``dryRun=true``  -> sync JSON ``BatchOperationResult``.
    - ``dryRun=false`` -> NDJSON stream of ``BatchOperationItemResult`` lines
      followed by a final ``{"summary": BatchOperationResult}`` line.
    """
    audit_log("BATCH_MODIFY_ROUTE", user.get("sub"), {
        "itemCount": len(request.items),
        "templateKeys": sorted(request.template.keys()),
        "dryRun": request.dryRun,
    })
    bloomberg = get_bloomberg()
    if request.dryRun:
        result = await batch_route_service.dry_run_batch_modify(bloomberg, request)
        return ApiResponse(
            success=True, data=result.model_dump(),
            message=f"Dry-run: {result.succeeded} ready, {result.blocked} blocked",
        )
    return StreamingResponse(
        batch_route_service.stream_batch_modify(bloomberg, request),
        media_type="application/x-ndjson",
    )


@router.get("/api/routes/diagnose-strategy-rate", response_model=ApiResponse)
async def diagnose_strategy_rate(user: dict = Depends(verify_token)):
    """Diagnose routes where strategy Rate information appears to be missing.

    Scans the live route cache and groups routes by (broker, strategyType),
    reporting for each route whether ``EMSX_STRATEGY_PART_RATE1`` /
    ``EMSX_STRATEGY_PART_RATE2`` were populated in the subscription stream.

    The response contains:
      - ``routes``: per-route diagnostic row (sequence, routeId, broker,
        strategyType, rate1, rate2, hasRate, status, ticker)
      - ``groups``: groupings by (broker, strategyType) with counts of routes
        that have / are missing rate info, so a user can quickly see whether
        a specific broker/strategy pair is systematically missing the field.
      - ``summary``: overall counts.

    Intended to help investigate cases such as "EQ-JPM some routes show Rate
    in Strat Params and some do not" by surfacing the raw subscription values.
    """
    routes = await get_bloomberg().get_routes()

    rows: list[dict] = []
    grouped: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"withRate": 0, "withoutRate": 0, "routes": []}
    )

    for r in routes:
        strategy_type = (r.get("strategyType") or "").strip()
        if not strategy_type:
            continue
        rate1 = r.get("strategyPartRate1")
        rate2 = r.get("strategyPartRate2")
        has_rate = (rate1 is not None) or (rate2 is not None)
        row = {
            "sequence": r.get("sequence"),
            "routeId": r.get("routeId"),
            "broker": r.get("broker") or "",
            "strategyType": strategy_type,
            "strategyStyle": r.get("strategyStyle") or "",
            "rate1": rate1,
            "rate2": rate2,
            "hasRate": has_rate,
            "status": r.get("status") or "",
            "ticker": r.get("ticker") or "",
        }
        rows.append(row)

        key = (row["broker"], strategy_type)
        bucket = grouped[key]
        if has_rate:
            bucket["withRate"] += 1
        else:
            bucket["withoutRate"] += 1
        bucket["routes"].append(row)

    groups = [
        {
            "broker": broker,
            "strategyType": strat,
            "withRate": bucket["withRate"],
            "withoutRate": bucket["withoutRate"],
            "total": bucket["withRate"] + bucket["withoutRate"],
            "routes": bucket["routes"],
        }
        for (broker, strat), bucket in sorted(grouped.items())
    ]

    summary = {
        "totalRoutesWithStrategy": len(rows),
        "routesWithRate": sum(1 for r in rows if r["hasRate"]),
        "routesMissingRate": sum(1 for r in rows if not r["hasRate"]),
        "brokerStrategyPairsFullyMissing": sum(
            1 for g in groups if g["withRate"] == 0 and g["withoutRate"] > 0
        ),
        "brokerStrategyPairsPartiallyMissing": sum(
            1 for g in groups if g["withRate"] > 0 and g["withoutRate"] > 0
        ),
    }

    return ApiResponse(
        success=True,
        data={"summary": summary, "groups": groups, "routes": rows},
        message=f"Diagnosed {len(rows)} routes across {len(groups)} broker/strategy pairs",
    )


@router.get("/api/routes/reference-enums", response_model=ApiResponse)
async def get_route_enums(user: dict = Depends(verify_token)):
    """Return reference enums used by the Modify Route dialog.

    The frontend must not hard-code Bloomberg EMSX order-type / TIF codes;
    this endpoint is the single source of truth. Each entry carries the
    EMSX wire value plus UI metadata (label, whether limit / stop price
    apply) so the dialog can render correctly and validate inputs without
    duplicating business rules.
    """
    order_types = [
        {"value": "MKT",        "label": "Market (MKT)",        "needsLimit": False, "needsStop": False},
        {"value": "LMT",        "label": "Limit (LMT)",         "needsLimit": True,  "needsStop": False},
        {"value": "STP",        "label": "Stop (STP)",          "needsLimit": False, "needsStop": True},
        {"value": "STOP_LIMIT", "label": "Stop Limit",          "needsLimit": True,  "needsStop": True},
    ]
    tif_options = [
        {"value": "DAY", "label": "Day"},
        {"value": "GTC", "label": "Good Till Cancelled"},
        {"value": "IOC", "label": "Immediate or Cancel"},
        {"value": "FOK", "label": "Fill or Kill"},
        {"value": "GTD", "label": "Good Till Date"},
    ]
    return ApiResponse(
        success=True,
        data={"orderTypes": order_types, "tifOptions": tif_options},
        message="Route reference enums",
    )

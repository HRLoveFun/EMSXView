"""Routes domain router — /api/routes* endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from schemas import ApiResponse, CancelRouteRequest, ModifyRouteRequest
from deps import verify_token, audit_log, get_bloomberg

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
    await get_bloomberg().modify_route(request)
    return ApiResponse(success=True, message=f"Route {request.routeId} modify request sent")

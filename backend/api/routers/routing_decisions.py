"""Routing decision log router（057 DL-21/075，只读查询）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from deps import verify_token
from schemas import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Routing Decisions"])


@router.get("/api/routing-decisions", response_model=ApiResponse)
async def list_routing_decisions(
    order_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=500),
    user: dict = Depends(verify_token),
) -> ApiResponse:
    """按订单查询影子决策记录（DL-21；不可变记录，按写入倒序）。"""
    from services.decision_log_service import load_decisions

    try:
        records = await load_decisions(order_id=order_id, limit=limit)
    except Exception:
        logger.warning("routing decisions query failed", exc_info=True)
        return ApiResponse(success=False, error="Routing decision store unavailable")
    return ApiResponse(success=True, data={"records": records, "count": len(records)})

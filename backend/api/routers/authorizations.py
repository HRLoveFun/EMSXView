"""PM authorization endpoints (S12/042) — /api/authorizations*.

登记 PM 数量授权并查询剩余量；下单入口的授权校验由
services/authorization_service.check_authorization 提供。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from deps import verify_token, require_permission, get_repo_provider
from models.authorization import AuthorizationIntent
from schemas import ApiResponse
from services.authorization_service import compute_remaining
from service_provider import RepositoryProvider

router = APIRouter(tags=["Authorizations"])


class AuthorizationCreate(BaseModel):
    """PM 授权录入请求。"""

    symbol: str = Field(..., min_length=1, max_length=32, description="标的（如 AAPL US Equity）")
    side: str = Field(..., pattern="^(BUY|SELL)$")
    portfolio: str | None = Field(None, max_length=64, description="组合（空 = 不限）")
    targetQuantity: int = Field(..., ge=1, description="PM 授权目标数量")
    note: str | None = Field(None, max_length=256)


async def _load_order_payloads(provider: RepositoryProvider) -> dict[str, dict]:
    """order_id → {symbol, side, portfolio}（orders_projection payload）。"""
    payloads: dict[str, dict] = {}
    for p in await provider.load_orders(limit=5000):
        oid = str(p.get("id") or p.get("orderId") or "")
        if oid:
            payloads[oid] = p
    return payloads


@router.post("/api/authorizations", response_model=ApiResponse)
async def create_authorization(
    request: AuthorizationCreate,
    user: dict = Depends(require_permission("admin")),
) -> ApiResponse:
    """登记一条 PM 授权（投资决策层数量上限）。"""
    provider = get_repo_provider()
    if not (provider and provider.is_active):
        return ApiResponse(success=False, error="Authorization persistence unavailable (DB not active)")

    intent = AuthorizationIntent(
        symbol=request.symbol.strip().upper(),
        side=request.side,
        portfolio=(request.portfolio or "").strip() or None,
        target_quantity=request.targetQuantity,
        status="ACTIVE",
        created_by=user.get("sub"),
        note=request.note,
    )
    intent_id = await provider.create_authorization(intent)
    if intent_id is None:
        return ApiResponse(success=False, error="Failed to persist authorization")
    return ApiResponse(
        success=True,
        data={"id": intent_id},
        message=f"Authorization {intent_id} created for {intent.symbol} {intent.side}",
    )


@router.get("/api/authorizations", response_model=ApiResponse)
async def list_authorizations(
    user: dict = Depends(verify_token),
) -> ApiResponse:
    """列出授权及剩余量（执行占用经父单聚合）。"""
    provider = get_repo_provider()
    if not (provider and provider.is_active):
        return ApiResponse(success=True, data=[], message="Authorization persistence unavailable")

    intents = await provider.load_authorizations(active_only=True)
    parents = await provider.run_parent_child_op("list_active_parents") or []
    remaining = compute_remaining(intents, parents, await _load_order_payloads(provider))
    return ApiResponse(success=True, data=remaining, message=f"{len(remaining)} authorization(s)")

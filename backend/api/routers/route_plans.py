"""Route Plan & RouteEngine domain router — /api/route-plans* and /api/route-engine* endpoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from schemas import (
    ApiResponse,
    BatchConfirmRequest,
    ProposalResolveRequest,
    RoutePlanCreate,
    RoutePlanUpdate,
    TestMatchResponse,
)
from deps import verify_token, require_permission, audit_log, audit_result, get_bloomberg_service, get_repo_provider
from models.route_plan import RoutePlan, RoutePlanAllocation
from services import compliance_service
from services.authorization_service import enforce_for_order
from services.route_engine import RouteEngine
from services.submission_service import submit_proposal_core

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

# per-proposal 确认锁 (S3/032)：保证 check→submit→update 的原子性；
# 随 proposal 生命周期保留，不做 pop 清理（避免新建锁竞态）
_confirm_locks: dict[int, asyncio.Lock] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 内存 dict → SQLAlchemy 模型转换。
# RouteEngine 按属性访问 plan/allocation，且 match_plans 会对 created_at 调
# .timestamp()——必须传入 datetime 而非 ISO 字符串，故做显式模型转换。
# ---------------------------------------------------------------------------

_ALLOC_MODEL_KEYS = (
    "id", "route_plan_id", "broker", "allocation_type", "allocation_value",
    "order_type", "limit_price_offset", "strategy_params", "sort_order",
)


def _plan_dict_to_model(plan: dict) -> RoutePlan:
    """内存 plan dict → RoutePlan 模型（ISO 时间解析为 datetime）。"""
    data = dict(plan)
    data["created_at"] = datetime.fromisoformat(plan["created_at"])
    data["updated_at"] = datetime.fromisoformat(plan["updated_at"])
    return RoutePlan(**data)


def _alloc_dict_to_model(alloc: dict) -> RoutePlanAllocation:
    """内存 allocation dict → RoutePlanAllocation 模型（过滤 camelCase 残键）。"""
    return RoutePlanAllocation(**{k: alloc[k] for k in _ALLOC_MODEL_KEYS if k in alloc})


class _EngineRepo:
    """RouteEngine 的内存仓库适配器——异步接口，与 route_engine.py 契约一致。

    修复 (S1/030)：原实现为同步 staticmethod，引擎侧 ``await repo.get_plan(...)``
    对普通返回值执行 await 抛 TypeError，整条计划→建议链路不可用。
    """

    async def get_plan(self, plan_id: int) -> RoutePlan | None:
        plan = _plans.get(plan_id)
        return _plan_dict_to_model(plan) if plan else None

    async def list_active_auto_plans(self) -> list[RoutePlan]:
        return [
            _plan_dict_to_model(p) for p in _plans.values()
            if p.get("enabled", True) and p.get("activation_mode") == "AUTO"
        ]

    async def get_allocations_for_plan(self, plan_id: int) -> list[RoutePlanAllocation]:
        return [_alloc_dict_to_model(a) for a in _allocations.get(plan_id, [])]

    async def delete_proposals_for_order(self, parent_order_id: str) -> list[dict]:
        return [
            _proposals.pop(pid, None)
            for pid, p in list(_proposals.items())
            if p.get("parent_order_id") == parent_order_id
            and p.get("status") == "PENDING_CONFIRM"
        ]

    async def create_proposals_bulk(self, pds: list[dict]) -> list[dict]:
        return await _create_proposals(pds)


# 模块级单例：RouteEngine(_engine_repo) 调用点无需感知实例化
_engine_repo = _EngineRepo()


async def _create_proposals(pds: list[dict]) -> list[dict]:
    """注册新建议——持久化优先 (S8/038)。

    幂等键 = SubOrderProposal 数据库主键：persist 成功时用 DB 分配的 id，
    重启后可恢复、重复确认可识别；持久化不可用时回退内存自增 id
    （此时建议重启即失，与 029-S9 前的既有行为一致）。
    """
    global _next_proposal_id
    now = _now()

    provider = get_repo_provider()
    ids: list[int] = []
    if provider and provider.is_active:
        try:
            ids = await provider.persist_proposals_bulk(pds)
        except Exception as exc:
            logger.warning("Proposal persist failed, falling back to in-memory ids: %s", exc)
    if not (ids and len(ids) == len(pds)):
        ids = []
        logger.warning("Proposals persisted without DB ids — restart recovery unavailable for this batch")

    for p in pds:
        if ids:
            pid = ids.pop(0)
            p["id"] = pid
            _next_proposal_id = max(_next_proposal_id, pid + 1)
        else:
            pid = _next_proposal_id
            _next_proposal_id += 1
            p["id"] = pid
        p["created_at"] = now
        p["updated_at"] = now
        _proposals[pid] = p
    return pds


async def _persist_proposal_result(
    proposal_id: int,
    *,
    status: str,
    route_id=None,
    confirmed_at=None,
    submitted_at=None,
) -> None:
    """确认状态机状态迁移 write-through (S8/038)。

    在返回响应前 await 完成——若响应成功但持久化失败，重启恢复后状态
    回退将引入重复确认风险，因此失败必须告警可见。
    """
    provider = get_repo_provider()
    if not (provider and provider.is_active):
        return
    try:
        ok = await provider.update_proposal_result(
            proposal_id,
            status=status,
            route_id=route_id,
            confirmed_at=confirmed_at,
            submitted_at=submitted_at,
            updated_at=confirmed_at or submitted_at,
        )
        if not ok:
            logger.warning("Proposal %d not found in DB for status update to %s", proposal_id, status)
    except Exception as exc:
        logger.error("Proposal %d status write-through failed (%s): %s", proposal_id, status, exc)


async def init_proposals_from_db(provider) -> int:
    """启动恢复 (S8/038)：从 DB 重建内存建议缓存。

    以 DB 状态为真相源——重启后已 SUBMITTED 的建议仍会拒绝重复确认。
    返回恢复的建议数量。
    """
    global _next_proposal_id
    if not provider or not provider.is_active:
        return 0
    rows = await provider.load_proposals()
    for p in rows:
        _proposals[p["id"]] = p
    if rows:
        _next_proposal_id = max(_next_proposal_id, max(r["id"] for r in rows) + 1)
    return len(rows)


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
) -> ApiResponse:
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
    user: dict = Depends(require_permission("admin")),
) -> ApiResponse:
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
async def get_route_plan(plan_id: int, user: dict = Depends(verify_token)) -> ApiResponse:
    """Get a single route plan by ID."""
    plan = _plans.get(plan_id)
    if plan is None:
        raise HTTPException(404, f"Route plan {plan_id} not found")
    return ApiResponse(success=True, data=_plan_to_response(plan, _allocations.get(plan_id, [])))


@router.put("/api/route-plans/{plan_id}", response_model=ApiResponse)
async def update_route_plan(
    plan_id: int, request: RoutePlanUpdate, user: dict = Depends(require_permission("admin")),
) -> ApiResponse:
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
async def delete_route_plan(plan_id: int, user: dict = Depends(require_permission("admin"))) -> ApiResponse:
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
) -> ApiResponse:
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
    user: dict = Depends(require_permission("admin")),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
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
        # 防护 (M5): 内部异常不原样返回
        return ApiResponse(success=False, error="Failed to generate sub-order proposals")

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
) -> ApiResponse:
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
    user: dict = Depends(require_permission("trade")),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
    """Confirm and submit a single sub-order proposal via RouteEx.

    S14/054：状态机统一走 submit_proposal_core（单笔与批量共用同一套
    锁/风控/授权/持久化/审计）；结果未知（504）冻结为 NEEDS_REVIEW——
    不可重发，人工核对后经 /resolve 解除。并发幂等由 per-proposal 锁
    保证（随 proposal 生命周期保留，不 pop）。
    """
    lock = _confirm_locks.setdefault(proposal_id, asyncio.Lock())
    async with lock:
        proposal = _proposals.get(proposal_id)
        if proposal is None:
            raise HTTPException(404, f"Proposal {proposal_id} not found")

        # 两阶段审计 (S6/036)：发起记 PENDING，完成后回填真实结果
        correlation_id = uuid4().hex
        audit_log(
            "CONFIRM_PROPOSAL", user.get("sub"), {"proposalId": proposal_id},
            result="PENDING", correlation_id=correlation_id,
        )

        def _compliance_check(p: dict):
            """与 orders_crud.route_order 同口径的 compliance 闭包。"""
            parent_order = None
            if hasattr(bloomberg, "_orders") and hasattr(bloomberg, "_data_lock"):
                with bloomberg._data_lock:
                    parent_order = bloomberg._orders.get(p["parent_order_id"])
            if parent_order is None:
                return []
            return compliance_service.check_route(
                parent_order,
                route_qty=p.get("quantity", 0),
                limit_price=p.get("limit_price"),
                stop_price=None,
                order_type=p.get("order_type") or "LIMIT",
            )

        async def _authorization_check(p: dict):
            """PM 授权闭包 (S13/043 口径)：缓存缺失跳过、not_covered 放行。"""
            parent_order = None
            if hasattr(bloomberg, "_orders") and hasattr(bloomberg, "_data_lock"):
                with bloomberg._data_lock:
                    parent_order = bloomberg._orders.get(p["parent_order_id"])
            if parent_order is None:
                return None
            return await enforce_for_order(
                get_repo_provider(),
                symbol=parent_order.symbol,
                side=parent_order.side,
                portfolio=parent_order.portfolio,
                additional_qty=p.get("quantity", 0),
            )

        result = await submit_proposal_core(
            proposal_id, proposal, bloomberg,
            correlation_id=correlation_id,
            persist_result=_persist_proposal_result,
            audit_result=audit_result,
            compliance_check=_compliance_check,
            authorization_check=_authorization_check,
        )

        if result.outcome == "SUBMITTED":
            return ApiResponse(
                success=True,
                message=f"Proposal {proposal_id} submitted as route {result.route_id}",
            )
        if result.outcome == "NEEDS_REVIEW":
            return ApiResponse(
                success=False,
                error=(
                    f"Proposal {proposal_id} submission outcome unknown "
                    f"(timeout) — frozen for manual review, use /resolve"
                ),
            )
        if result.outcome == "FAILED":
            # 防护 (M5): 内部异常不原样返回
            return ApiResponse(success=False, error="Failed to submit proposal")
        # BLOCKED（状态冲突）：core 返回而非抛出（批量复用），此处转为 HTTPException
        raise HTTPException(result.http_status or 400, result.detail)


@router.post("/api/sub-order-proposals/batch-confirm")
async def batch_confirm_proposals(
    request: BatchConfirmRequest,
    user: dict = Depends(require_permission("trade")),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
    """Batch confirm and submit multiple proposals.

    S14/054：逐建议走 submit_proposal_core（与单笔确认共用同一套
    风控/授权/锁/持久化/审计/NEEDS_REVIEW 状态机），不再经
    batch_route_service 的批量路由路径——修复「batch 未继承单笔保护」
    与「流 bytes 序列化 TypeError」两个实测缺口。
    """
    # 两阶段审计 (S6/050 模式)：发起记 PENDING，流结束后按汇总回填
    correlation_id = uuid4().hex
    audit_log("BATCH_CONFIRM_PROPOSALS", user.get("sub"), {
        "proposalIds": request.proposalIds, "dryRun": request.dryRun,
    }, result="PENDING", correlation_id=correlation_id)

    # 预检：存在性 + 状态（不含提交；逐条提交在流内走 core）
    proposals: dict[int, dict] = {}
    for pid in request.proposalIds:
        proposal = _proposals.get(pid)
        if proposal is None:
            raise HTTPException(404, f"Proposal {pid} not found")
        if proposal.get("status") != "PENDING_CONFIRM":
            raise HTTPException(
                400,
                f"Proposal {pid} has status '{proposal.get('status')}', not PENDING_CONFIRM",
            )
        proposals[pid] = proposal

    # PM 授权预检 (S13/050 模式)：任一 exceeded → 整体 403（保守整体拒绝）
    blocked_items: list[dict] = []
    if not request.dryRun:
        for pid, proposal in proposals.items():
            parent_order = None
            if hasattr(bloomberg, "_orders") and hasattr(bloomberg, "_data_lock"):
                with bloomberg._data_lock:
                    parent_order = bloomberg._orders.get(proposal["parent_order_id"])
            if parent_order is None:
                continue
            authz = await enforce_for_order(
                get_repo_provider(),
                symbol=parent_order.symbol,
                side=parent_order.side,
                portfolio=parent_order.portfolio,
                additional_qty=proposal.get("quantity", 0),
            )
            if authz and authz["outcome"] == "exceeded":
                blocked_items.append({"proposalId": pid, **authz})
            elif authz and authz["outcome"] == "not_covered":
                logger.warning(
                    "Batch proposal %d has no matching PM authorization — proceeding",
                    pid,
                )
    if blocked_items:
        audit_result(correlation_id, "fail")
        raise HTTPException(
            403,
            detail={"message": "PM authorization limit exceeded (batch)", "blocked": blocked_items},
        )

    async def _stream():
        succeeded = failed = 0
        for pid in request.proposalIds:
            proposal = _proposals.get(pid)
            if proposal is None:
                yield _ndjson({"key": str(pid), "status": "BLOCKED", "message": "not found"})
                failed += 1
                continue
            # 与单笔确认共用 per-proposal 锁，防止批量与单笔并发竞态
            lock = _confirm_locks.setdefault(pid, asyncio.Lock())
            async with lock:
                item_cid = uuid4().hex

                def _compliance_check(p: dict):
                    parent_order = None
                    if hasattr(bloomberg, "_orders") and hasattr(bloomberg, "_data_lock"):
                        with bloomberg._data_lock:
                            parent_order = bloomberg._orders.get(p["parent_order_id"])
                    if parent_order is None:
                        return []
                    return compliance_service.check_route(
                        parent_order,
                        route_qty=p.get("quantity", 0),
                        limit_price=p.get("limit_price"),
                        stop_price=None,
                        order_type=p.get("order_type") or "LIMIT",
                    )

                async def _authorization_check(p: dict):
                    parent_order = None
                    if hasattr(bloomberg, "_orders") and hasattr(bloomberg, "_data_lock"):
                        with bloomberg._data_lock:
                            parent_order = bloomberg._orders.get(p["parent_order_id"])
                    if parent_order is None:
                        return None
                    return await enforce_for_order(
                        get_repo_provider(),
                        symbol=parent_order.symbol,
                        side=parent_order.side,
                        portfolio=parent_order.portfolio,
                        additional_qty=p.get("quantity", 0),
                    )

                result = await submit_proposal_core(
                    pid, proposal, bloomberg,
                    correlation_id=item_cid,
                    persist_result=_persist_proposal_result,
                    audit_result=audit_result,
                    compliance_check=_compliance_check,
                    authorization_check=_authorization_check,
                )
            if result.outcome == "SUBMITTED":
                succeeded += 1
                yield _ndjson({"key": str(pid), "status": "SUCCESS", "routeId": result.route_id})
            elif result.outcome == "NEEDS_REVIEW":
                failed += 1
                yield _ndjson({
                    "key": str(pid), "status": "NEEDS_REVIEW",
                    "message": "outcome unknown — frozen for manual review",
                })
            elif result.outcome == "BLOCKED":
                failed += 1
                yield _ndjson({
                    "key": str(pid), "status": "BLOCKED",
                    "message": result.detail, "httpStatus": result.http_status,
                })
            else:
                failed += 1
                yield _ndjson({"key": str(pid), "status": "FAILED", "message": result.detail})
        audit_result(
            correlation_id,
            "ok" if failed == 0 and succeeded > 0 else "fail",
        )

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


def _ndjson(obj: dict) -> str:
    """NDJSON 行序列化（统一 str 输出，消除 bytes 序列化缺陷）。"""
    import json
    return json.dumps(obj) + "\n"


@router.post("/api/sub-order-proposals/{proposal_id}/resolve", response_model=ApiResponse)
async def resolve_proposal(
    proposal_id: int,
    request: ProposalResolveRequest,
    user: dict = Depends(require_permission("trade")),
) -> ApiResponse:
    """人工核对解除 NEEDS_REVIEW 建议 (S14/054)。

    提交结果未知（504/响应丢失）的建议冻结后，交易员核对终端实际状态：
    - CONFIRM_SUBMITTED：确认路由已成功 → SUBMITTED（可回填 routeId）；
    - REJECT：确认未成功/放弃 → REJECTED。
    非 NEEDS_REVIEW 状态一律拒绝（不可绕过冻结直接重发）。
    """
    audit_log("RESOLVE_PROPOSAL", user.get("sub"), {
        "proposalId": proposal_id, "action": request.action, "note": request.note,
    })
    proposal = _proposals.get(proposal_id)
    if proposal is None:
        raise HTTPException(404, f"Proposal {proposal_id} not found")
    if proposal.get("status") != "NEEDS_REVIEW":
        raise HTTPException(
            400,
            f"Proposal {proposal_id} has status '{proposal.get('status')}' — "
            "only NEEDS_REVIEW can be resolved",
        )

    now = _now()
    if request.action == "CONFIRM_SUBMITTED":
        proposal.update(
            status="SUBMITTED", route_id=request.routeId or proposal.get("route_id"),
            confirmed_at=now, submitted_at=now, updated_at=now,
        )
        await _persist_proposal_result(
            proposal_id, status="SUBMITTED", route_id=proposal.get("route_id"),
            confirmed_at=now, submitted_at=now,
        )
        return ApiResponse(
            success=True,
            message=f"Proposal {proposal_id} resolved as SUBMITTED (manual review)",
        )

    proposal["status"] = "REJECTED"
    proposal["updated_at"] = now
    await _persist_proposal_result(proposal_id, status="REJECTED", confirmed_at=now)
    return ApiResponse(success=True, message=f"Proposal {proposal_id} resolved as REJECTED (manual review)")


@router.post("/api/sub-order-proposals/{proposal_id}/reject", response_model=ApiResponse)
async def reject_proposal(proposal_id: int, user: dict = Depends(require_permission("trade"))) -> ApiResponse:
    """Reject a sub-order proposal."""
    audit_log("REJECT_PROPOSAL", user.get("sub"), {"proposalId": proposal_id})

    proposal = _proposals.get(proposal_id)
    if proposal is None:
        raise HTTPException(404, f"Proposal {proposal_id} not found")
    if proposal.get("status") == "CONFIRMING":
        # 确认进行中 (S3/032)：禁止并发 reject 覆盖中间态
        raise HTTPException(409, f"Proposal {proposal_id} is being confirmed; reject later")
    proposal["status"] = "REJECTED"
    proposal["updated_at"] = _now()
    # write-through (S8/038)：拒绝状态落库
    await _persist_proposal_result(proposal_id, status="REJECTED", confirmed_at=proposal["updated_at"])
    return ApiResponse(success=True, message=f"Proposal {proposal_id} rejected")

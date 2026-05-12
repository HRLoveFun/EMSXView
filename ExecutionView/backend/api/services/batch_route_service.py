"""Batch route / batch modify-route execution service.

Centralises:
  - Pre-trade compliance evaluation per item
  - Trader-ownership and status guards via existing ``route_service``
  - Concurrent blpapi submission bounded by ``settings.BATCH_CONCURRENCY``
    (the bloomberg adapter still serialises EMSX requests via
    ``_request_lock`` internally, so real throughput is empirical — see
    docs/knowledge/metrics.md for the live observation entry)
  - NDJSON streaming of per-item results, yielded as each completes

Two public entry points:

  - ``run_batch_route(...)``   -> for ``POST /api/orders/batch-route``
  - ``run_batch_modify(...)``  -> for ``POST /api/routes/batch-modify``

Both return either a fully materialised ``BatchOperationResult`` (when
``dryRun=True``) or an async generator yielding NDJSON lines (one
``BatchOperationItemResult`` per line + a final summary line).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import HTTPException

from config import settings
from schemas import (
    BatchModifyRouteItem,
    BatchModifyRouteRequest,
    BatchOperationItemResult,
    BatchOperationResult,
    BatchRouteOrderItem,
    BatchRouteOrderRequest,
    ModifyRouteRequest,
    RouteOrderRequest,
    Violation,
)
from services import compliance_service
from services.route_service import ROUTABLE_STATUSES

logger = logging.getLogger(__name__)


def _route_key(item: BatchRouteOrderItem) -> str:
    """Result key for a route item; falls back to orderId."""
    return item.clientKey or item.orderId


def _modify_key(item: BatchModifyRouteItem) -> str:
    return item.clientKey or f"{item.sequence}.{item.routeId}"


# ============================================================================
# Template + override merging
# ============================================================================

_ROUTE_FIELDS = {
    "broker", "quantity", "orderType", "price", "stopPrice", "timeInForce",
    "exchangeDestination", "notes", "strategyParams", "releaseTime",
}

_MODIFY_FIELDS = {
    "amount", "orderType", "limitPrice", "stopPrice", "tif", "broker",
    "exchangeDestination", "notes", "strategyParams",
}


def _merge_route_payload(
    template: Dict[str, Any],
    item: BatchRouteOrderItem,
    *,
    default_quantity: Optional[int],
) -> Dict[str, Any]:
    """Build a RouteOrderRequest-compatible payload for a batch item.

    Falls back to ``default_quantity`` (parent.remainingQuantity) when neither
    template nor override specifies ``quantity``.
    """
    merged: Dict[str, Any] = {"orderId": item.orderId}
    for field in _ROUTE_FIELDS:
        if field in template and template[field] is not None:
            merged[field] = template[field]
    if item.override:
        for field, value in item.override.items():
            if field in _ROUTE_FIELDS and value is not None:
                merged[field] = value
    if "quantity" not in merged and default_quantity is not None:
        merged["quantity"] = default_quantity
    return merged


def _merge_modify_payload(
    template: Dict[str, Any],
    item: BatchModifyRouteItem,
) -> Dict[str, Any]:
    """Build a ModifyRouteRequest-compatible payload for a batch item.

    ``ModifyRouteRequest`` uses pydantic's ``model_fields_set`` for
    limitPrice/stopPrice "explicit reset" semantics, so we must include those
    keys only when the user actually intends to set them. The merge keeps the
    same convention: a key is present iff it appears in template or override.
    """
    merged: Dict[str, Any] = {"sequence": item.sequence, "routeId": item.routeId}
    for field in _MODIFY_FIELDS:
        if field in template:
            merged[field] = template[field]
    if item.override:
        for field, value in item.override.items():
            if field in _MODIFY_FIELDS:
                merged[field] = value
    return merged


# ============================================================================
# Per-item dry-run evaluation
# ============================================================================

def _evaluate_route_item(
    bloomberg: Any,
    item: BatchRouteOrderItem,
    *,
    template: Dict[str, Any],
    terminal_trader: Optional[str],
) -> Tuple[BatchOperationItemResult, Optional[RouteOrderRequest]]:
    """Run validation + compliance for a single route-order item.

    Returns ``(result, request)``. When ``result.status != 'BLOCKED'`` and
    construction succeeded, ``request`` is the validated payload ready for
    submission. Otherwise ``request`` is None.
    """
    parent_order = None
    if hasattr(bloomberg, "_orders"):
        with getattr(bloomberg, "_data_lock"):
            parent_order = bloomberg._orders.get(item.orderId)

    rkey = _route_key(item)
    if parent_order is None:
        return (
            BatchOperationItemResult(
                key=rkey,
                status="BLOCKED",
                message=f"Order {item.orderId} not found",
                violations=[],
            ),
            None,
        )

    parent_status = getattr(parent_order, "status", "")
    if parent_status not in ROUTABLE_STATUSES:
        return (
            BatchOperationItemResult(
                key=rkey,
                status="BLOCKED",
                message=(
                    f"Order has status '{parent_status}' — only "
                    f"{', '.join(sorted(ROUTABLE_STATUSES))} can be routed"
                ),
                violations=[],
            ),
            None,
        )

    parent_trader = getattr(parent_order, "trader", None)
    if (
        terminal_trader
        and parent_trader
        and terminal_trader.upper() != parent_trader.upper()
    ):
        return (
            BatchOperationItemResult(
                key=rkey,
                status="BLOCKED",
                message=(
                    f"Order is assigned to trader '{parent_trader}', but "
                    f"current trader is '{terminal_trader}'"
                ),
                violations=[],
            ),
            None,
        )

    default_qty = int(getattr(parent_order, "remainingQuantity", 0) or 0)
    payload = _merge_route_payload(template, item, default_quantity=default_qty)

    try:
        request = RouteOrderRequest(**payload)
    except Exception as exc:  # noqa: BLE001
        return (
            BatchOperationItemResult(
                key=rkey,
                status="BLOCKED",
                message=f"Invalid request payload: {exc}",
                violations=[],
            ),
            None,
        )

    if request.quantity > default_qty:
        return (
            BatchOperationItemResult(
                key=rkey,
                status="BLOCKED",
                message=(
                    f"Route quantity ({request.quantity}) exceeds remaining "
                    f"quantity ({default_qty})"
                ),
                violations=[],
            ),
            None,
        )

    violations = compliance_service.check_route(
        parent_order,
        route_qty=request.quantity,
        limit_price=request.price,
        stop_price=request.stopPrice,
        order_type=request.orderType,
    )
    # Separate hard-block from soft-warn violations. Only BLOCK severtiy
    # prevents the route; WARN violations are carried on a SUCCESS result
    # so the UI can surface the advisory message.
    block_violations = [v for v in violations if v.severity == "BLOCK"]
    warn_violations = [v for v in violations if v.severity == "WARN"]
    if block_violations:
        return (
            BatchOperationItemResult(
                key=rkey,
                status="BLOCKED",
                message="Compliance check failed",
                violations=violations,  # all violations for full diagnostics
            ),
            None,
        )

    return (
        BatchOperationItemResult(
            key=rkey,
            status="SUCCESS",
            message="Validated",
            violations=warn_violations,  # carry soft warnings
        ),
        request,
    )


def _evaluate_modify_item(
    bloomberg: Any,
    item: BatchModifyRouteItem,
    *,
    template: Dict[str, Any],
) -> Tuple[BatchOperationItemResult, Optional[ModifyRouteRequest]]:
    key = _modify_key(item)
    cache_key = f"{item.sequence}.{item.routeId}"

    cached_route = None
    parent_order = None
    if hasattr(bloomberg, "_routes"):
        with getattr(bloomberg, "_data_lock"):
            cached_route = bloomberg._routes.get(cache_key)
            if cached_route is not None:
                parent_order = bloomberg._orders.get(str(item.sequence))

    if cached_route is None:
        return (
            BatchOperationItemResult(
                key=key,
                status="BLOCKED",
                message=f"Route {cache_key} not found",
                violations=[],
            ),
            None,
        )

    payload = _merge_modify_payload(template, item)
    try:
        request = ModifyRouteRequest(**payload)
    except Exception as exc:  # noqa: BLE001
        return (
            BatchOperationItemResult(
                key=key,
                status="BLOCKED",
                message=f"Invalid request payload: {exc}",
                violations=[],
            ),
            None,
        )

    new_limit_price: Optional[float] = (
        request.limitPrice if "limitPrice" in request.model_fields_set else None
    )
    new_stop_price: Optional[float] = (
        request.stopPrice if "stopPrice" in request.model_fields_set else None
    )
    violations = compliance_service.check_modify(
        cached_route,
        parent_order,
        new_qty=request.amount,
        new_limit_price=new_limit_price,
        new_stop_price=new_stop_price,
        new_order_type=request.orderType,
    )
    # Separate hard-block from soft-warn violations. Only BLOCK severtiy
    # prevents the modify; WARN violations are carried on a SUCCESS result
    # so the UI can surface the advisory message.
    block_violations = [v for v in violations if v.severity == "BLOCK"]
    warn_violations = [v for v in violations if v.severity == "WARN"]
    if block_violations:
        return (
            BatchOperationItemResult(
                key=key,
                status="BLOCKED",
                message="Compliance check failed",
                violations=violations,
            ),
            None,
        )

    return (
        BatchOperationItemResult(
            key=key,
            status="SUCCESS",
            message="Validated",
            violations=warn_violations,
        ),
        request,
    )


# ============================================================================
# Public entry points
# ============================================================================

def _summarise(items: List[BatchOperationItemResult]) -> BatchOperationResult:
    succeeded = sum(1 for it in items if it.status == "SUCCESS")
    blocked = sum(1 for it in items if it.status == "BLOCKED")
    failed = sum(1 for it in items if it.status == "FAILED")
    return BatchOperationResult(
        total=len(items),
        succeeded=succeeded,
        blocked=blocked,
        failed=failed,
        items=items,
    )


def _validate_split_totals(
    bloomberg: Any,
    request: BatchRouteOrderRequest,
    eval_results: List[Tuple[BatchOperationItemResult, Optional[RouteOrderRequest]]],
) -> List[Tuple[BatchOperationItemResult, Optional[RouteOrderRequest]]]:
    """Cross-item check for over-allocation:

    For each parent order, sum of validated qty must not exceed
    *effective remaining* = ``order.remainingQuantity`` minus quantity
    already pending at the broker (sum of ``route.working`` for routes
    whose status is still capacity-consuming). When violated, every item
    referencing that order is rewritten as BLOCKED.

    Operates only on currently-SUCCESS items; already-BLOCKED items are kept
    as-is so their original failure reason still surfaces.

    Note: applies even when only a single item references the order \u2014
    needed because the user may already have an in-flight working route
    from an earlier batch.
    """
    totals: Dict[str, int] = defaultdict(int)
    items_by_order: Dict[str, List[int]] = defaultdict(list)
    for idx, (result, req) in enumerate(eval_results):
        if result.status != "SUCCESS" or req is None:
            continue
        items_by_order[request.items[idx].orderId].append(idx)
        totals[request.items[idx].orderId] += int(req.quantity)

    if not totals:
        return eval_results

    # Statuses whose quantity is still committed at the broker. Mirrors
    # the frontend PENDING_ROUTE_STATUSES set so user UI and server agree
    # on what counts as "already routed and not back yet".
    pending_route_statuses = {
        "SENT", "WORKING", "PARTFILLED", "QUEUED", "HOLD",
        "CXLREQ", "CXLREJ", "CXLREP", "CXLRPRQ", "CXLRPRJ",
        "REPPEN", "A-SENT", "OA-SENT",
    }

    out = list(eval_results)
    with getattr(bloomberg, "_data_lock"):
        order_cache = getattr(bloomberg, "_orders", {}) or {}
        route_cache = getattr(bloomberg, "_routes", {}) or {}
        remaining_map: Dict[str, int] = {}
        pending_map: Dict[str, int] = {oid: 0 for oid in totals}
        for oid in totals:
            remaining_map[oid] = int(getattr(order_cache.get(oid), "remainingQuantity", 0) or 0)
        for route in route_cache.values():
            seq = str(getattr(route, "sequence", "") or "")
            if seq not in pending_map:
                continue
            status = (getattr(route, "status", "") or "").upper()
            if status not in pending_route_statuses:
                continue
            working = int(getattr(route, "working", 0) or 0)
            if working > 0:
                pending_map[seq] += working
    for oid, total_qty in totals.items():
        remain = remaining_map.get(oid, 0)
        pending = pending_map.get(oid, 0)
        effective = max(0, remain - pending)
        if total_qty > effective:
            for idx in items_by_order[oid]:
                blocked = BatchOperationItemResult(
                    key=out[idx][0].key,
                    status="BLOCKED",
                    message=(
                        f"Allocation total ({total_qty}) exceeds available capacity "
                        f"({effective} = remaining {remain} \u2212 pending {pending}) "
                        f"for order {oid}"
                    ),
                    violations=[],
                )
                out[idx] = (blocked, None)
    return out


async def dry_run_batch_route(
    bloomberg: Any,
    request: BatchRouteOrderRequest,
    *,
    terminal_trader: Optional[str],
) -> BatchOperationResult:
    """Pre-flight validation only; no blpapi calls."""
    eval_results = [
        _evaluate_route_item(
            bloomberg, item, template=request.template, terminal_trader=terminal_trader,
        )
        for item in request.items
    ]
    eval_results = _validate_split_totals(bloomberg, request, eval_results)
    items: List[BatchOperationItemResult] = [r for r, _ in eval_results]
    return _summarise(items)


async def dry_run_batch_modify(
    bloomberg: Any,
    request: BatchModifyRouteRequest,
) -> BatchOperationResult:
    items: List[BatchOperationItemResult] = []
    for item in request.items:
        result, _req = _evaluate_modify_item(bloomberg, item, template=request.template)
        items.append(result)
    return _summarise(items)


def _to_ndjson_line(obj: Any) -> bytes:
    if hasattr(obj, "model_dump"):
        payload = obj.model_dump()
    else:
        payload = obj
    return (json.dumps(payload, default=str) + "\n").encode("utf-8")


async def _submit_route(
    bloomberg: Any,
    sem: asyncio.Semaphore,
    rkey: str,
    validated_req: RouteOrderRequest,
    violations: Optional[List[Violation]] = None,
) -> BatchOperationItemResult:
    """Submit a single validated route under the semaphore; log RTT."""
    async with sem:
        t0 = time.monotonic()
        try:
            resp = await bloomberg.route_order(validated_req)
            route_id = resp.get("routeId") if isinstance(resp, dict) else None
            rtt_ms = (time.monotonic() - t0) * 1000.0
            logger.info(
                "batch-route item key=%s status=SUCCESS rtt_ms=%.1f routeId=%s",
                rkey, rtt_ms, route_id,
            )
            return BatchOperationItemResult(
                key=rkey,
                status="SUCCESS",
                message=f"Route created (routeId={route_id})" if route_id else "Route created",
                routeId=route_id,
                violations=violations or [],
            )
        except HTTPException as exc:
            rtt_ms = (time.monotonic() - t0) * 1000.0
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            logger.warning(
                "batch-route item key=%s status=FAILED rtt_ms=%.1f detail=%s",
                rkey, rtt_ms, detail,
            )
            return BatchOperationItemResult(key=rkey, status="FAILED", message=detail)
        except Exception as exc:  # noqa: BLE001
            rtt_ms = (time.monotonic() - t0) * 1000.0
            logger.exception(
                "batch-route item key=%s status=FAILED rtt_ms=%.1f unexpected",
                rkey, rtt_ms,
            )
            return BatchOperationItemResult(
                key=rkey, status="FAILED", message=f"Unexpected error: {exc}",
            )


async def _submit_modify(
    bloomberg: Any,
    sem: asyncio.Semaphore,
    mkey: str,
    validated_req: ModifyRouteRequest,
    violations: Optional[List[Violation]] = None,
) -> BatchOperationItemResult:
    async with sem:
        t0 = time.monotonic()
        try:
            await bloomberg.modify_route(validated_req)
            rtt_ms = (time.monotonic() - t0) * 1000.0
            logger.info(
                "batch-modify item key=%s status=SUCCESS rtt_ms=%.1f",
                mkey, rtt_ms,
            )
            return BatchOperationItemResult(
                key=mkey, status="SUCCESS", message="Route modified",
                violations=violations or [],
            )
        except HTTPException as exc:
            rtt_ms = (time.monotonic() - t0) * 1000.0
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            logger.warning(
                "batch-modify item key=%s status=FAILED rtt_ms=%.1f detail=%s",
                mkey, rtt_ms, detail,
            )
            return BatchOperationItemResult(key=mkey, status="FAILED", message=detail)
        except Exception as exc:  # noqa: BLE001
            rtt_ms = (time.monotonic() - t0) * 1000.0
            logger.exception(
                "batch-modify item key=%s status=FAILED rtt_ms=%.1f unexpected",
                mkey, rtt_ms,
            )
            return BatchOperationItemResult(
                key=mkey, status="FAILED", message=f"Unexpected error: {exc}",
            )


async def stream_batch_route(
    bloomberg: Any,
    request: BatchRouteOrderRequest,
    *,
    terminal_trader: Optional[str],
) -> AsyncIterator[bytes]:
    """Yield NDJSON lines: one per item, plus one final summary line.

    Items that fail dry-run (BLOCKED) are emitted immediately. Items that pass
    are submitted concurrently bounded by ``settings.BATCH_CONCURRENCY`` and
    yielded as each completes (so order in the stream may differ from input).
    """
    t_batch = time.monotonic()
    concurrency = max(1, int(settings.BATCH_CONCURRENCY))
    sem = asyncio.Semaphore(concurrency)
    eval_results = [
        _evaluate_route_item(
            bloomberg, item, template=request.template, terminal_trader=terminal_trader,
        )
        for item in request.items
    ]
    eval_results = _validate_split_totals(bloomberg, request, eval_results)

    final_results: List[BatchOperationItemResult] = []
    pending: List[asyncio.Task[BatchOperationItemResult]] = []

    for (result, validated_req) in eval_results:
        if validated_req is None or result.status != "SUCCESS":
            final_results.append(result)
            yield _to_ndjson_line(result)
            continue
        # Forward any WARN violations from the evaluation result so they
        # appear on the final SUCCESS line returned by _submit_route.
        pending.append(asyncio.create_task(
            _submit_route(bloomberg, sem, result.key, validated_req, result.violations)
        ))

    for coro in asyncio.as_completed(pending):
        finalised = await coro
        final_results.append(finalised)
        yield _to_ndjson_line(finalised)

    summary = _summarise(final_results)
    wall_ms = (time.monotonic() - t_batch) * 1000.0
    logger.info(
        "batch-route batch total=%d concurrency=%d wall_ms=%.1f succeeded=%d blocked=%d failed=%d",
        summary.total, concurrency, wall_ms, summary.succeeded, summary.blocked, summary.failed,
    )
    yield _to_ndjson_line({"summary": summary.model_dump()})


async def stream_batch_modify(
    bloomberg: Any,
    request: BatchModifyRouteRequest,
) -> AsyncIterator[bytes]:
    """Yield NDJSON lines: one per item, plus one final summary line."""
    t_batch = time.monotonic()
    concurrency = max(1, int(settings.BATCH_CONCURRENCY))
    sem = asyncio.Semaphore(concurrency)
    eval_results = [
        _evaluate_modify_item(bloomberg, item, template=request.template)
        for item in request.items
    ]

    final_results: List[BatchOperationItemResult] = []
    pending: List[asyncio.Task[BatchOperationItemResult]] = []

    for (result, validated_req) in eval_results:
        if validated_req is None or result.status != "SUCCESS":
            final_results.append(result)
            yield _to_ndjson_line(result)
            continue
        pending.append(asyncio.create_task(
            _submit_modify(bloomberg, sem, result.key, validated_req, result.violations)
        ))

    for coro in asyncio.as_completed(pending):
        finalised = await coro
        final_results.append(finalised)
        yield _to_ndjson_line(finalised)

    summary = _summarise(final_results)
    wall_ms = (time.monotonic() - t_batch) * 1000.0
    logger.info(
        "batch-modify batch total=%d concurrency=%d wall_ms=%.1f succeeded=%d blocked=%d failed=%d",
        summary.total, concurrency, wall_ms, summary.succeeded, summary.blocked, summary.failed,
    )
    yield _to_ndjson_line({"summary": summary.model_dump()})

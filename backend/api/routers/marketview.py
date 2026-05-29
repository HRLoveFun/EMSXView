"""MarketView router — stock-pool-driven pre-trade workstation endpoints.

P3 SRP refactoring: Pydantic models and serialization helpers extracted to
schemas/marketview.py. This file now contains only endpoint logic (~120 lines
vs. ~499 lines originally).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from platform_data import get_shared_handoff_exchange
from platform_data.adapters import (
    INTRADAY_BUCKET_OPTIONS,
    INTRADAY_DEFAULT_BUCKET_MINUTES,
    INTRADAY_MAX_TICKERS,
    MarketCandidatePayload,
    MarketReferenceDataAdapter,
)
from schemas.marketview import (
    IntradayFeatureEnvelope,
    MarketAlertFilter,
    MarketSnapshotEnvelope,
    MarketSortDirection,
    MarketSortField,
    MarketToExecutionHandoffEnvelope,
    MarketToExecutionPublishRequest,
    serialize_intraday_snapshot,
    serialize_market_handoff,
    serialize_snapshot,
)

router = APIRouter(tags=["MarketView"])
market = MarketReferenceDataAdapter()


# ── Market Snapshot ─────────────────────────────────────────────────────────


@router.get("/api/marketview/snapshot", response_model=MarketSnapshotEnvelope)
async def get_market_snapshot(
    limit: int = Query(default=25, ge=1, le=100),
    trade_date: Optional[str] = Query(default=None, pattern=r"^\d{8}$"),
    pool_id: str = Query(default="all"),
    min_adv_20d: Optional[float] = Query(default=None, ge=0),
    min_total_volume: Optional[float] = Query(default=None, ge=0),
    min_daily_volatility: Optional[float] = Query(default=None, ge=0),
    min_intraday_volatility: Optional[float] = Query(default=None, ge=0),
    liquidity_alert: MarketAlertFilter = Query(default="all"),
    volatility_alert: MarketAlertFilter = Query(default="all"),
    sort_by: MarketSortField = Query(default="total_volume"),
    sort_direction: MarketSortDirection = Query(default="desc"),
):
    try:
        snapshot = market.get_market_snapshot(
            limit=limit,
            trade_date=trade_date,
            pool_id=pool_id,
            min_adv_20d=min_adv_20d,
            min_total_volume=min_total_volume,
            min_daily_volatility=min_daily_volatility,
            min_intraday_volatility=min_intraday_volatility,
            liquidity_alert=liquidity_alert,
            volatility_alert=volatility_alert,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"MarketView snapshot error: {exc}")

    payload = serialize_snapshot(snapshot)
    message = (
        f"Market workstation snapshot for {payload.trade_date}: "
        f"{payload.row_count} instruments in pool {payload.active_pool_id}"
        if payload.trade_date
        else "Market snapshot unavailable — no daily summary data yet"
    )
    return MarketSnapshotEnvelope(success=True, data=payload, message=message)


# ── Intraday Features ───────────────────────────────────────────────────────


@router.get(
    "/api/marketview/intraday-features",
    response_model=IntradayFeatureEnvelope,
)
async def get_intraday_features(
    tickers: str = Query(
        ...,
        description="Comma-separated list of equ_ticker values; max "
        f"{INTRADAY_MAX_TICKERS} per call.",
    ),
    trade_date: Optional[str] = Query(default=None, pattern=r"^\d{8}$"),
    bucket_minutes: int = Query(default=INTRADAY_DEFAULT_BUCKET_MINUTES),
):
    if bucket_minutes not in INTRADAY_BUCKET_OPTIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported bucket_minutes={bucket_minutes}; "
                f"allowed values: {list(INTRADAY_BUCKET_OPTIONS)}"
            ),
        )

    ticker_list = [part.strip() for part in tickers.split(",") if part.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="tickers must include at least one value")
    if len(ticker_list) > INTRADAY_MAX_TICKERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Too many tickers requested ({len(ticker_list)}); "
                f"max {INTRADAY_MAX_TICKERS} per call"
            ),
        )

    try:
        snapshot = market.get_intraday_features(
            equ_tickers=ticker_list,
            trade_date=trade_date,
            bucket_minutes=bucket_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"MarketView intraday feature error: {exc}",
        )

    payload = serialize_intraday_snapshot(snapshot)
    if payload.trade_date is None:
        message = "Intraday features unavailable — no BDIB bars for the requested date"
    else:
        message = (
            f"Intraday features for {payload.ticker_count} tickers on "
            f"{payload.trade_date} in {payload.bucket_minutes}-minute buckets"
        )
    return IntradayFeatureEnvelope(success=True, data=payload, message=message)


# ── WBS-08 Handoff: MarketView → ExecutionView ────────────────────────────


@router.post(
    "/api/marketview/handoff/execution",
    response_model=MarketToExecutionHandoffEnvelope,
)
async def publish_execution_handoff(request: MarketToExecutionPublishRequest):
    """Publish the current MarketView candidates as a handoff to ExecutionView.

    WBS-08 contract 1: MarketView → ExecutionView. The request specifies
    which pool/trade_date/tickers to capture; the endpoint resolves the
    candidate payload from the market adapter and stores it in the shared
    handoff exchange. ExecutionView reads the active handoff via
    GET /api/executions/handoff/candidates.
    """
    try:
        snapshot = market.get_market_snapshot(
            limit=request.limit,
            trade_date=request.trade_date,
            pool_id=request.pool_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    candidate_payload = snapshot.candidate_payload
    if request.tickers:
        selected = {t for t in request.tickers}
        filtered_candidates = [
            c for c in candidate_payload.candidates if c.equ_ticker in selected
        ]
        candidate_payload = MarketCandidatePayload(
            source=candidate_payload.source,
            handoff_target=candidate_payload.handoff_target,
            trade_date=candidate_payload.trade_date,
            pool_id=candidate_payload.pool_id,
            pool_label=candidate_payload.pool_label,
            filters=candidate_payload.filters,
            sort=candidate_payload.sort,
            row_count=len(filtered_candidates),
            candidates=filtered_candidates,
        )

    handoff = get_shared_handoff_exchange().publish_market_to_execution(
        candidate_payload,
        execution_hint=request.execution_hint,
    )
    return MarketToExecutionHandoffEnvelope(
        success=True,
        data=serialize_market_handoff(handoff),
        message=(
            f"Published {candidate_payload.row_count} candidate(s) to ExecutionView "
            f"(trace_id={handoff.metadata.trace_id})"
        ),
    )

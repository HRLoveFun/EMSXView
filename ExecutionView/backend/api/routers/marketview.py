"""MarketView router — stock-pool-driven pre-trade workstation endpoints."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from platform_data.adapters import (
    INTRADAY_BUCKET_OPTIONS,
    INTRADAY_DEFAULT_BUCKET_MINUTES,
    INTRADAY_MAX_TICKERS,
    IntradayFeatureBucket,
    IntradayFeatureSnapshot,
    IntradayTickerFeatures,
    MarketAlert,
    MarketCandidatePayload,
    MarketCandidateRow,
    MarketSnapshot,
    MarketSnapshotFilters,
    MarketSnapshotSort,
    MarketStockPool,
)
from platform_data import build_platform_data_access

router = APIRouter(tags=["MarketView"])
platform_data = build_platform_data_access()

MarketAlertFilter = Literal["all", "warning", "critical"]
MarketSortField = Literal[
    "equ_ticker",
    "daily_close",
    "daily_volatility",
    "intraday_volatility",
    "total_volume",
    "adv_5d",
    "adv_20d",
    "volume_vs_adv20_pct",
    "liquidity_alert",
    "volatility_alert",
]
MarketSortDirection = Literal["asc", "desc"]


class MarketAlertResponse(BaseModel):
    code: str
    category: str
    severity: str
    message: str


class MarketStockPoolResponse(BaseModel):
    pool_id: str
    label: str
    description: str
    default_sort_by: str
    default_sort_direction: str


class MarketSnapshotFiltersResponse(BaseModel):
    min_adv_20d: Optional[float] = None
    min_total_volume: Optional[float] = None
    min_daily_volatility: Optional[float] = None
    min_intraday_volatility: Optional[float] = None
    liquidity_alert: str
    volatility_alert: str


class MarketSnapshotSortResponse(BaseModel):
    field: str
    direction: str


class MarketSnapshotRowResponse(BaseModel):
    equ_ticker: str
    trade_date: str
    daily_close: Optional[float] = None
    daily_volatility: Optional[float] = None
    intraday_volatility: Optional[float] = None
    total_volume: Optional[float] = None
    adv_5d: Optional[float] = None
    adv_20d: Optional[float] = None
    volume_vs_adv20_pct: Optional[float] = None
    liquidity_alert: str
    volatility_alert: str
    alert_count: int
    alerts: list[MarketAlertResponse] = Field(default_factory=list)


class MarketCandidateRowResponse(BaseModel):
    equ_ticker: str
    trade_date: str
    daily_close: Optional[float] = None
    total_volume: Optional[float] = None
    adv_20d: Optional[float] = None
    daily_volatility: Optional[float] = None
    intraday_volatility: Optional[float] = None
    liquidity_alert: str
    volatility_alert: str
    alerts: list[MarketAlertResponse] = Field(default_factory=list)


class MarketCandidatePayloadResponse(BaseModel):
    source: str
    handoff_target: str
    trade_date: Optional[str] = None
    pool_id: str
    pool_label: Optional[str] = None
    filters: MarketSnapshotFiltersResponse
    sort: MarketSnapshotSortResponse
    row_count: int
    candidates: list[MarketCandidateRowResponse] = Field(default_factory=list)


class MarketSnapshotPayload(BaseModel):
    trade_date: Optional[str] = None
    row_count: int
    available_pools: list[MarketStockPoolResponse] = Field(default_factory=list)
    active_pool_id: str
    filters: MarketSnapshotFiltersResponse
    sort: MarketSnapshotSortResponse
    rows: list[MarketSnapshotRowResponse] = Field(default_factory=list)
    candidate_payload: MarketCandidatePayloadResponse


class MarketSnapshotEnvelope(BaseModel):
    success: bool
    data: MarketSnapshotPayload
    message: str = ""


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
        snapshot = platform_data.market.get_market_snapshot(
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

    payload = _serialize_snapshot(snapshot)
    message = (
        f"Market workstation snapshot for {payload.trade_date}: {payload.row_count} instruments in pool {payload.active_pool_id}"
        if payload.trade_date
        else "Market snapshot unavailable — no daily summary data yet"
    )
    return MarketSnapshotEnvelope(success=True, data=payload, message=message)


def _serialize_snapshot(snapshot: MarketSnapshot) -> MarketSnapshotPayload:
    return MarketSnapshotPayload(
        trade_date=snapshot.trade_date,
        row_count=snapshot.row_count,
        available_pools=[_serialize_pool(pool) for pool in snapshot.available_pools],
        active_pool_id=snapshot.active_pool_id,
        filters=_serialize_filters(snapshot.filters),
        sort=_serialize_sort(snapshot.sort),
        rows=[_serialize_row(row) for row in snapshot.rows],
        candidate_payload=_serialize_candidate_payload(snapshot.candidate_payload),
    )


def _serialize_pool(pool: MarketStockPool) -> MarketStockPoolResponse:
    return MarketStockPoolResponse(**pool.__dict__)


def _serialize_filters(filters: MarketSnapshotFilters) -> MarketSnapshotFiltersResponse:
    return MarketSnapshotFiltersResponse(**filters.__dict__)


def _serialize_sort(sort: MarketSnapshotSort) -> MarketSnapshotSortResponse:
    return MarketSnapshotSortResponse(**sort.__dict__)


def _serialize_alert(alert: MarketAlert) -> MarketAlertResponse:
    return MarketAlertResponse(**alert.__dict__)


def _serialize_row(row) -> MarketSnapshotRowResponse:
    return MarketSnapshotRowResponse(
        equ_ticker=row.equ_ticker,
        trade_date=row.trade_date,
        daily_close=row.daily_close,
        daily_volatility=row.daily_volatility,
        intraday_volatility=row.intraday_volatility,
        total_volume=row.total_volume,
        adv_5d=row.adv_5d,
        adv_20d=row.adv_20d,
        volume_vs_adv20_pct=row.volume_vs_adv20_pct,
        liquidity_alert=row.liquidity_alert,
        volatility_alert=row.volatility_alert,
        alert_count=row.alert_count,
        alerts=[_serialize_alert(alert) for alert in row.alerts],
    )


def _serialize_candidate_row(row: MarketCandidateRow) -> MarketCandidateRowResponse:
    return MarketCandidateRowResponse(
        equ_ticker=row.equ_ticker,
        trade_date=row.trade_date,
        daily_close=row.daily_close,
        total_volume=row.total_volume,
        adv_20d=row.adv_20d,
        daily_volatility=row.daily_volatility,
        intraday_volatility=row.intraday_volatility,
        liquidity_alert=row.liquidity_alert,
        volatility_alert=row.volatility_alert,
        alerts=[_serialize_alert(alert) for alert in row.alerts],
    )


def _serialize_candidate_payload(payload: MarketCandidatePayload) -> MarketCandidatePayloadResponse:
    return MarketCandidatePayloadResponse(
        source=payload.source,
        handoff_target=payload.handoff_target,
        trade_date=payload.trade_date,
        pool_id=payload.pool_id,
        pool_label=payload.pool_label,
        filters=_serialize_filters(payload.filters),
        sort=_serialize_sort(payload.sort),
        row_count=payload.row_count,
        candidates=[_serialize_candidate_row(candidate) for candidate in payload.candidates],
    )


# ── Intraday feature service ───────────────────────────────────────────────

class IntradayFeatureBucketResponse(BaseModel):
    bucket_start: str
    bucket_end: str
    bar_count: int
    volume: Optional[float] = None
    cumulative_volume: Optional[float] = None
    cumulative_volume_pct: Optional[float] = None
    vwap: Optional[float] = None
    close: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    realized_vol_annualized: Optional[float] = None
    volume_vs_adv20_pct: Optional[float] = None


class IntradayTickerFeaturesResponse(BaseModel):
    equ_ticker: str
    trade_date: str
    bar_count: int
    first_bar_time: Optional[str] = None
    last_bar_time: Optional[str] = None
    total_volume: Optional[float] = None
    daily_vwap: Optional[float] = None
    daily_close: Optional[float] = None
    daily_volatility: Optional[float] = None
    intraday_volatility: Optional[float] = None
    adv_20d: Optional[float] = None
    open_window_volume: Optional[float] = None
    open_window_vwap: Optional[float] = None
    open_window_share_pct: Optional[float] = None
    close_window_volume: Optional[float] = None
    close_window_vwap: Optional[float] = None
    close_window_share_pct: Optional[float] = None
    volume_vs_adv20_pct: Optional[float] = None
    buckets: list[IntradayFeatureBucketResponse] = Field(default_factory=list)


class IntradayFeatureSnapshotPayload(BaseModel):
    trade_date: Optional[str] = None
    bucket_minutes: int
    ticker_count: int
    missing_tickers: list[str] = Field(default_factory=list)
    tickers: list[IntradayTickerFeaturesResponse] = Field(default_factory=list)


class IntradayFeatureEnvelope(BaseModel):
    success: bool
    data: IntradayFeatureSnapshotPayload
    message: str = ""


def _serialize_intraday_bucket(bucket: IntradayFeatureBucket) -> IntradayFeatureBucketResponse:
    return IntradayFeatureBucketResponse(**bucket.__dict__)


def _serialize_intraday_ticker(features: IntradayTickerFeatures) -> IntradayTickerFeaturesResponse:
    data = {k: v for k, v in features.__dict__.items() if k != "buckets"}
    return IntradayTickerFeaturesResponse(
        **data,
        buckets=[_serialize_intraday_bucket(bucket) for bucket in features.buckets],
    )


def _serialize_intraday_snapshot(
    snapshot: IntradayFeatureSnapshot,
) -> IntradayFeatureSnapshotPayload:
    return IntradayFeatureSnapshotPayload(
        trade_date=snapshot.trade_date,
        bucket_minutes=snapshot.bucket_minutes,
        ticker_count=snapshot.ticker_count,
        missing_tickers=list(snapshot.missing_tickers),
        tickers=[_serialize_intraday_ticker(ticker) for ticker in snapshot.tickers],
    )


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
        snapshot = platform_data.market.get_intraday_features(
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

    payload = _serialize_intraday_snapshot(snapshot)
    if payload.trade_date is None:
        message = "Intraday features unavailable — no BDIB bars for the requested date"
    else:
        message = (
            f"Intraday features for {payload.ticker_count} tickers on "
            f"{payload.trade_date} in {payload.bucket_minutes}-minute buckets"
        )
    return IntradayFeatureEnvelope(success=True, data=payload, message=message)


# ─── WBS-08 handoff contract: MarketView → ExecutionView ─────────────────────


class _HandoffMetadataResponse(BaseModel):
    contract_version: str
    source: str
    handoff_target: str
    generated_at: str
    trace_id: str
    origin_trace_id: Optional[str] = None


class MarketToExecutionHandoffPayload(BaseModel):
    metadata: _HandoffMetadataResponse
    trade_date: Optional[str] = None
    pool_id: str
    pool_label: Optional[str] = None
    candidate_payload: MarketCandidatePayloadResponse
    execution_hint: dict = Field(default_factory=dict)


class MarketToExecutionHandoffEnvelope(BaseModel):
    success: bool
    data: Optional[MarketToExecutionHandoffPayload] = None
    message: str = ""


class MarketToExecutionPublishRequest(BaseModel):
    pool_id: str = "all"
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    tickers: Optional[list[str]] = None
    execution_hint: dict = Field(default_factory=dict)
    limit: int = Field(default=40, ge=1, le=100)


def _serialize_handoff_metadata(metadata) -> _HandoffMetadataResponse:
    return _HandoffMetadataResponse(
        contract_version=metadata.contract_version,
        source=metadata.source,
        handoff_target=metadata.handoff_target,
        generated_at=metadata.generated_at,
        trace_id=metadata.trace_id,
        origin_trace_id=metadata.origin_trace_id,
    )


def _serialize_market_handoff(handoff) -> MarketToExecutionHandoffPayload:
    return MarketToExecutionHandoffPayload(
        metadata=_serialize_handoff_metadata(handoff.metadata),
        trade_date=handoff.trade_date,
        pool_id=handoff.pool_id,
        pool_label=handoff.pool_label,
        candidate_payload=_serialize_candidate_payload(handoff.candidate_payload),
        execution_hint=dict(handoff.execution_hint),
    )


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
        snapshot = platform_data.market.get_market_snapshot(
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

    from platform_data import get_shared_handoff_exchange

    handoff = get_shared_handoff_exchange().publish_market_to_execution(
        candidate_payload,
        execution_hint=request.execution_hint,
    )
    return MarketToExecutionHandoffEnvelope(
        success=True,
        data=_serialize_market_handoff(handoff),
        message=(
            f"Published {candidate_payload.row_count} candidate(s) to ExecutionView "
            f"(trace_id={handoff.metadata.trace_id})"
        ),
    )


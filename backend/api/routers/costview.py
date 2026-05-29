"""
CostView TCA router — /api/tca/* endpoints.

Provides:
  POST /api/tca/analyze          — run TCA analysis with optional filters
  POST /api/tca/trigger-update   — manually start the daily update pipeline
  GET  /api/tca/update-status/{job_id}  — poll a triggered update job

Data constraint: ALL metrics are derived exclusively from
processed_fills.db, fill_bdib.db, raw_bdib.db, and raw_fills.db.
No external API calls are made during analysis.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from platform_data.adapters import ScorecardFilters, TcaFilters
from platform_data.regime_query import get_regime_distribution
from platform_data import get_shared_handoff_exchange, get_tca_query_service

from schemas.costview import (
    PinRecommendationRequest,
    PinRecommendationResponse,
    RegimeDistributionResponse,
    RegimeDistributionRow,
    ScorecardRequest,
    ScorecardResponse,
    StageInfo,
    TcaAnalyzeRequest,
    TcaAnalyzeResponse,
    TriggerUpdateResponse,
    UpdateStatusResponse,
    serialize_report,
    serialize_scorecard,
)

from ._pipeline_jobs import get_job, trigger_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(tags=["CostView TCA"])
_analytics = get_tca_query_service()


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/api/tca/analyze", response_model=TcaAnalyzeResponse)
async def analyze_tca(request: TcaAnalyzeRequest):
    """Run TCA analysis over the filtered order set."""
    f = request.filters
    filters = TcaFilters(
        order_ids=f.order_ids,
        algo=f.algo,
        start_date=f.start_date,
        end_date=f.end_date,
        broker=f.broker,
        symbol=f.symbol,
        aggregation=request.aggregation,
        limit=request.limit,
        offset=request.offset,
    )

    try:
        report = _analytics.build_tca_report(filters)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"CostView database not found: {exc}. Run the data pipeline first.",
        )
    except Exception as exc:
        logger.error(f"TCA analysis failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TCA analysis error: {exc}")

    if report.data_source_warning:
        raise HTTPException(status_code=503, detail=report.data_source_warning)

    report_dict = serialize_report(report)
    return TcaAnalyzeResponse(
        success=True,
        data=report_dict,
        message=f"TCA report: {report.total_orders} orders matched",
    )


@router.post("/api/tca/scorecard", response_model=ScorecardResponse)
async def analyze_scorecard(request: ScorecardRequest):
    """Build a broker/strategy cohort scorecard."""
    f = request.filters
    filters = ScorecardFilters(
        cohort=request.cohort,
        order_ids=f.order_ids,
        algo=f.algo,
        start_date=f.start_date,
        end_date=f.end_date,
        broker=f.broker,
        symbol=f.symbol,
        min_sample_size=request.min_sample_size,
        max_orders=request.max_orders,
    )
    try:
        report = _analytics.build_scorecard(filters)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"CostView database not found: {exc}. Run the data pipeline first.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Scorecard analysis failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scorecard error: {exc}")

    if report.data_source_warning and not report.cohorts:
        raise HTTPException(status_code=503, detail=report.data_source_warning)

    return ScorecardResponse(
        success=True,
        data=serialize_scorecard(report),
        message=(
            f"Scorecard across {len(report.cohorts)} {request.cohort} cohort(s) "
            f"({report.total_orders_considered} orders)"
        ),
    )


@router.post("/api/tca/trigger-update", response_model=TriggerUpdateResponse)
async def trigger_update(request: Request):
    """[DEPRECATED ALIAS] Trigger the CostView daily update pipeline.

    Restricted to localhost to prevent unauthorized pipeline execution.
    """
    client_host = request.client.host if request.client else "unknown"
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            status_code=403, detail="Trigger endpoint is restricted to localhost"
        )
    result = trigger_pipeline(client_host)
    return TriggerUpdateResponse(**result)


@router.get("/api/tca/update-status/{job_id}", response_model=UpdateStatusResponse)
async def get_update_status(job_id: str):
    """[DEPRECATED ALIAS] Poll a pipeline job. Prefer /api/db/update-status."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    stage = job.get("stage")
    return UpdateStatusResponse(
        job_id=job_id,
        status=job["status"],
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        error=job.get("error"),
        stage=StageInfo(**stage) if stage else None,
        overall_progress=job.get("overall_progress", 0),
        last_activity_at=job.get("last_activity_at"),
    )


# ── WBS-08 handoff contract: CostView → ExecutionView ─────────────────────────


@router.post("/api/tca/recommendations/pin", response_model=PinRecommendationResponse)
async def pin_broker_strategy_recommendation(request: PinRecommendationRequest):
    """Pin a CostView cohort conclusion as a recommendation for ExecutionView."""
    rec = get_shared_handoff_exchange().publish_cost_to_execution(
        cohort=request.cohort,
        asset_class=request.asset_class,
        broker=request.broker,
        strategy=request.strategy,
        urgency=request.urgency,
        sample_size=request.sample_size,
        arrival_bps=request.arrival_bps,
        implementation_bps=request.implementation_bps,
        severity=request.severity,
        rationale=request.rationale,
        source_report_trace_id=request.source_report_trace_id,
    )
    return PinRecommendationResponse(
        success=True,
        data={
            "metadata": {
                "contract_version": rec.metadata.contract_version,
                "source": rec.metadata.source,
                "handoff_target": rec.metadata.handoff_target,
                "generated_at": rec.metadata.generated_at,
                "trace_id": rec.metadata.trace_id,
            },
            "cohort": rec.cohort,
            "broker": rec.broker,
            "strategy": rec.strategy,
            "severity": rec.severity,
        },
        message=f"Pinned recommendation (trace_id={rec.metadata.trace_id})",
    )


@router.get("/api/tca/handoff/post-trade/{order_id}", response_model=PinRecommendationResponse)
async def get_post_trade_handoff(order_id: str):
    """Peek the ExecutionView → CostView post-trade handoff for a given order."""
    handoff = get_shared_handoff_exchange().get_execution_to_cost(order_id)
    if handoff is None:
        return PinRecommendationResponse(
            success=True,
            data=None,
            message=f"No post-trade handoff recorded for order {order_id}",
        )
    return PinRecommendationResponse(
        success=True,
        data={
            "metadata": {
                "contract_version": handoff.metadata.contract_version,
                "source": handoff.metadata.source,
                "handoff_target": handoff.metadata.handoff_target,
                "generated_at": handoff.metadata.generated_at,
                "trace_id": handoff.metadata.trace_id,
                "origin_trace_id": handoff.metadata.origin_trace_id,
            },
            "order_id": handoff.order_id,
            "parent_execution_id": handoff.parent_execution_id,
            "broker": handoff.broker,
            "strategy": handoff.strategy,
            "asset_class": handoff.asset_class,
            "urgency": handoff.urgency,
            "route_ids": list(handoff.route_ids),
            "strategy_params": dict(handoff.strategy_params),
            "candidate_trace_id": handoff.candidate_trace_id,
        },
        message=f"Post-trade handoff trace_id={handoff.metadata.trace_id}",
    )


# ── Regime distribution (M1/M2 view) ──────────────────────────────────────────


@router.get("/api/costview/regime-distribution", response_model=RegimeDistributionResponse)
async def regime_distribution(
    start_date: str,
    end_date: str,
    regime_dim: str = "vol_regime",
):
    """Return per-day fill counts grouped by regime label."""
    if regime_dim not in {"vol_regime", "liq_regime", "trend_regime"}:
        raise HTTPException(status_code=400, detail=f"unsupported regime_dim: {regime_dim}")
    if not (len(start_date) == 10 and len(end_date) == 10):
        raise HTTPException(status_code=400, detail="dates must be ISO YYYY-MM-DD")

    try:
        rows_data = get_regime_distribution(
            start_date=start_date, end_date=end_date, regime_dim=regime_dim,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="regime.db not built yet")

    if not rows_data:
        return RegimeDistributionResponse(
            success=True, rows=[], regime_dim=regime_dim,
            config_version=None, start_date=start_date, end_date=end_date,
        )

    config_version = rows_data[0].get("config_version")
    out: list[RegimeDistributionRow] = []
    for row in rows_data:
        out.append(RegimeDistributionRow(
            date=row["date"],
            market_code=row["market_code"],
            low=row.get("low", 0),
            normal=row.get("normal", 0),
            high=row.get("high", 0),
            extreme=row.get("extreme", 0),
            none=row.get("none_count", 0),
            total=row.get("total", 0),
        ))
    return RegimeDistributionResponse(
        success=True, rows=out, regime_dim=regime_dim,
        config_version=config_version, start_date=start_date, end_date=end_date,
    )

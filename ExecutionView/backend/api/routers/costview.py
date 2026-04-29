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
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

# ── CostView sys.path setup ──────────────────────────────────────────────────
# __file__ = .../EMSX/ExecutionView/backend/api/routers/costview.py
# parents:  [0]=routers  [1]=api  [2]=backend  [3]=ExecutionView  [4]=EMSX root
_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # .../EMSX
_COSTVIEW_ROOT = _PROJECT_ROOT / "CostView"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from platform_data import TcaFilters, TcaReport, build_platform_data_access
from platform_data.adapters import (
    ScorecardCohortMetrics,
    ScorecardFilters,
    ScorecardReport,
)
from CostView.src.tca_query_service import SCORECARD_COHORTS

from ._pipeline_jobs import get_job, trigger_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(tags=["CostView TCA"])
platform_data = build_platform_data_access()


# ── Pydantic request/response models ─────────────────────────────────────────

class TcaFilterPayload(BaseModel):
    """Flexible filter input — all fields optional."""
    order_ids: Optional[list[str]] = Field(
        default=None,
        description="Specific order IDs to include",
        max_length=500,
    )
    algo: Optional[str] = Field(
        default=None, max_length=50,
        description="Algorithm name e.g. VWAP, TWAP, POV"
    )
    start_date: Optional[str] = Field(
        default=None, pattern=r"^\d{8}$",
        description="Start date YYYYMMDD"
    )
    end_date: Optional[str] = Field(
        default=None, pattern=r"^\d{8}$",
        description="End date YYYYMMDD"
    )
    broker: Optional[str] = Field(default=None, max_length=100)
    symbol: Optional[str] = Field(
        default=None, max_length=100,
        description="Bloomberg equity ticker e.g. AAPL US Equity"
    )

    @field_validator("order_ids")
    @classmethod
    def validate_order_ids(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None and len(v) > 500:
            raise ValueError("order_ids must not exceed 500 entries")
        return v


class TcaAnalyzeRequest(BaseModel):
    filters: TcaFilterPayload = Field(default_factory=TcaFilterPayload)
    aggregation: str = Field(
        default="per_order",
        pattern=r"^(per_order|aggregated)$",
    )
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class TcaAnalyzeResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    message: str = ""


class ScorecardRequest(BaseModel):
    """Broker/strategy cohort scorecard request."""
    cohort: str = Field(
        default="broker_strategy",
        description=f"Cohort dimension; one of {list(SCORECARD_COHORTS)}",
    )
    filters: TcaFilterPayload = Field(default_factory=TcaFilterPayload)
    min_sample_size: int = Field(default=10, ge=1, le=1000)
    max_orders: int = Field(default=2000, ge=1, le=10000)

    @field_validator("cohort")
    @classmethod
    def validate_cohort(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in SCORECARD_COHORTS:
            raise ValueError(
                f"cohort must be one of {list(SCORECARD_COHORTS)}"
            )
        return v


class ScorecardResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    message: str = ""


class TriggerUpdateResponse(BaseModel):
    job_id: str
    status: str
    message: str


class StageInfo(BaseModel):
    name: str        # "initialization" | "fill_fetch" | "processing" | "completion"
    label: str       # human-readable label
    progress: int = 0  # 0-100 within this stage


class UpdateStatusResponse(BaseModel):
    job_id: str
    status: str      # "started" | "running" | "completed" | "failed"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    stage: Optional[StageInfo] = None
    overall_progress: int = 0  # 0-100 across all stages
    last_activity_at: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/tca/analyze", response_model=TcaAnalyzeResponse)
async def analyze_tca(request: TcaAnalyzeRequest):
    """Run TCA analysis over the filtered order set.

    All metrics are derived from the local fill and BDIB SQLite databases.
    No Bloomberg or external API calls are made during this endpoint.

    Returns a structured report with per-order summaries and per-route details.
    If fill_bdib.db is empty (pipeline not yet run), returns a clear 503 with
    instructions to trigger an update.
    """
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
        report = platform_data.analytics.build_tca_report(filters)
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

    # Serialize dataclasses to dict
    report_dict = _serialize_report(report)
    return TcaAnalyzeResponse(
        success=True,
        data=report_dict,
        message=f"TCA report: {report.total_orders} orders matched",
    )


@router.post("/api/tca/scorecard", response_model=ScorecardResponse)
async def analyze_scorecard(request: ScorecardRequest):
    """Build a broker/strategy cohort scorecard.

    Aggregates per-order TCA metrics across the requested cohort dimension
    (broker, strategy, broker_strategy, asset_class, time_of_day,
    liquidity_adv20, or volatility). Cohorts with fewer than
    ``min_sample_size`` orders carry a sample_size_warning so the frontend
    can de-emphasize them rather than display unstable rankings.
    """
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
        report = platform_data.analytics.build_scorecard(filters)
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
        data=_serialize_scorecard(report),
        message=(
            f"Scorecard across {len(report.cohorts)} {request.cohort} cohort(s) "
            f"({report.total_orders_considered} orders)"
        ),
    )


@router.post("/api/tca/trigger-update", response_model=TriggerUpdateResponse)
async def trigger_update(request: Request):
    """[DEPRECATED ALIAS] Trigger the CostView daily update pipeline.

    Kept for backward compatibility with the CostView frontend. New callers
    should use ``POST /api/db/update`` (DatabaseView router). Both endpoints
    share the same in-memory job registry, so status polling works across
    either URL.

    Restricted to localhost to prevent unauthorized pipeline execution.
    """
    client_host = request.client.host if request.client else "unknown"
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            status_code=403,
            detail="Trigger endpoint is restricted to localhost",
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


# ─── WBS-08 handoff contract: CostView → ExecutionView ───────────────────────


class PinRecommendationRequest(BaseModel):
    cohort: str = Field(min_length=1, max_length=50)
    asset_class: Optional[str] = None
    broker: Optional[str] = None
    strategy: Optional[str] = None
    urgency: Optional[str] = None
    sample_size: int = Field(ge=0, le=1_000_000)
    arrival_bps: Optional[float] = None
    implementation_bps: Optional[float] = None
    severity: str = Field(default="normal")
    rationale: str = Field(default="", max_length=500)
    source_report_trace_id: Optional[str] = None


class PinRecommendationResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    message: str = ""


@router.post(
    "/api/tca/recommendations/pin",
    response_model=PinRecommendationResponse,
)
async def pin_broker_strategy_recommendation(request: PinRecommendationRequest):
    """Pin a CostView cohort conclusion as a recommendation for ExecutionView.

    ExecutionView reads pinned recommendations via
    GET /api/broker-recommendations. Keeping the publish endpoint here keeps
    write-ownership with the analytics domain.
    """
    from platform_data import get_shared_handoff_exchange

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


@router.get(
    "/api/tca/handoff/post-trade/{order_id}",
    response_model=PinRecommendationResponse,
)
async def get_post_trade_handoff(order_id: str):
    """Peek the ExecutionView → CostView post-trade handoff for a given order."""
    from platform_data import get_shared_handoff_exchange

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

class RegimeDistributionRow(BaseModel):
    """One row per (date, market_code)."""
    date: str
    market_code: str
    low: int = 0
    normal: int = 0
    high: int = 0
    extreme: int = 0
    none: int = 0
    total: int = 0


class RegimeDistributionResponse(BaseModel):
    success: bool
    rows: list[RegimeDistributionRow]
    regime_dim: str
    config_version: Optional[str] = None
    start_date: str
    end_date: str


@router.get("/api/costview/regime-distribution", response_model=RegimeDistributionResponse)
async def regime_distribution(
    start_date: str,
    end_date: str,
    regime_dim: str = "vol_regime",
):
    """Return per-day fill counts grouped by regime label.

    Reads CostView/data/regime.db (active config) and aggregates
    `fill_regime_labels` over [start_date, end_date].
    """
    if regime_dim not in {"vol_regime", "liq_regime", "trend_regime"}:
        raise HTTPException(status_code=400, detail=f"unsupported regime_dim: {regime_dim}")
    if not (len(start_date) == 10 and len(end_date) == 10):
        raise HTTPException(status_code=400, detail="dates must be ISO YYYY-MM-DD")

    import sqlite3
    db_path = _COSTVIEW_ROOT / "data" / "regime.db"
    if not db_path.exists():
        raise HTTPException(status_code=503, detail="regime.db not built yet")

    conn = sqlite3.connect(str(db_path))
    try:
        cfg_row = conn.execute(
            "SELECT version_id FROM audit_regime_config_versions WHERE is_active=1 LIMIT 1"
        ).fetchone()
        cfg_version = cfg_row[0] if cfg_row else None
        if cfg_version is None:
            return RegimeDistributionResponse(
                success=True, rows=[], regime_dim=regime_dim,
                config_version=None, start_date=start_date, end_date=end_date,
            )
        # COALESCE empty regime to 'none' bucket
        sql = f"""
            SELECT trade_date AS date, market_code,
                   COALESCE({regime_dim}, 'none') AS regime, COUNT(*) AS n
            FROM fill_regime_labels
            WHERE config_version = ?
              AND trade_date BETWEEN ? AND ?
            GROUP BY trade_date, market_code, COALESCE({regime_dim}, 'none')
            ORDER BY trade_date, market_code
        """
        cur = conn.execute(sql, (cfg_version, start_date, end_date))
        rows_raw = cur.fetchall()
    finally:
        conn.close()

    grouped: dict[tuple[str, str], dict[str, int]] = {}
    for d, mc, regime, n in rows_raw:
        key = (d, mc)
        bucket = grouped.setdefault(key, {})
        bucket[str(regime)] = int(n)

    out: list[RegimeDistributionRow] = []
    for (d, mc), counts in grouped.items():
        total = sum(counts.values())
        out.append(RegimeDistributionRow(
            date=d, market_code=mc,
            low=counts.get("low", 0),
            normal=counts.get("normal", 0),
            high=counts.get("high", 0),
            extreme=counts.get("extreme", 0),
            none=counts.get("none", 0),
            total=total,
        ))
    return RegimeDistributionResponse(
        success=True, rows=out, regime_dim=regime_dim,
        config_version=cfg_version, start_date=start_date, end_date=end_date,
    )


# ── Pipeline runner ────────────────────────────────────────────────────────────
#
# The pipeline job registry and subprocess runner live in
# routers/_pipeline_jobs.py so that both /api/tca/trigger-update (this router,
# deprecated alias) and /api/db/update (DatabaseView router) share state.


# ── Serialization helpers ─────────────────────────────────────────────────────

def _serialize_report(report: TcaReport) -> dict:
    """Convert TcaReport dataclass tree to a JSON-safe dict."""
    return {
        "filters": report.filters,
        "total_orders": report.total_orders,
        "offset": report.offset,
        "limit": report.limit,
        "generated_at": report.generated_at,
        "orders": [
            {
                "order_id": o.order_id,
                "order_as_of_date": o.order_as_of_date,
                "equ_ticker": o.equ_ticker,
                "side": o.side,
                "algo": o.algo,
                "start_time": o.start_time,
                "end_time": o.end_time,
                "fill_pct": o.fill_pct,
                "exec_price": o.exec_price,
                "interval_vwap": o.interval_vwap,
                "tracking_error_bps": o.tracking_error_bps,
                "volume_pct_interval": o.volume_pct_interval,
                "volume_pct_adv5": o.volume_pct_adv5,
                "volume_pct_adv20": o.volume_pct_adv20,
                "daily_volatility": o.daily_volatility,
                "intraday_volatility": o.intraday_volatility,
                "price_movement_pct": o.price_movement_pct,
                "data_quality_warning": o.data_quality_warning,
                "routes": [
                    {
                        "order_id": r.order_id,
                        "route_id": r.route_id,
                        "order_as_of_date": r.order_as_of_date,
                        "broker": r.broker,
                        "side": r.side,
                        "start_time": r.start_time,
                        "end_time": r.end_time,
                        "fill_pct": r.fill_pct,
                        "exec_price": r.exec_price,
                        "interval_vwap": r.interval_vwap,
                        "tracking_error_bps": r.tracking_error_bps,
                        "volume_pct_interval": r.volume_pct_interval,
                        "time_series": r.time_series,
                    }
                    for r in o.routes
                ],
            }
            for o in report.orders
        ],
    }


def _serialize_scorecard(report: ScorecardReport) -> dict:
    """Convert ScorecardReport dataclass tree to a JSON-safe dict."""
    return {
        "filters": report.filters,
        "cohort": report.cohort,
        "min_sample_size": report.min_sample_size,
        "total_orders_considered": report.total_orders_considered,
        "total_orders_capped": report.total_orders_capped,
        "generated_at": report.generated_at,
        "data_source_warning": report.data_source_warning,
        "cohorts": [
            {
                "cohort_key": c.cohort_key,
                "cohort_label": c.cohort_label,
                "sample_size": c.sample_size,
                "order_count": c.order_count,
                "avg_tracking_error_bps": c.avg_tracking_error_bps,
                "median_tracking_error_bps": c.median_tracking_error_bps,
                "p95_tracking_error_bps": c.p95_tracking_error_bps,
                "stddev_tracking_error_bps": c.stddev_tracking_error_bps,
                "avg_fill_pct": c.avg_fill_pct,
                "avg_volume_pct_interval": c.avg_volume_pct_interval,
                "avg_volume_pct_adv20": c.avg_volume_pct_adv20,
                "avg_daily_volatility": c.avg_daily_volatility,
                "avg_intraday_volatility": c.avg_intraday_volatility,
                "avg_price_movement_pct": c.avg_price_movement_pct,
                "data_quality_ratio": c.data_quality_ratio,
                "sample_size_warning": c.sample_size_warning,
                "anomaly_flags": list(c.anomaly_flags),
            }
            for c in report.cohorts
        ],
    }

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
import subprocess
import sys
import threading
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

logger = logging.getLogger(__name__)
router = APIRouter(tags=["CostView TCA"])
platform_data = build_platform_data_access()

# ── In-memory job registry (process-lifetime only) ───────────────────────────
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


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
    """Manually trigger the CostView daily update pipeline.

    Idempotent: if a job is already running, returns the existing job_id
    instead of spawning a duplicate. This allows frontend reconnection
    after a page refresh or module switch.

    Restricted to requests originating from localhost to prevent
    unauthorized pipeline execution.
    """
    # Localhost guard
    client_host = request.client.host if request.client else "unknown"
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            status_code=403,
            detail="Trigger endpoint is restricted to localhost",
        )

    # ── Idempotent check: return existing active job if any ────────────────
    with _jobs_lock:
        for existing_id, existing_job in _jobs.items():
            if existing_job.get("status") in ("started", "running"):
                logger.info(
                    f"Returning existing active job {existing_id} "
                    f"(status={existing_job['status']}) "
                    "instead of spawning a new one"
                )
                return TriggerUpdateResponse(
                    job_id=existing_id,
                    status=existing_job["status"],
                    message="Pipeline already running — returning existing job",
                )

    # No active job → create new one
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "started",
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "error": None,
            "stage": {"name": "initialization", "label": "Initialization", "progress": 0},
            "overall_progress": 0,
            "last_activity_at": datetime.now().isoformat(),
        }

    # Launch subprocess in a daemon thread so the endpoint returns immediately
    threading.Thread(
        target=_run_pipeline_subprocess,
        args=(job_id,),
        daemon=True,
    ).start()

    logger.info(f"Pipeline triggered: job_id={job_id}")
    return TriggerUpdateResponse(
        job_id=job_id,
        status="started",
        message="Daily update pipeline started. Poll /api/tca/update-status/{job_id} for progress.",
    )


@router.get("/api/tca/update-status/{job_id}", response_model=UpdateStatusResponse)
async def get_update_status(job_id: str):
    """Poll the status of a triggered pipeline job."""
    with _jobs_lock:
        job = _jobs.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return UpdateStatusResponse(
        job_id=job_id,
        status=job["status"],
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        error=job.get("error"),
        stage=StageInfo(**job["stage"]) if job.get("stage") else None,
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


# ── Pipeline runner ────────────────────────────────────────────────────────────

# ── Stage definitions (must match daily_update.py STAGE_MARKERS) ──────────────

_PIPELINE_STAGES = [
    {"name": "initialization", "label": "Initialization"},
    {"name": "fill_fetch",     "label": "Fill Fetch"},
    {"name": "processing",     "label": "Processing"},
    {"name": "completion",     "label": "Completion"},
]

_STAGE_WEIGHTS = {  # relative weight for overall progress calculation
    "initialization": 10,
    "fill_fetch":     35,
    "processing":     45,
    "completion":     10,
}

_STAGE_PREFIX = "[STAGE]"  # marker prefix from daily_update.py stdout


def _compute_progress(stage_name: str, stage_pct: int) -> int:
    """Compute overall 0-100 progress given current stage + its internal pct."""
    stage_names = [stage["name"] for stage in _PIPELINE_STAGES]
    try:
        current_index = stage_names.index(stage_name)
    except ValueError:
        current_index = 0

    prior = sum(
        _STAGE_WEIGHTS.get(_PIPELINE_STAGES[index]["name"], 0)
        for index in range(current_index)
    )
    return min(100, prior + int(_STAGE_WEIGHTS.get(stage_name, 0) * stage_pct / 100))


def _mark_job_activity(job_id: str) -> None:
    if job_id in _jobs:
        _jobs[job_id]["last_activity_at"] = datetime.now().isoformat()


def _parse_stage_line(line: str):
    """Parse a [STAGE] line from subprocess stdout.
    Expected format: [STAGE] <stage_name> <progress_pct>
    Returns (stage_name, progress_pct) or None.
    """
    line = line.strip()
    if not line.startswith(_STAGE_PREFIX):
        return None
    parts = line[len(_STAGE_PREFIX):].strip().split()
    if len(parts) >= 2:
        try:
            return parts[0], min(100, max(0, int(parts[1])))
        except ValueError:
            return parts[0], 0
    elif len(parts) == 1:
        return parts[0], 0
    return None


def _run_pipeline_subprocess(job_id: str) -> None:
    """Execute daily_update.py --once as a subprocess and update job status with stage info."""
    daily_update_script = _COSTVIEW_ROOT / "scripts" / "daily_update.py"

    # Transition to running with initial stage
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["stage"] = {"name": "initialization", "label": "Initialization", "progress": 0}
            _jobs[job_id]["overall_progress"] = 0
            _mark_job_activity(job_id)

    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(daily_update_script), "--once"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,     # merge into stdout — avoid pipe deadlock
            text=True,
        )

        # Real-time line parsing for stage updates
        while True:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if not line:
                continue

            parsed = _parse_stage_line(line)
            if parsed:
                stage_name, stage_pct = parsed
                label = next((s["label"] for s in _PIPELINE_STAGES if s["name"] == stage_name), stage_name)
                overall = _compute_progress(stage_name, stage_pct)
                with _jobs_lock:
                    if job_id in _jobs:
                        _jobs[job_id]["stage"] = {"name": stage_name, "label": label, "progress": stage_pct}
                        _jobs[job_id]["overall_progress"] = overall
                        _mark_job_activity(job_id)
            else:
                with _jobs_lock:
                    if job_id in _jobs:
                        _mark_job_activity(job_id)

        output, _ = proc.communicate(timeout=60)
        status = "completed" if proc.returncode == 0 else "failed"
        # Capture last 2KB of combined stdout+stderr for error diagnostics
        error = None
        if proc.returncode != 0 and output:
            lines = output.strip().splitlines()
            error_lines = [l for l in lines if not l.startswith(_STAGE_PREFIX)]
            error = "\n".join(error_lines[-20:]) if error_lines else output[-2000:]

    except subprocess.TimeoutExpired:
        proc.kill() if 'proc' in dir() else None
        status = "failed"
        error = "Pipeline timed out after 3600 seconds"
    except Exception as exc:
        status = "failed"
        error = str(exc)

    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = status
            _jobs[job_id]["completed_at"] = datetime.now().isoformat()
            _jobs[job_id]["error"] = error
            _mark_job_activity(job_id)
            if status == "completed":
                _jobs[job_id]["overall_progress"] = 100
                _jobs[job_id]["stage"] = {
                    "name": "completion", "label": "Completion", "progress": 100,
                }

    logger.info(f"Pipeline job {job_id} finished: {status}")


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

"""DatabaseView router — /api/db/* endpoints.

Exposes read-only diagnostic statistics over the CostView SQLite files and
a single "trigger increment update" action. No destructive operations
(vacuum / delete / backfill) are exposed; backfill remains CLI-only per
the iteration plan.

Endpoints
---------
GET    /api/db/overview                 — all databases + headline stats
GET    /api/db/{key}/summary            — per-table date coverage + per-date row counts
GET    /api/db/{key}/integrity          — lightweight, bounded integrity checks
POST   /api/db/update                   — trigger the daily update pipeline (localhost only)
GET    /api/db/update-status/{job_id}   — poll a triggered pipeline job
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

# ── sys.path setup (mirrors routers/costview.py) ─────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # .../EMSX
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from platform_data import repositories as repo  # noqa: E402

from ._pipeline_jobs import get_job, trigger_pipeline  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(tags=["DatabaseView"])


# ── Response models (thin; payload shapes come from repositories dataclasses) ─

class OverviewItem(BaseModel):
    key: str
    label: str
    path: str
    description: str
    exists: bool
    size_bytes: int
    last_modified: Optional[str] = None
    wal_active: bool = False
    table_count: int = 0
    total_rows: int = 0
    latest_trade_date: Optional[str] = None
    earliest_trade_date: Optional[str] = None
    distinct_trade_dates: int = 0
    health: str = "unknown"


class OverviewResponse(BaseModel):
    success: bool = True
    items: list[OverviewItem]


class DateRowCountModel(BaseModel):
    trade_date: str
    row_count: int


class TableSummaryModel(BaseModel):
    name: str
    description: str
    primary_key: Optional[str] = None
    date_column: Optional[str] = None
    row_count: int
    latest_trade_date: Optional[str] = None
    earliest_trade_date: Optional[str] = None
    distinct_trade_dates: int = 0
    per_date_counts: list[DateRowCountModel] = Field(default_factory=list)


class SummaryResponse(BaseModel):
    success: bool = True
    key: str
    label: str
    path: str
    exists: bool
    size_bytes: int
    last_modified: Optional[str] = None
    description: str
    tables: list[TableSummaryModel]


class IntegrityIssueModel(BaseModel):
    code: str
    severity: str
    message: str
    count: int = 0


class IntegrityResponse(BaseModel):
    success: bool = True
    key: str
    checked_at: str
    issues: list[IntegrityIssueModel]


class TriggerUpdateResponse(BaseModel):
    success: bool = True
    job_id: str
    status: str
    message: str


class StageInfoModel(BaseModel):
    name: str
    label: str
    progress: int = 0


class UpdateStatusResponse(BaseModel):
    success: bool = True
    job_id: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    stage: Optional[StageInfoModel] = None
    overall_progress: int = 0
    last_activity_at: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/db/overview", response_model=OverviewResponse)
async def get_database_overview() -> OverviewResponse:
    """Cheap overview of every registered database.

    Uses index-based fast counts / endpoint MIN-MAX on date columns, so this
    endpoint returns in O(tens of ms) even when the underlying databases are
    multi-GB. Distinct-date counts are deferred to /summary.
    """
    overviews = repo.get_overview()
    items = [OverviewItem(**ov.to_dict()) for ov in overviews]
    return OverviewResponse(items=items)


@router.get("/api/db/{key}/summary", response_model=SummaryResponse)
async def get_database_summary(key: str, date_limit: int = 800) -> SummaryResponse:
    """Per-table date-coverage statistics (driver of the frontend heatmap)."""
    if key not in repo.list_database_keys():
        raise HTTPException(status_code=404, detail=f"Unknown database key: {key}")
    summary = repo.get_summary(key, date_limit=date_limit)
    return SummaryResponse(**summary.to_dict())


@router.get("/api/db/{key}/integrity", response_model=IntegrityResponse)
async def get_database_integrity(key: str) -> IntegrityResponse:
    """Bounded integrity check (recent-window scans only)."""
    if key not in repo.list_database_keys():
        raise HTTPException(status_code=404, detail=f"Unknown database key: {key}")
    integrity = repo.get_integrity(key)
    return IntegrityResponse(**integrity.to_dict())


@router.post("/api/db/update", response_model=TriggerUpdateResponse)
async def trigger_database_update(request: Request) -> TriggerUpdateResponse:
    """Trigger the daily incremental update pipeline.

    Restricted to localhost callers (matches the existing /api/tca/trigger-update
    behaviour). Idempotent: returns the existing job if one is already active.
    Backfill remains CLI-only and is not exposed here.
    """
    client_host = request.client.host if request.client else "unknown"
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            status_code=403,
            detail="Update endpoint is restricted to localhost",
        )
    result = trigger_pipeline(client_host)
    return TriggerUpdateResponse(**result)


@router.get("/api/db/update-status/{job_id}", response_model=UpdateStatusResponse)
async def get_database_update_status(job_id: str) -> UpdateStatusResponse:
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
        stage=StageInfoModel(**stage) if stage else None,
        overall_progress=job.get("overall_progress", 0),
        last_activity_at=job.get("last_activity_at"),
    )

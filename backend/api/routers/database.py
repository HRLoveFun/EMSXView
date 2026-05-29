"""DatabaseView router — /api/db/* endpoints.

Exposes read-only diagnostic statistics over the CostView SQLite files and
a single "trigger increment update" action. No destructive operations
(vacuum / delete / backfill) are exposed; backfill remains CLI-only per
the iteration plan.

Endpoints
---------
GET    /api/db/overview                          — all databases + headline stats
GET    /api/db/{key}/summary                     — per-table date coverage + per-date row counts
GET    /api/db/{key}/integrity                   — lightweight, bounded integrity checks
GET    /api/db/{key}/tables/{table}/schema       — column + index metadata for one table
GET    /api/db/{key}/tables/{table}/sample       — most recent rows (≤ 200) of one table
POST   /api/db/update                            — trigger the daily update pipeline (localhost only)
GET    /api/db/update-status/{job_id}            — poll a triggered pipeline job
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from platform_data import database_diagnostics as repo  # noqa: E402

from platform_data.pipeline_jobs import get_job, trigger_pipeline  # noqa: E402

# A2: Inject DataPipeline ConnectionManager into diagnostics module at import time.
# This replaces the former ``from DataPipeline import ConnectionManager`` lazy
# import inside database_diagnostics._get_db_paths().
try:
    from DataPipeline import ConnectionManager
    repo.init_diagnostics_db(ConnectionManager())
except ImportError:
    pass  # DataPipeline not available (e.g. in test environment)

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


class ColumnInfoModel(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: int = 0
    default_value: Optional[str] = None


class IndexInfoModel(BaseModel):
    name: str
    unique: bool
    columns: list[str] = Field(default_factory=list)


class SchemaResponse(BaseModel):
    success: bool = True
    database_key: str
    table: str
    description: str
    primary_key_display: Optional[str] = None
    columns: list[ColumnInfoModel] = Field(default_factory=list)
    indexes: list[IndexInfoModel] = Field(default_factory=list)


class ColumnAnomalyModel(BaseModel):
    column: str
    severity: str
    code: str
    message: str


class SampleResponse(BaseModel):
    success: bool = True
    database_key: str
    table: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)
    row_count_estimate: int = 0
    fetched_at: str
    order_by: Optional[str] = None
    anomalies: list[ColumnAnomalyModel] = Field(default_factory=list)


class TriggerUpdateResponse(BaseModel):
    success: bool = True
    job_id: str
    status: str
    message: str


class StageInfoModel(BaseModel):
    name: str
    label: str
    progress: int = 0
    detail: Optional[str] = None


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


@router.get(
    "/api/db/{key}/tables/{table}/schema",
    response_model=SchemaResponse,
)
async def get_table_schema(key: str, table: str) -> SchemaResponse:
    """Return column / index metadata for a registered table.

    Both `key` and `table` are validated against the static registry; any
    unknown identifier is rejected with 404 before reaching SQL.
    """
    if key not in repo.list_database_keys():
        raise HTTPException(status_code=404, detail=f"Unknown database key: {key}")
    if table not in repo.list_tables(key):
        raise HTTPException(
            status_code=404,
            detail=f"Unknown table '{table}' for database '{key}'",
        )
    schema = repo.get_schema(key, table)
    return SchemaResponse(**schema.to_dict())


@router.get(
    "/api/db/{key}/tables/{table}/sample",
    response_model=SampleResponse,
)
async def get_table_sample(
    key: str, table: str, limit: int = 50
) -> SampleResponse:
    """Return the most recent rows of a registered table (≤ 200)."""
    if key not in repo.list_database_keys():
        raise HTTPException(status_code=404, detail=f"Unknown database key: {key}")
    if table not in repo.list_tables(key):
        raise HTTPException(
            status_code=404,
            detail=f"Unknown table '{table}' for database '{key}'",
        )
    if limit < 1:
        raise HTTPException(
            status_code=400, detail="limit must be ≥ 1"
        )
    sample = repo.get_sample(key, table, limit=limit)
    return SampleResponse(**sample.to_dict())



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

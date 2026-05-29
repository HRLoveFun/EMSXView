"""Read-only execution history router backed by ExecutionHistoryQueryService."""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from platform_data.adapters import (
    ExecutionHistoryFillRow,
    ExecutionHistoryFillSnapshot,
    ExecutionHistoryOrderSummaryRow,
    ExecutionHistoryOrderSummarySnapshot,
    ExecutionHistoryRouteSummaryRow,
    ExecutionHistoryRouteSummarySnapshot,
)
from platform_data.execution_history_service import ExecutionHistoryQueryService
from schemas import (
    ExecutionHistoryFillData,
    ExecutionHistoryFillResponse,
    ExecutionHistoryOrderSummaryData,
    ExecutionHistoryOrderSummaryResponse,
    ExecutionHistoryRouteSummaryData,
    ExecutionHistoryRouteSummaryResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Execution History"])

# Lazy-init ExecutionHistoryQueryService with ConnectionManager injected.
_execution_history: ExecutionHistoryQueryService | None = None


def _get_execution_history() -> ExecutionHistoryQueryService:
    """Lazily create ExecutionHistoryQueryService with ConnectionManager injected."""
    global _execution_history
    if _execution_history is None:
        from DataPipeline import ConnectionManager
        _execution_history = ExecutionHistoryQueryService(connection_manager=ConnectionManager())
    return _execution_history


# ── Row projection helpers (replacing ExecutionHistoryAdapter's _project_row) ──

def _build_fill_snapshot(
    raw: list[dict[str, Any]],
    start_date: str | None,
    end_date: str | None,
) -> ExecutionHistoryFillSnapshot:
    rows = [_project_into(ExecutionHistoryFillRow, r) for r in raw]
    return ExecutionHistoryFillSnapshot(
        start_date=start_date,
        end_date=end_date,
        row_count=len(rows),
        rows=rows,
    )


def _build_order_summary_snapshot(
    raw: list[dict[str, Any]],
    start_date: str | None,
    end_date: str | None,
) -> ExecutionHistoryOrderSummarySnapshot:
    rows = [_project_into(ExecutionHistoryOrderSummaryRow, r) for r in raw]
    return ExecutionHistoryOrderSummarySnapshot(
        start_date=start_date,
        end_date=end_date,
        row_count=len(rows),
        rows=rows,
    )


def _build_route_summary_snapshot(
    raw: list[dict[str, Any]],
    start_date: str | None,
    end_date: str | None,
) -> ExecutionHistoryRouteSummarySnapshot:
    rows = [_project_into(ExecutionHistoryRouteSummaryRow, r) for r in raw]
    return ExecutionHistoryRouteSummarySnapshot(
        start_date=start_date,
        end_date=end_date,
        row_count=len(rows),
        rows=rows,
    )


def _project_into(dataclass_type: type, row: dict[str, Any]) -> Any:
    """Project a dict onto the fields of a dataclass (ignoring extras)."""
    allowed = {f for f in dataclass_type.__dataclass_fields__}
    projected = {k: v for k, v in row.items() if k in allowed}
    for key in ("order_id", "route_id", "fill_id"):
        if key in projected and projected[key] is not None:
            projected[key] = str(projected[key])
    return dataclass_type(**projected)


@router.get("/api/execution-history/fills", response_model=ExecutionHistoryFillResponse)
async def get_fill_history(
    order_id: str | None = Query(default=None),
    route_id: str | None = Query(default=None),
    start_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    end_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    _validate_date_window(start_date, end_date)
    try:
        raw = _get_execution_history().list_fill_history(
            limit=limit,
            order_id=order_id,
            route_id=route_id,
            start_date=start_date,
            end_date=end_date,
        )
        snapshot = _build_fill_snapshot(raw, start_date, end_date)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"Execution history store not found: {exc}")
    except Exception as exc:
        logger.error("Execution history fills query failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Execution history query error: {exc}")

    return ExecutionHistoryFillResponse(
        success=True,
        data=ExecutionHistoryFillData(**asdict(snapshot)),
        message=f"Execution history fills: {snapshot.row_count} rows matched",
    )


@router.get("/api/execution-history/orders", response_model=ExecutionHistoryOrderSummaryResponse)
async def get_order_history(
    order_id: str | None = Query(default=None),
    start_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    end_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    _validate_date_window(start_date, end_date)
    try:
        raw = _get_execution_history().list_order_history(
            limit=limit,
            order_id=order_id,
            start_date=start_date,
            end_date=end_date,
        )
        snapshot = _build_order_summary_snapshot(raw, start_date, end_date)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"Execution history store not found: {exc}")
    except Exception as exc:
        logger.error("Execution history orders query failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Execution history query error: {exc}")

    return ExecutionHistoryOrderSummaryResponse(
        success=True,
        data=ExecutionHistoryOrderSummaryData(**asdict(snapshot)),
        message=f"Execution history orders: {snapshot.row_count} rows matched",
    )


@router.get("/api/execution-history/routes", response_model=ExecutionHistoryRouteSummaryResponse)
async def get_route_history(
    order_id: str | None = Query(default=None),
    route_id: str | None = Query(default=None),
    start_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    end_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    _validate_date_window(start_date, end_date)
    try:
        raw = _get_execution_history().list_route_history(
            limit=limit,
            order_id=order_id,
            route_id=route_id,
            start_date=start_date,
            end_date=end_date,
        )
        snapshot = _build_route_summary_snapshot(raw, start_date, end_date)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"Execution history store not found: {exc}")
    except Exception as exc:
        logger.error("Execution history routes query failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Execution history query error: {exc}")

    return ExecutionHistoryRouteSummaryResponse(
        success=True,
        data=ExecutionHistoryRouteSummaryData(**asdict(snapshot)),
        message=f"Execution history routes: {snapshot.row_count} rows matched",
    )


def _validate_date_window(start_date: str | None, end_date: str | None) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be <= end_date")
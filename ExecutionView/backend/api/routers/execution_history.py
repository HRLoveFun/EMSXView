"""Read-only execution history router backed by platform_data.execution_history."""

from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from platform_data import build_platform_data_access
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
platform_data = build_platform_data_access()


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
        snapshot = platform_data.execution_history.list_fill_history(
            limit=limit,
            order_id=order_id,
            route_id=route_id,
            start_date=start_date,
            end_date=end_date,
        )
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
        snapshot = platform_data.execution_history.list_order_history(
            limit=limit,
            order_id=order_id,
            start_date=start_date,
            end_date=end_date,
        )
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
        snapshot = platform_data.execution_history.list_route_history(
            limit=limit,
            order_id=order_id,
            route_id=route_id,
            start_date=start_date,
            end_date=end_date,
        )
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
"""Connection domain router — /api/connection/*, /api/health, root."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends

from schemas import ApiResponse
from deps import verify_token, get_bloomberg_service
from config import settings
from db import check_database_connection

router = APIRouter(tags=["Connection"])

# Reconnect rate limiter: at most one background reconnect attempt per 30s.
_last_reconnect_ts: float = 0.0


@router.get("/", tags=["Health"])
async def root(bloomberg=Depends(get_bloomberg_service)):
    """API root — service info."""
    return {
        "service": "EMSXView Trading API",
        "version": "1.0.0",
        "status": "running",
        "bloomberg": bloomberg.get_status().model_dump(),
    }


@router.get("/api/health", response_model=ApiResponse, tags=["Health"])
async def health_check(bloomberg=Depends(get_bloomberg_service)):
    """Health check endpoint."""
    bb_status = bloomberg.get_status()
    if settings.ENABLE_DB_PERSISTENCE:
        db_connected, db_message = await check_database_connection()
        db_status = "connected" if db_connected else "disconnected"
    else:
        db_connected = True
        db_message = "DB persistence disabled"
        db_status = "disabled"
    healthy = bb_status.status == "connected" and db_connected
    return ApiResponse(
        success=healthy,
        data={
            "bloomberg": bb_status.model_dump(),
            "database": {"status": db_status, "message": db_message},
        },
        message="Service is healthy" if healthy else f"bloomberg={bb_status.status}, database={db_status}",
    )


@router.get("/api/connection", response_model=ApiResponse)
async def get_connection_status(
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Get Bloomberg connection status."""
    bb_status = bloomberg.get_status()
    return ApiResponse(success=True, data={"status": bb_status.status}, message=f"Bloomberg is {bb_status.status}")


@router.get("/api/startup-status", response_model=ApiResponse)
async def get_startup_status(
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Get layered startup status for backend, Bloomberg, and EMSX subscriptions.
    Fires a background reconnect if Bloomberg is disconnected (rate-limited to
    once per 30s) so the system self-heals without waiting for a user action."""
    global _last_reconnect_ts
    if not bloomberg.connected:
        now = time.monotonic()
        if now - _last_reconnect_ts > 30:
            _last_reconnect_ts = now
            asyncio.create_task(bloomberg.connect())
    status = bloomberg.get_startup_status()
    return ApiResponse(success=True, data=status.model_dump(), message=status.message)


@router.post("/api/connection/reconnect", response_model=ApiResponse)
async def reconnect_bloomberg(
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Force reconnection to Bloomberg."""
    from fastapi import HTTPException
    bloomberg.disconnect()
    connected = await bloomberg.connect()
    if connected:
        return ApiResponse(success=True, message="Reconnected to Bloomberg")
    raise HTTPException(503, "Failed to reconnect to Bloomberg")

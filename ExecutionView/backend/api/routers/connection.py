"""Connection domain router — /api/connection/*, /api/health, root."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from schemas import ApiResponse
from deps import verify_token, get_bloomberg
from config import settings
from db import check_database_connection

router = APIRouter(tags=["Connection"])


@router.get("/", tags=["Health"])
async def root():
    """API root — service info."""
    return {
        "service": "EMSX Trading API",
        "version": "1.0.0",
        "status": "running",
        "bloomberg": get_bloomberg().get_status().model_dump(),
    }


@router.get("/api/health", response_model=ApiResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    bb_status = get_bloomberg().get_status()
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
async def get_connection_status(user: dict = Depends(verify_token)):
    """Get Bloomberg connection status."""
    bb_status = get_bloomberg().get_status()
    return ApiResponse(success=True, data={"status": bb_status.status}, message=f"Bloomberg is {bb_status.status}")


@router.get("/api/startup-status", response_model=ApiResponse)
async def get_startup_status(user: dict = Depends(verify_token)):
    """Get layered startup status for backend, Bloomberg, and EMSX subscriptions."""
    status = get_bloomberg().get_startup_status()
    return ApiResponse(success=True, data=status.model_dump(), message=status.message)


@router.post("/api/connection/reconnect", response_model=ApiResponse)
async def reconnect_bloomberg(user: dict = Depends(verify_token)):
    """Force reconnection to Bloomberg."""
    from fastapi import HTTPException
    bb = get_bloomberg()
    bb.disconnect()
    connected = await bb.connect()
    if connected:
        return ApiResponse(success=True, message="Reconnected to Bloomberg")
    raise HTTPException(503, "Failed to reconnect to Bloomberg")

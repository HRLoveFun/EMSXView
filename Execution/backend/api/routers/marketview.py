"""MarketView router — lightweight pre-trade market snapshot endpoints."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from platform_data import MarketSnapshot, build_platform_data_access

router = APIRouter(tags=["MarketView"])
platform_data = build_platform_data_access()


class MarketSnapshotRowResponse(BaseModel):
    equ_ticker: str
    trade_date: str
    daily_close: Optional[float] = None
    daily_volatility: Optional[float] = None
    intraday_volatility: Optional[float] = None
    total_volume: Optional[float] = None
    adv_5d: Optional[float] = None
    adv_20d: Optional[float] = None


class MarketSnapshotPayload(BaseModel):
    trade_date: Optional[str] = None
    row_count: int
    rows: list[MarketSnapshotRowResponse]


class MarketSnapshotEnvelope(BaseModel):
    success: bool
    data: MarketSnapshotPayload
    message: str = ""


@router.get("/api/marketview/snapshot", response_model=MarketSnapshotEnvelope)
async def get_market_snapshot(
    limit: int = Query(default=25, ge=1, le=100),
    trade_date: Optional[str] = Query(default=None, pattern=r"^\d{8}$"),
):
    try:
        snapshot = platform_data.market.get_market_snapshot(limit=limit, trade_date=trade_date)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"MarketView snapshot error: {exc}")

    payload = _serialize_snapshot(snapshot)
    message = (
        f"Market snapshot for {payload.trade_date}: {payload.row_count} instruments"
        if payload.trade_date
        else "Market snapshot unavailable — no daily summary data yet"
    )
    return MarketSnapshotEnvelope(success=True, data=payload, message=message)


def _serialize_snapshot(snapshot: MarketSnapshot) -> MarketSnapshotPayload:
    return MarketSnapshotPayload(
        trade_date=snapshot.trade_date,
        row_count=snapshot.row_count,
        rows=[MarketSnapshotRowResponse(**row.__dict__) for row in snapshot.rows],
    )
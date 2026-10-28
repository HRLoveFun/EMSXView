"""执行区间量价端点（057 DL-30）——GET /api/execution/interval-series。

区间由调用方按订单创建/开始与结束时刻传入；服务端只读 bar、按桶聚合，
缺 bar 的桶显式返回 `is_gap=True`，不插值。鉴权与审计基线遵循 A04/A05。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import verify_token
from schemas import ApiResponse
from services.interval_series import (
    BUCKET_OPTIONS,
    IntervalPoint,
    IntervalSeries,
    load_interval_series,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Execution"])

_TIME_PATTERN = r"^\d{2}:\d{2}(:\d{2})?$"


class IntervalPointResponse(BaseModel):
    bucket_start: str
    bucket_end: str
    price: Optional[float] = None
    vwap: Optional[float] = None
    volume: float = 0.0
    cum_volume: float = 0.0
    is_gap: bool = True


class IntervalSeriesPayload(BaseModel):
    equ_ticker: str
    trade_date: str
    start: str
    end: str
    bucket_minutes: int
    source: str
    points: list[IntervalPointResponse] = Field(default_factory=list)
    interval_vwap: Optional[float] = None
    total_volume: float = 0.0
    bar_count: int = 0
    gap_buckets: int = 0
    generated_at: str = ""


def _serialize(series: IntervalSeries) -> IntervalSeriesPayload:
    return IntervalSeriesPayload(
        equ_ticker=series.equ_ticker,
        trade_date=series.trade_date,
        start=series.start,
        end=series.end,
        bucket_minutes=series.bucket_minutes,
        source=series.source,
        points=[IntervalPointResponse(**point.__dict__) for point in series.points],
        interval_vwap=series.interval_vwap,
        total_volume=series.total_volume,
        bar_count=series.bar_count,
        gap_buckets=series.gap_buckets,
        generated_at=series.generated_at,
    )


@router.get("/api/execution/interval-series", response_model=ApiResponse)
async def get_interval_series(
    equ_ticker: str = Query(..., min_length=1, max_length=64),
    trade_date: str = Query(..., pattern=r"^\d{8}$"),
    start: str = Query(..., pattern=_TIME_PATTERN),
    end: str = Query(..., pattern=_TIME_PATTERN),
    bucket_minutes: int = Query(default=5),
    user: dict = Depends(verify_token),
) -> ApiResponse:
    """按 ticker + 执行区间返回价格/累计量/区间 VWAP；无 bar 显式 gap。"""
    if bucket_minutes not in BUCKET_OPTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"bucket_minutes must be one of {list(BUCKET_OPTIONS)}",
        )
    try:
        series = load_interval_series(equ_ticker, trade_date, start, end, bucket_minutes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # 取数失败不伪装成空序列
        logger.exception("interval series failed")
        raise HTTPException(status_code=500, detail=f"Interval series error: {exc}")

    payload = _serialize(series)
    return ApiResponse(
        success=True,
        data=payload.model_dump(),
        message=(
            f"{series.equ_ticker} {series.start}-{series.end}: "
            f"{series.bar_count} bars, {series.gap_buckets} gap bucket(s)"
        ),
    )

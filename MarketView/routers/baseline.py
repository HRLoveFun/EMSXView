"""日度基线端点（057 DL-10）——GET /api/marketview/daily-baseline。

逐票 60 日稳健分布特征（MarketBaseline契约）；只读，无 Bloomberg 依赖。
tickers 逗号分隔；未配置/无数据的股票以 n_days=0 + 全 None 字段返回（不静默丢弃）。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from platform_data.adapters import DailyBaselineAdapter
from platform_data.contracts import BASELINE_SCHEMA_VERSION, BASELINE_WINDOW_DAYS, MarketBaseline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["MarketView"])

_baseline: DailyBaselineAdapter | None = None


def _get_baseline() -> DailyBaselineAdapter:
    """懒加载单例（测试经 monkeypatch 替换，同 marketview 路由模式）。"""
    global _baseline
    if _baseline is None:
        _baseline = DailyBaselineAdapter()
    return _baseline


class MarketBaselineResponse(BaseModel):
    equ_ticker: str
    as_of: str
    log_volume_z: Optional[float] = None
    vol_percentile: Optional[float] = None
    intraday_vol_percentile: Optional[float] = None
    overnight_gap_sigma: Optional[float] = None
    auction_open_pct: Optional[float] = None
    auction_close_pct: Optional[float] = None
    adv5_adv60_ratio: Optional[float] = None
    spread_proxy_bps: Optional[float] = None
    n_days: int
    excluded_dates: list[str] = Field(default_factory=list)
    schema_version: str


class DailyBaselinePayload(BaseModel):
    as_of: Optional[str] = None
    window_days: int
    schema_version: str
    baselines: list[MarketBaselineResponse] = Field(default_factory=list)


class DailyBaselineEnvelope(BaseModel):
    success: bool
    data: DailyBaselinePayload
    message: str = ""


def _serialize(baseline: MarketBaseline) -> MarketBaselineResponse:
    return MarketBaselineResponse(
        equ_ticker=baseline.equ_ticker,
        as_of=baseline.as_of,
        log_volume_z=baseline.log_volume_z,
        vol_percentile=baseline.vol_percentile,
        intraday_vol_percentile=baseline.intraday_vol_percentile,
        overnight_gap_sigma=baseline.overnight_gap_sigma,
        auction_open_pct=baseline.auction_open_pct,
        auction_close_pct=baseline.auction_close_pct,
        adv5_adv60_ratio=baseline.adv5_adv60_ratio,
        spread_proxy_bps=baseline.spread_proxy_bps,
        n_days=baseline.n_days,
        excluded_dates=list(baseline.excluded_dates),
        schema_version=baseline.schema_version,
    )


@router.get("/api/marketview/daily-baseline", response_model=DailyBaselineEnvelope)
async def get_daily_baseline(
    tickers: str = Query(..., description="逗号分隔的 equ_ticker；建议每批 ≤100（access-guide 点查上限）"),
    as_of: Optional[str] = Query(default=None, pattern=r"^\d{8}$"),
):
    try:
        ticker_list = [part.strip() for part in tickers.split(",") if part.strip()]
        if not ticker_list:
            raise HTTPException(status_code=400, detail="tickers must include at least one value")
        baselines = _get_baseline().get_baseline(ticker_list, as_of=as_of)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("daily baseline failed")
        raise HTTPException(status_code=500, detail=f"Daily baseline error: {exc}")

    payload = DailyBaselinePayload(
        as_of=next((b.as_of for b in baselines if b.as_of), None),
        window_days=BASELINE_WINDOW_DAYS,
        schema_version=BASELINE_SCHEMA_VERSION,
        baselines=[_serialize(b) for b in baselines],
    )
    with_data = sum(1 for b in baselines if b.n_days > 0)
    return DailyBaselineEnvelope(
        success=True,
        data=payload,
        message=f"Daily baseline for {len(baselines)} ticker(s): {with_data} with data (window {BASELINE_WINDOW_DAYS}d)",
    )

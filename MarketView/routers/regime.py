"""市场级状态端点（057 DL-11）——GET /api/marketview/market-regime。

日级三状态（流动性/波动/趋势）+ 当日窗口内宏观事件；只读 regime.db。
无数据的市场不出现在结果中（缺口可见，不静默填常态）。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from platform_data.adapters import EventRegimeAdapter
from platform_data.contracts import REGIME_SCHEMA_VERSION, MarketRegimeState

logger = logging.getLogger(__name__)

router = APIRouter(tags=["MarketView"])

_events: EventRegimeAdapter | None = None


def _get_events() -> EventRegimeAdapter:
    """懒加载单例（测试经 monkeypatch 替换，同 marketview/baseline 路由模式）。"""
    global _events
    if _events is None:
        _events = EventRegimeAdapter()
    return _events


class EventFlagResponse(BaseModel):
    code: str
    severity: str
    window_days: int
    source: str
    evidence: Optional[str] = None


class MarketRegimeStateResponse(BaseModel):
    market_code: str
    as_of: str
    liq_regime: Optional[str] = None
    vol_regime: Optional[str] = None
    trend_regime: Optional[str] = None
    macro_events: list[EventFlagResponse] = Field(default_factory=list)
    config_version: Optional[str] = None
    schema_version: str


class MarketRegimePayload(BaseModel):
    as_of: Optional[str] = None
    schema_version: str
    requested: list[str] = Field(default_factory=list)
    states: list[MarketRegimeStateResponse] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class MarketRegimeEnvelope(BaseModel):
    success: bool
    data: MarketRegimePayload
    message: str = ""


def _serialize(state: MarketRegimeState) -> MarketRegimeStateResponse:
    return MarketRegimeStateResponse(
        market_code=state.market_code,
        as_of=state.as_of,
        liq_regime=state.liq_regime,
        vol_regime=state.vol_regime,
        trend_regime=state.trend_regime,
        macro_events=[
            EventFlagResponse(
                code=e.code,
                severity=e.severity,
                window_days=e.window_days,
                source=e.source,
                evidence=e.evidence,
            )
            for e in state.macro_events
        ],
        config_version=state.config_version,
        schema_version=state.schema_version,
    )


@router.get("/api/marketview/market-regime", response_model=MarketRegimeEnvelope)
async def get_market_regime(
    markets: str = Query(..., description="逗号分隔的市场码（如 US,JP,EU；regime 库 23 市场）"),
    as_of: Optional[str] = Query(default=None, pattern=r"^\d{8}$"),
):
    try:
        market_list = [part.strip().upper() for part in markets.split(",") if part.strip()]
        if not market_list:
            raise HTTPException(status_code=400, detail="markets must include at least one value")
        states = _get_events().get_market_states(market_list, as_of=as_of)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("market regime failed")
        raise HTTPException(status_code=500, detail=f"Market regime error: {exc}")

    found = {s.market_code for s in states}
    missing = [m for m in market_list if m not in found]
    payload = MarketRegimePayload(
        as_of=next((s.as_of for s in states if s.as_of), None),
        schema_version=REGIME_SCHEMA_VERSION,
        requested=market_list,
        states=[_serialize(s) for s in states],
        missing=missing,
    )
    return MarketRegimeEnvelope(
        success=True,
        data=payload,
        message=f"Market regime for {len(states)}/{len(market_list)} market(s)"
        + (f"; missing: {','.join(missing)}" if missing else ""),
    )

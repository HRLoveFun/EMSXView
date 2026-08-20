"""Handoff (WBS-08) Pydantic schemas — cross-module request/response models.

Phase B2: Extracted from schemas/marketview.py. Handoff models are used by both
MarketView (standalone service) and ExecutionView (backend/api/routers/orders_handoff.py),
so they reside here rather than in either module's router.

See docs/spec/data-domain.md for WBS-08 contract specification.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Shared metadata model (contracts 1-3) ───────────────────────────────────


class HandoffMetadataResponse(BaseModel):
    """Shared handoff metadata model (WBS-08 contracts 1-3).

    Used by both MarketView → Execution handoff and Execution → CostView handoff.
    """
    contract_version: str
    source: str
    handoff_target: str
    generated_at: str
    trace_id: str
    origin_trace_id: Optional[str] = None


# ── Market → Execution handoff (contract 1) ─────────────────────────────────

# Lightweight candidate row (avoids depending on schemas/marketview.py).
from platform_data.adapters import MarketCandidatePayload, MarketCandidateRow


class MarketCandidateRowResponse(BaseModel):
    equ_ticker: str
    trade_date: str
    daily_close: Optional[float] = None
    total_volume: Optional[float] = None
    adv_20d: Optional[float] = None
    daily_volatility: Optional[float] = None
    intraday_volatility: Optional[float] = None
    liquidity_alert: str
    volatility_alert: str


class MarketCandidatePayloadResponse(BaseModel):
    source: str
    handoff_target: str
    trade_date: Optional[str] = None
    pool_id: str
    pool_label: Optional[str] = None
    row_count: int
    candidates: list[MarketCandidateRowResponse] = Field(default_factory=list)


class MarketToExecutionHandoffPayload(BaseModel):
    metadata: HandoffMetadataResponse
    trade_date: Optional[str] = None
    pool_id: str
    pool_label: Optional[str] = None
    candidate_payload: MarketCandidatePayloadResponse
    execution_hint: dict = Field(default_factory=dict)


class MarketToExecutionHandoffEnvelope(BaseModel):
    success: bool
    data: Optional[MarketToExecutionHandoffPayload] = None
    message: str = ""


class MarketToExecutionPublishRequest(BaseModel):
    """Used by MarketView standalone service to publish handoff candidates."""
    pool_id: str = "all"
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    tickers: Optional[list[str]] = None
    execution_hint: dict = Field(default_factory=dict)
    limit: int = Field(default=40, ge=1, le=100)


# ── Execution → CostView handoff (contract 2) ────────────────────────────────


class PostTradeHandoffRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    parent_execution_id: Optional[str] = Field(default=None, max_length=64)
    broker: Optional[str] = Field(default=None, max_length=64)
    strategy: Optional[str] = Field(default=None, max_length=64)
    asset_class: Optional[str] = Field(default=None, max_length=32)
    urgency: Optional[str] = Field(default=None, max_length=32)
    route_ids: list[str] = Field(default_factory=list, max_length=1000)
    strategy_params: dict = Field(default_factory=dict)
    candidate_trace_id: Optional[str] = Field(default=None, max_length=128)

    @field_validator("route_ids")
    @classmethod
    def _validate_route_ids(cls, v: list[str]) -> list[str]:
        for rid in v:
            if len(rid) > 64:
                raise ValueError("route_id 长度超限 (max 64)")
        return v

    @field_validator("strategy_params")
    @classmethod
    def _validate_strategy_params(cls, v: dict) -> dict:
        # 防护: 跨模块载荷大小上限 64KB, 防止无界 dict 撑爆内存/日志
        try:
            size = len(json.dumps(v, default=str))
        except (TypeError, ValueError):
            raise ValueError("strategy_params 无法序列化")
        if size > 64 * 1024:
            raise ValueError("strategy_params 大小超限 (max 64KB)")
        return v


class PostTradeHandoffPayload(BaseModel):
    metadata: HandoffMetadataResponse
    order_id: str
    parent_execution_id: Optional[str] = None
    broker: Optional[str] = None
    strategy: Optional[str] = None
    asset_class: Optional[str] = None
    urgency: Optional[str] = None
    route_ids: list[str] = Field(default_factory=list)
    strategy_params: dict = Field(default_factory=dict)
    candidate_trace_id: Optional[str] = None


class PostTradeHandoffResponse(BaseModel):
    success: bool
    data: Optional[PostTradeHandoffPayload] = None
    message: str = ""

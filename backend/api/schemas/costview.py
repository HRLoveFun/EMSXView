"""CostView TCA schemas — request/response models and serialization helpers.

Extracted from routers/costview.py to keep the router focused on endpoint
logic only. See P2 refactoring plan.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from platform_data.adapters import ScorecardReport, TcaReport
from platform_data.contracts import SCORECARD_COHORTS

# ── Pydantic request/response models ─────────────────────────────────────────


class TcaFilterPayload(BaseModel):
    """Flexible filter input — all fields optional."""

    order_ids: Optional[list[str]] = Field(
        default=None, description="Specific order IDs to include", max_length=500
    )
    algo: Optional[str] = Field(
        default=None, max_length=50, description="Algorithm name e.g. VWAP, TWAP, POV"
    )
    start_date: Optional[str] = Field(
        default=None, pattern=r"^\d{8}$", description="Start date YYYYMMDD"
    )
    end_date: Optional[str] = Field(
        default=None, pattern=r"^\d{8}$", description="End date YYYYMMDD"
    )
    broker: Optional[str] = Field(default=None, max_length=100)
    symbol: Optional[str] = Field(
        default=None, max_length=100,
        description="Bloomberg equity ticker e.g. AAPL US Equity",
    )

    @field_validator("order_ids")
    @classmethod
    def validate_order_ids(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None and len(v) > 500:
            raise ValueError("order_ids must not exceed 500 entries")
        return v


class TcaAnalyzeRequest(BaseModel):
    filters: TcaFilterPayload = Field(default_factory=TcaFilterPayload)
    aggregation: str = Field(default="per_order", pattern=r"^(per_order|aggregated)$")
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class TcaAnalyzeResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    message: str = ""


class ScorecardRequest(BaseModel):
    """Broker/strategy cohort scorecard request."""

    cohort: str = Field(
        default="broker_strategy",
        description=f"Cohort dimension; one of {list(SCORECARD_COHORTS)}",
    )
    filters: TcaFilterPayload = Field(default_factory=TcaFilterPayload)
    min_sample_size: int = Field(default=10, ge=1, le=1000)
    max_orders: int = Field(default=2000, ge=1, le=10000)

    @field_validator("cohort")
    @classmethod
    def validate_cohort(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in SCORECARD_COHORTS:
            raise ValueError(f"cohort must be one of {list(SCORECARD_COHORTS)}")
        return v


class ScorecardResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    message: str = ""


class TriggerUpdateResponse(BaseModel):
    job_id: str
    status: str
    message: str


class StageInfo(BaseModel):
    name: str  # "initialization" | "fill_fetch" | "processing" | "completion"
    label: str  # human-readable label
    progress: int = 0  # 0-100 within this stage
    detail: Optional[str] = None


class UpdateStatusResponse(BaseModel):
    job_id: str
    status: str  # "started" | "running" | "completed" | "failed"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    stage: Optional[StageInfo] = None
    overall_progress: int = 0  # 0-100 across all stages
    last_activity_at: Optional[str] = None


class PinRecommendationRequest(BaseModel):
    cohort: str = Field(min_length=1, max_length=50)
    asset_class: Optional[str] = None
    broker: Optional[str] = None
    strategy: Optional[str] = None
    urgency: Optional[str] = None
    sample_size: int = Field(ge=0, le=1_000_000)
    arrival_bps: Optional[float] = None
    implementation_bps: Optional[float] = None
    severity: str = Field(default="normal")
    rationale: str = Field(default="", max_length=500)
    source_report_trace_id: Optional[str] = None


class PinRecommendationResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    message: str = ""


class RegimeDistributionRow(BaseModel):
    """One row per (date, market_code)."""

    date: str
    market_code: str
    low: int = 0
    normal: int = 0
    high: int = 0
    extreme: int = 0
    none: int = 0
    total: int = 0


class RegimeDistributionResponse(BaseModel):
    success: bool
    rows: list[RegimeDistributionRow]
    regime_dim: str
    config_version: Optional[str] = None
    start_date: str
    end_date: str


# ── Serialization helpers ─────────────────────────────────────────────────────


def serialize_report(report: TcaReport) -> dict:
    """Convert TcaReport dataclass tree to a JSON-safe dict."""
    return {
        "filters": report.filters,
        "total_orders": report.total_orders,
        "offset": report.offset,
        "limit": report.limit,
        "generated_at": report.generated_at,
        "orders": [
            {
                "order_id": o.order_id,
                "order_as_of_date": o.order_as_of_date,
                "equ_ticker": o.equ_ticker,
                "side": o.side,
                "algo": o.algo,
                "start_time": o.start_time,
                "end_time": o.end_time,
                "fill_pct": o.fill_pct,
                "exec_price": o.exec_price,
                "interval_vwap": o.interval_vwap,
                "tracking_error_bps": o.tracking_error_bps,
                "volume_pct_interval": o.volume_pct_interval,
                "volume_pct_adv5": o.volume_pct_adv5,
                "volume_pct_adv20": o.volume_pct_adv20,
                "daily_volatility": o.daily_volatility,
                "intraday_volatility": o.intraday_volatility,
                "price_movement_pct": o.price_movement_pct,
                "data_quality_warning": o.data_quality_warning,
                "routes": [
                    {
                        "order_id": r.order_id,
                        "route_id": r.route_id,
                        "order_as_of_date": r.order_as_of_date,
                        "broker": r.broker,
                        "side": r.side,
                        "start_time": r.start_time,
                        "end_time": r.end_time,
                        "fill_pct": r.fill_pct,
                        "exec_price": r.exec_price,
                        "interval_vwap": r.interval_vwap,
                        "tracking_error_bps": r.tracking_error_bps,
                        "volume_pct_interval": r.volume_pct_interval,
                        "time_series": r.time_series,
                    }
                    for r in o.routes
                ],
            }
            for o in report.orders
        ],
    }


def serialize_scorecard(report: ScorecardReport) -> dict:
    """Convert ScorecardReport dataclass tree to a JSON-safe dict."""
    return {
        "filters": report.filters,
        "cohort": report.cohort,
        "min_sample_size": report.min_sample_size,
        "total_orders_considered": report.total_orders_considered,
        "total_orders_capped": report.total_orders_capped,
        "generated_at": report.generated_at,
        "data_source_warning": report.data_source_warning,
        "cohorts": [
            {
                "cohort_key": c.cohort_key,
                "cohort_label": c.cohort_label,
                "sample_size": c.sample_size,
                "order_count": c.order_count,
                "avg_tracking_error_bps": c.avg_tracking_error_bps,
                "median_tracking_error_bps": c.median_tracking_error_bps,
                "p95_tracking_error_bps": c.p95_tracking_error_bps,
                "stddev_tracking_error_bps": c.stddev_tracking_error_bps,
                "avg_fill_pct": c.avg_fill_pct,
                "avg_volume_pct_interval": c.avg_volume_pct_interval,
                "avg_volume_pct_adv20": c.avg_volume_pct_adv20,
                "avg_daily_volatility": c.avg_daily_volatility,
                "avg_intraday_volatility": c.avg_intraday_volatility,
                "avg_price_movement_pct": c.avg_price_movement_pct,
                "data_quality_ratio": c.data_quality_ratio,
                "sample_size_warning": c.sample_size_warning,
                "anomaly_flags": list(c.anomaly_flags),
            }
            for c in report.cohorts
        ],
    }

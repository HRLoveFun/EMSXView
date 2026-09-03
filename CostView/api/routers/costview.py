"""
CostView TCA router — /api/tca/* endpoints.

Provides:
  POST /api/tca/analyze          — run TCA analysis with optional filters
  POST /api/tca/trigger-update   — manually start the daily update pipeline
  GET  /api/tca/update-status/{job_id}  — poll a triggered update job

Data constraint: ALL metrics are derived exclusively from
processed_fills.db, fill_bdib.db, raw_bdib.db, and raw_fills.db.
No external API calls are made during analysis.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from platform_data.adapters import (
    ScorecardCohortMetrics,
    ScorecardFilters,
    ScorecardReport,
    TcaFilters,
    TcaOrderAggregate,
    TcaReport,
    TcaRouteSummary,
)
from platform_data.contracts import SCORECARD_COHORTS
from platform_data.regime_query import get_regime_distribution
from CostView.src.tca_query_service import TcaQueryService
from CostView.src.tca_utils import filters_to_dict as _filters_to_dict
from CostView.src.tca_utils import resolve_date_defaults



logger = logging.getLogger(__name__)
router = APIRouter(tags=["CostView TCA"])
_analytics = TcaQueryService()


# ── Pydantic request/response models ─────────────────────────────────────────

class TcaFilterPayload(BaseModel):
    """Flexible filter input — all fields optional."""
    order_ids: Optional[list[str]] = Field(
        default=None,
        description="Specific order IDs to include",
        max_length=500,
    )
    algo: Optional[str] = Field(
        default=None, max_length=50,
        description="Algorithm name e.g. VWAP, TWAP, POV"
    )
    start_date: Optional[str] = Field(
        default=None, pattern=r"^\d{8}$",
        description="Start date YYYYMMDD"
    )
    end_date: Optional[str] = Field(
        default=None, pattern=r"^\d{8}$",
        description="End date YYYYMMDD"
    )
    broker: Optional[str] = Field(default=None, max_length=100)
    symbol: Optional[str] = Field(
        default=None, max_length=100,
        description="Bloomberg equity ticker e.g. AAPL US Equity"
    )

    @field_validator("order_ids")
    @classmethod
    def validate_order_ids(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None and len(v) > 500:
            raise ValueError("order_ids must not exceed 500 entries")
        return v


class TcaAnalyzeRequest(BaseModel):
    filters: TcaFilterPayload = Field(default_factory=TcaFilterPayload)
    aggregation: str = Field(
        default="per_order",
        pattern=r"^(per_order|aggregated)$",
    )
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
            raise ValueError(
                f"cohort must be one of {list(SCORECARD_COHORTS)}"
            )
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
    name: str        # "initialization" | "fill_fetch" | "processing" | "completion"
    label: str       # human-readable label
    progress: int = 0  # 0-100 within this stage
    detail: Optional[str] = None  # freeform detail (e.g. "Day 3/7: 2026-04-29 — 1245 rows, upserted 1245")


class UpdateStatusResponse(BaseModel):
    job_id: str
    status: str      # "started" | "running" | "completed" | "failed"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    stage: Optional[StageInfo] = None
    overall_progress: int = 0  # 0-100 across all stages
    last_activity_at: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

_LOCALHOST_HOSTS = ("127.0.0.1", "::1", "localhost")


def _default_query_date(f: TcaFilterPayload) -> Optional[str]:
    """仅当请求未显式指定日期/订单时，返回默认目标日期（上一工作日）。

    显式给出过滤条件的查询不做自动跑数探测。
    """
    if f.start_date or f.end_date or f.order_ids:
        return None
    resolved = resolve_date_defaults(TcaFilters())
    return resolved.start_date


@router.post("/api/tca/analyze", response_model=TcaAnalyzeResponse)
async def analyze_tca(request: TcaAnalyzeRequest, raw_request: Request):
    """Run TCA analysis over the filtered order set.

    All metrics are derived from the local fill and BDIB SQLite databases.
    No Bloomberg or external API calls are made during this endpoint.

    Returns a structured report with flat per-route summaries (34 fields each).
    未显式指定日期且默认日期（上一工作日）数据未生成时返回 503 提示：
    数据更新维护已迁独立项目 EMSXDataPipeline，请通过其 Runner 触发。
    """

    f = request.filters
    default_date = _default_query_date(f)
    if default_date and not _analytics.has_data_for_date(default_date):
        raise HTTPException(
            status_code=503,
            detail=(
                f"{default_date} 数据尚未生成。数据更新维护已迁独立项目 "
                "EMSXDataPipeline；请通过其 Runner（POST /run）触发后再查询。"
            ),
        )
    filters = TcaFilters(
        order_ids=f.order_ids,
        algo=f.algo,
        start_date=f.start_date,
        end_date=f.end_date,
        broker=f.broker,
        symbol=f.symbol,
        aggregation=request.aggregation,
        limit=request.limit,
        offset=request.offset,
    )

    try:
        report = _analytics.build_tca_report(filters)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"CostView database not found: {exc}. Run the data pipeline first.",
        )
    except Exception as exc:
        logger.error(f"TCA analysis failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TCA analysis error: {exc}")

    if report.data_source_warning:
        raise HTTPException(status_code=503, detail=report.data_source_warning)

    # Serialize dataclasses to dict
    report_dict = _serialize_report(report)
    return TcaAnalyzeResponse(
        success=True,
        data=report_dict,
        message=f"TCA report: {report.total_orders} routes matched",
    )


@router.post("/api/tca/analyze-orders", response_model=TcaAnalyzeResponse)
async def analyze_tca_orders(request: TcaAnalyzeRequest):
    """Run TCA analysis aggregated at order level (003-tca-core-benchmarks).

    Aggregates per-route TCA metrics to order level via the documented
    aggregation strategy (SUM for currency costs, turnover-weighted for
    bps, first-route for price benchmarks, etc.). Gated by
    TCA_ORDER_AGG_ENABLED — when disabled returns empty orders.
    """
    f = request.filters
    filters = TcaFilters(
        order_ids=f.order_ids,
        algo=f.algo,
        start_date=f.start_date,
        end_date=f.end_date,
        broker=f.broker,
        symbol=f.symbol,
        aggregation="aggregated",
        limit=request.limit,
        offset=request.offset,
    )

    try:
        aggregates = _analytics.build_order_report(filters)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"CostView database not found: {exc}. Run the data pipeline first.",
        )
    except Exception as exc:
        logger.error(f"TCA order aggregation failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TCA order aggregation error: {exc}")

    return TcaAnalyzeResponse(
        success=True,
        data={
            "filters": _filters_to_dict(filters),
            "total_orders": len(aggregates),
            "offset": request.offset,
            "limit": request.limit,
            "generated_at": datetime.now().isoformat(),
            "orders": [_serialize_order_aggregate(a) for a in aggregates],
        },
        message=f"TCA order report: {len(aggregates)} orders matched",
    )



@router.post("/api/tca/scorecard", response_model=ScorecardResponse)
async def analyze_scorecard(request: ScorecardRequest):
    """Build a broker/strategy cohort scorecard.

    Aggregates per-route TCA metrics across the requested cohort dimension
    (broker, strategy, broker_strategy, asset_class, time_of_day,
    liquidity_adv20, or volatility). Cohorts with fewer than
    ``min_sample_size`` routes carry a sample_size_warning so the frontend
    can de-emphasize them rather than display unstable rankings.
    """

    f = request.filters
    filters = ScorecardFilters(
        cohort=request.cohort,
        order_ids=f.order_ids,
        algo=f.algo,
        start_date=f.start_date,
        end_date=f.end_date,
        broker=f.broker,
        symbol=f.symbol,
        min_sample_size=request.min_sample_size,
        max_orders=request.max_orders,
    )
    try:
        report = _analytics.build_scorecard(filters)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"CostView database not found: {exc}. Run the data pipeline first.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Scorecard analysis failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scorecard error: {exc}")

    if report.data_source_warning and not report.cohorts:
        raise HTTPException(status_code=503, detail=report.data_source_warning)

    return ScorecardResponse(
        success=True,
        data=_serialize_scorecard(report),
        message=(
            f"Scorecard across {len(report.cohorts)} {request.cohort} cohort(s) "
            f"({report.total_orders_considered} routes)"
        ),
    )



# ─── WBS-08 handoff contract: CostView → ExecutionView ───────────────────────


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


@router.post(
    "/api/tca/recommendations/pin",
    response_model=PinRecommendationResponse,
)
async def pin_broker_strategy_recommendation(request: PinRecommendationRequest):
    """Pin a CostView cohort conclusion as a recommendation for ExecutionView.

    ExecutionView reads pinned recommendations via
    GET /api/broker-recommendations. Keeping the publish endpoint here keeps
    write-ownership with the analytics domain.
    """
    from platform_data import get_shared_handoff_exchange

    rec = get_shared_handoff_exchange().publish_cost_to_execution(
        cohort=request.cohort,
        asset_class=request.asset_class,
        broker=request.broker,
        strategy=request.strategy,
        urgency=request.urgency,
        sample_size=request.sample_size,
        arrival_bps=request.arrival_bps,
        implementation_bps=request.implementation_bps,
        severity=request.severity,
        rationale=request.rationale,
        source_report_trace_id=request.source_report_trace_id,
    )
    return PinRecommendationResponse(
        success=True,
        data={
            "metadata": {
                "contract_version": rec.metadata.contract_version,
                "source": rec.metadata.source,
                "handoff_target": rec.metadata.handoff_target,
                "generated_at": rec.metadata.generated_at,
                "trace_id": rec.metadata.trace_id,
            },
            "cohort": rec.cohort,
            "broker": rec.broker,
            "strategy": rec.strategy,
            "severity": rec.severity,
        },
        message=f"Pinned recommendation (trace_id={rec.metadata.trace_id})",
    )


@router.get(
    "/api/tca/handoff/post-trade/{order_id}",
    response_model=PinRecommendationResponse,
)
async def get_post_trade_handoff(order_id: str):
    """Peek the ExecutionView → CostView post-trade handoff for a given order."""
    from platform_data import get_shared_handoff_exchange

    handoff = get_shared_handoff_exchange().get_execution_to_cost(order_id)
    if handoff is None:
        return PinRecommendationResponse(
            success=True,
            data=None,
            message=f"No post-trade handoff recorded for order {order_id}",
        )
    return PinRecommendationResponse(
        success=True,
        data={
            "metadata": {
                "contract_version": handoff.metadata.contract_version,
                "source": handoff.metadata.source,
                "handoff_target": handoff.metadata.handoff_target,
                "generated_at": handoff.metadata.generated_at,
                "trace_id": handoff.metadata.trace_id,
                "origin_trace_id": handoff.metadata.origin_trace_id,
            },
            "order_id": handoff.order_id,
            "parent_execution_id": handoff.parent_execution_id,
            "broker": handoff.broker,
            "strategy": handoff.strategy,
            "asset_class": handoff.asset_class,
            "urgency": handoff.urgency,
            "route_ids": list(handoff.route_ids),
            "strategy_params": dict(handoff.strategy_params),
            "candidate_trace_id": handoff.candidate_trace_id,
        },
        message=f"Post-trade handoff trace_id={handoff.metadata.trace_id}",
    )


# ── Regime distribution (M1/M2 view) ──────────────────────────────────────────

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


@router.get("/api/costview/regime-distribution", response_model=RegimeDistributionResponse)
async def regime_distribution(
    start_date: str,
    end_date: str,
    regime_dim: str = "vol_regime",
):
    """Return per-day fill counts grouped by regime label.

    Reads CostView/data/regime.db (active config) and aggregates
    `fill_regime_labels` over [start_date, end_date].
    """
    if regime_dim not in {"vol_regime", "liq_regime", "trend_regime"}:
        raise HTTPException(status_code=400, detail=f"unsupported regime_dim: {regime_dim}")
    if not (len(start_date) == 10 and len(end_date) == 10):
        raise HTTPException(status_code=400, detail="dates must be ISO YYYY-MM-DD")

    try:
        from data_access import ConnectionManager
        rows_data = get_regime_distribution(
            start_date=start_date,
            end_date=end_date,
            regime_dim=regime_dim,
            connection_manager=ConnectionManager(),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="regime.db not built yet")

    if not rows_data:
        return RegimeDistributionResponse(
            success=True, rows=[], regime_dim=regime_dim,
            config_version=None, start_date=start_date, end_date=end_date,
        )

    config_version = rows_data[0].get("config_version")
    out: list[RegimeDistributionRow] = []
    for row in rows_data:
        out.append(RegimeDistributionRow(
            date=row["date"],
            market_code=row["market_code"],
            low=row.get("low", 0),
            normal=row.get("normal", 0),
            high=row.get("high", 0),
            extreme=row.get("extreme", 0),
            none=row.get("none_count", 0),
            total=row.get("total", 0),
        ))
    return RegimeDistributionResponse(
        success=True, rows=out, regime_dim=regime_dim,
        config_version=config_version, start_date=start_date, end_date=end_date,
    )


# ── Pipeline runner ────────────────────────────────────────────────────────────
#
# The pipeline job registry and subprocess runner live in
# platform_data/pipeline_jobs.py so that both /api/tca/trigger-update (this router,
# deprecated alias) and /api/db/update (DatabaseView router) share state.


# ── Serialization helpers ─────────────────────────────────────────────────────

def _serialize_report(report: TcaReport) -> dict:
    """Convert TcaReport dataclass tree to a JSON-safe flat per-route dict."""
    return {
        "filters": report.filters,
        "total_orders": report.total_orders,
        "offset": report.offset,
        "limit": report.limit,
        "generated_at": report.generated_at,
        "orders": [_serialize_route(r) for r in report.orders],
    }


def _serialize_route(route: TcaRouteSummary) -> dict:
    """Serialize one TcaRouteSummary to a dict with snake_case keys."""
    return {
        # 源值
        "order_id": route.OrderId,
        "route_id": route.RouteId,
        "order_as_of_date": route.order_as_of_date,
        "exchange": route.Exchange,
        "account": route.Account,
        "equ_ticker": route.equ_ticker,
        "currency": route.Currency,
        "side": route.Side,
        "amount": route.Amount,
        "route_shares": route.RouteShares,
        "type": route.Type,
        "limit_price": route.LimitPrice,
        "stop_price": route.StopPrice,
        "broker": route.Broker,
        "strategy_type": route.StrategyType,
        "algo": route.algo,
        "trader_name": route.TraderName,
        # 计算指标
        "fill": route.fill,
        "fill_continuous": route.fill_continuous,
        "fill_close": route.fill_close,
        "par_rate": route.par_rate,
        "par_rate_continuous": route.par_rate_continuous,
        "par_rate_close": route.par_rate_close,
        "p_avg": route.p_avg,
        "p_avg_continuous": route.p_avg_continuous,
        "pnl_vwap": route.pnl_vwap,
        "pnl_vwap_continuous": route.pnl_vwap_continuous,
        "rpm": route.RPM,
        "rpm_continuous": route.RPM_continuous,
        "pwp_5": route.pwp_5,
        "pwp_10": route.pwp_10,
        "pwp_15": route.pwp_15,
        "pwp_20": route.pwp_20,
        "pwp_25": route.pwp_25,
        # 003-tca-core-benchmarks: Phase 0 核心基准
        "p_arrival": route.p_arrival,
        "p_close": route.p_close,
        "arrival_cost_bps": route.arrival_cost_bps,
        "close_cost_bps": route.close_cost_bps,
        "opportunity_cost": route.opportunity_cost,
        # 003-tca-core-benchmarks: Phase 1 Wagner IS / 风险 / 冲击
        "p_decision": route.p_decision,
        "delay_cost": route.delay_cost,
        "trading_cost": route.trading_cost,
        "wagner_is": route.wagner_is,
        "wagner_is_bps": route.wagner_is_bps,
        "cost_stddev": route.cost_stddev,
        "cost_p95": route.cost_p95,
        "cost_cvar": route.cost_cvar,
        "order_duration_sec": route.order_duration_sec,
        "exec_rate_shares_per_min": route.exec_rate_shares_per_min,
        "temp_impact_5min_bps": route.temp_impact_5min_bps,
        "temp_impact_10min_bps": route.temp_impact_10min_bps,
        "temp_impact_30min_bps": route.temp_impact_30min_bps,
        "perm_impact_bps": route.perm_impact_bps,
        "recovery_truncated": route.recovery_truncated,
        # 时序数据
        "time_series": route.time_series,
    }


def _serialize_order_aggregate(order: TcaOrderAggregate) -> dict:
    """Serialize one TcaOrderAggregate to a dict with snake_case keys.

    003-tca-core-benchmarks: order 级 TCA 汇总序列化（route 聚合）。
    """
    return {
        "order_id": order.OrderId,
        "order_as_of_date": order.order_as_of_date,
        "equ_ticker": order.equ_ticker,
        "exchange": order.Exchange,
        "side": order.Side,
        "broker": order.Broker,
        "algo": order.algo,
        "trader_name": order.TraderName,
        "route_count": order.route_count,
        "fill_count": order.fill_count,
        "delay_cost": order.delay_cost,
        "trading_cost": order.trading_cost,
        "opportunity_cost": order.opportunity_cost,
        "wagner_is": order.wagner_is,
        "p_arrival": order.p_arrival,
        "p_decision": order.p_decision,
        "p_close": order.p_close,
        "arrival_cost_bps": order.arrival_cost_bps,
        "close_cost_bps": order.close_cost_bps,
        "wagner_is_bps": order.wagner_is_bps,
        "temp_impact_5min_bps": order.temp_impact_5min_bps,
        "temp_impact_10min_bps": order.temp_impact_10min_bps,
        "temp_impact_30min_bps": order.temp_impact_30min_bps,
        "perm_impact_bps": order.perm_impact_bps,
        "fill": order.fill,
        "route_shares": order.route_shares,
        "par_rate": order.par_rate,
        "cost_stddev": order.cost_stddev,
        "cost_p95": order.cost_p95,
        "cost_cvar": order.cost_cvar,
        "order_duration_sec": order.order_duration_sec,
        "exec_rate_shares_per_min": order.exec_rate_shares_per_min,
        "recovery_truncated": order.recovery_truncated,
    }



def _serialize_scorecard(report: ScorecardReport) -> dict:
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

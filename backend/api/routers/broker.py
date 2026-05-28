"""Broker domain router — /api/broker-*, /api/brokers, /api/trader-info endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from schemas import (
    ApiResponse, BrokerAlgorithmConfig, StrategyConfig, StrategyParameter,
)
from deps import verify_token, audit_log, get_bloomberg, get_broker_storage

logger = logging.getLogger("main")

router = APIRouter(tags=["Broker"])


@router.get("/api/trader-info", response_model=ApiResponse)
async def get_trader_info(user: dict = Depends(verify_token)):
    """Get the terminal's trader identity."""
    name = get_bloomberg().get_terminal_trader_name()
    return ApiResponse(success=True, data={"traderName": name}, message=f"Terminal trader: {name}")


@router.get("/api/asset-class", response_model=ApiResponse)
async def get_asset_class(ticker: str, user: dict = Depends(verify_token)):
    """Resolve EMSX asset class for a ticker.

    Current usage is still overwhelmingly EQTY, but this keeps the broker/
    strategy discovery chain explicit for future FUT/OPT/multileg flows.
    """
    asset_class = await get_bloomberg().get_asset_class(ticker)
    return ApiResponse(
        success=True,
        data={"ticker": ticker, "assetClass": asset_class},
        message=f"Resolved asset class {asset_class} for {ticker}",
    )


@router.get("/api/broker-strategies", response_model=ApiResponse)
async def get_broker_strategies(
    broker: str,
    assetClass: str = "EQTY",
    user: dict = Depends(verify_token),
):
    """Get available strategies for a broker."""
    strategies = await get_bloomberg().get_broker_strategies(broker, assetClass)
    return ApiResponse(
        success=True,
        data={"broker": broker, "assetClass": assetClass, "strategies": strategies},
        message=f"Found {len(strategies)} strategies for {broker}",
    )


@router.get("/api/broker-strategy-info", response_model=ApiResponse)
async def get_broker_strategy_info(
    broker: str,
    strategy: str,
    assetClass: str = "EQTY",
    user: dict = Depends(verify_token),
):
    """Get strategy parameter details."""
    fields = await get_bloomberg().get_broker_strategy_info(broker, strategy, assetClass)
    return ApiResponse(
        success=True,
        data={"broker": broker, "strategy": strategy, "assetClass": assetClass, "fields": fields},
        message=f"Found {len(fields)} parameters for {broker}/{strategy}",
    )


@router.get("/api/brokers", response_model=ApiResponse)
async def get_brokers(assetClass: str = "EQTY", user: dict = Depends(verify_token)):
    """Get available brokers for an asset class."""
    brokers = await get_bloomberg().get_brokers(assetClass)
    return ApiResponse(
        success=True,
        data={"brokers": brokers, "assetClass": assetClass},
        message=f"Found {len(brokers)} brokers",
    )


@router.get("/api/broker-algorithms", response_model=ApiResponse)
async def get_stored_broker_algorithms(user: dict = Depends(verify_token)):
    """Get stored broker algorithm configuration."""
    storage = get_broker_storage()
    configs = await storage.get_configs()
    last_updated = await storage.get_last_updated()
    needs_refresh = await storage.needs_refresh()
    return ApiResponse(
        success=True,
        data={
            "configs": [c.model_dump() for c in configs],
            "lastUpdated": last_updated.isoformat() if last_updated else None,
            "needsRefresh": needs_refresh,
            "count": len(configs),
        },
        message=f"Retrieved {len(configs)} broker algorithm configurations",
    )


@router.post("/api/broker-algorithms/refresh", response_model=ApiResponse)
async def refresh_broker_algorithms(user: dict = Depends(verify_token)):
    """Refresh broker algorithm configuration from Bloomberg API."""
    audit_log("REFRESH_BROKER_ALGORITHMS", user.get("sub"), {})
    bb = get_bloomberg()
    storage = get_broker_storage()

    try:
        configs: List[BrokerAlgorithmConfig] = []
        brokers = await bb.get_brokers("EQTY")
        logger.info(f"[RefreshBrokerAlgorithms] Found {len(brokers)} brokers")

        for broker in brokers:
            if not broker.startswith("EQ-"):
                continue
            try:
                strategies = await bb.get_broker_strategies(broker, "EQTY")
                if not strategies:
                    continue
                strategy_configs: List[StrategyConfig] = []
                for strategy_name in strategies:
                    try:
                        fields = await bb.get_broker_strategy_info(broker, strategy_name, "EQTY")
                        strategy_configs.append(StrategyConfig(
                            name=strategy_name,
                            parameters=[
                                StrategyParameter(
                                    fieldName=f.get("fieldName", ""),
                                    stringValue=f.get("stringValue", ""),
                                    disable=f.get("disable", "N"),
                                    dataType="string",
                                    description=f"{f.get('fieldName', '')} parameter",
                                )
                                for f in fields
                            ] if fields else [],
                        ))
                    except Exception as e:
                        strategy_configs.append(StrategyConfig(name=strategy_name, parameters=[]))
                        logger.warning(f"[RefreshBrokerAlgorithms] Failed info for {broker}/{strategy_name}: {e}")
                configs.append(BrokerAlgorithmConfig(
                    broker=broker,
                    strategies=strategy_configs,
                ))
            except Exception as e:
                logger.warning(f"[RefreshBrokerAlgorithms] Failed broker {broker}: {e}")

        success = await storage.save(configs)
        if success:
            return ApiResponse(
                success=True,
                data={
                    "configs": [c.model_dump() for c in configs],
                    "count": len(configs),
                    "lastUpdated": datetime.now().isoformat(),
                },
                message=f"Successfully refreshed {len(configs)} broker algorithm configurations",
            )
        raise HTTPException(500, "Failed to save broker algorithm configuration")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[RefreshBrokerAlgorithms] Failed: {e}")
        raise HTTPException(500, f"Failed to refresh broker algorithms: {str(e)}")


@router.get("/api/broker-algorithms/status", response_model=ApiResponse)
async def get_broker_algorithms_status(user: dict = Depends(verify_token)):
    """Get status of broker algorithm configuration storage."""
    storage = get_broker_storage()
    last_updated = await storage.get_last_updated()
    needs_refresh = await storage.needs_refresh()
    return ApiResponse(
        success=True,
        data={
            "lastUpdated": last_updated.isoformat() if last_updated else None,
            "needsRefresh": needs_refresh,
            "hasData": last_updated is not None,
        },
        message="Broker algorithm status retrieved",
    )


# ─── WBS-08 handoff contract: CostView → ExecutionView ───────────────────────


@router.get("/api/broker-recommendations", response_model=ApiResponse)
async def get_broker_recommendations(
    assetClass: str | None = None,
    broker: str | None = None,
    limit: int = 20,
    user: dict = Depends(verify_token),
):
    """Read pinned CostView broker/strategy recommendations.

    WBS-08 contract 3: CostView → ExecutionView. CostView publishes cohort
    scorecard conclusions via POST /api/tca/recommendations/pin; ExecutionView
    reads them here when composing a new order/route so trader decisions stay
    backed by post-trade evidence instead of gut feel.
    """
    from platform_data import get_shared_handoff_exchange

    recs = get_shared_handoff_exchange().list_cost_to_execution(
        asset_class=assetClass,
        broker=broker,
        limit=max(1, min(limit, 100)),
    )
    serialized = [
        {
            "metadata": {
                "contract_version": r.metadata.contract_version,
                "source": r.metadata.source,
                "handoff_target": r.metadata.handoff_target,
                "generated_at": r.metadata.generated_at,
                "trace_id": r.metadata.trace_id,
                "origin_trace_id": r.metadata.origin_trace_id,
            },
            "cohort": r.cohort,
            "asset_class": r.asset_class,
            "broker": r.broker,
            "strategy": r.strategy,
            "urgency": r.urgency,
            "sample_size": r.sample_size,
            "arrival_bps": r.arrival_bps,
            "implementation_bps": r.implementation_bps,
            "severity": r.severity,
            "rationale": r.rationale,
            "source_report_trace_id": r.source_report_trace_id,
        }
        for r in recs
    ]
    return ApiResponse(
        success=True,
        data={"recommendations": serialized, "count": len(serialized)},
        message=f"Fetched {len(serialized)} CostView broker/strategy recommendation(s)",
    )

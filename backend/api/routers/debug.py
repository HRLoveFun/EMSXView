"""Debug router — /api/debug/* endpoints."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from schemas import ApiResponse
from config import settings
from deps import verify_token, get_bloomberg_service

logger = logging.getLogger("main")

router = APIRouter(tags=["Debug"])


@router.get("/api/debug/round-lot-sizes", response_model=ApiResponse)
async def get_round_lot_sizes(
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Get cached round lot sizes for debugging odd lot detection."""
    bb = bloomberg
    round_lot_sizes = dict(bb._round_lot_sizes)
    subscribed_tickers = list(bb._mktdata_subscribed_tickers)
    active_tickers = list(bb._mktdata_active_tickers)
    failed_tickers = list(bb._mktdata_failed_tickers)

    debug_symbols = [
        "COST US Equity", "DE US Equity", "GEV US Equity", "RS US Equity",
        "ZS US Equity", "ROP US Equity", "ORCL US Equity", "MSTR US Equity",
        "INTU US Equity", "HUBS US Equity", "ADBE US Equity", "MPWR US Equity",
        "VRSN US Equity", "IT US Equity", "IBM US Equity", "ZBRA US Equity",
        "TDY US Equity", "MSI US Equity", "CHTR US Equity", "SPY US Equity",
        "AVGO US Equity", "PH US Equity", "ETN US Equity", "V US Equity",
    ]
    debug_info = {}
    for sym in debug_symbols:
        debug_info[sym] = {
            "round_lot": round_lot_sizes.get(sym),
            "subscribed": sym in subscribed_tickers,
            "active": sym in active_tickers,
            "failed": sym in failed_tickers,
        }

    return ApiResponse(
        success=True,
        data={
            "round_lot_sizes": round_lot_sizes,
            "debug_symbols": debug_info,
            "config": {"odd_lot_markets": settings.ODD_LOT_MARKETS},
            "stats": {
                "total_cached": len(round_lot_sizes),
                "subscribed": len(subscribed_tickers),
                "active": len(active_tickers),
                "failed": len(failed_tickers),
            },
        },
        message=f"Cached {len(round_lot_sizes)} round lot sizes for markets {settings.ODD_LOT_MARKETS}",
    )


@router.post("/api/debug/query-round-lot", response_model=ApiResponse)
async def query_round_lot(
    ticker: str,
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
):
    """Manually query PX_ROUND_LOT_SIZE for a specific ticker."""
    try:
        import blpapi

        bb = bloomberg
        sess = bb._mktdata_session
        if not sess:
            return ApiResponse(success=False, error="Mktdata session not available")

        svc = sess.getService("//blp/refdata")
        req = svc.createRequest("ReferenceDataRequest")
        securities = req.getElement("securities")
        securities.appendValue(ticker)
        fields = req.getElement("fields")
        fields.appendValue("PX_ROUND_LOT_SIZE")

        logger.info(f"[DEBUG_BDP] Querying PX_ROUND_LOT_SIZE for {ticker}")
        sess.sendRequest(req)

        timeout_ms = 5000
        deadline = datetime.now().timestamp() * 1000 + timeout_ms
        result = None

        while datetime.now().timestamp() * 1000 < deadline:
            ev = sess.nextEvent(500)
            if ev.eventType() in (blpapi.Event.RESPONSE, blpapi.Event.PARTIAL_RESPONSE):
                for msg in ev:
                    security_data = msg.getElement("securityData")
                    for i in range(security_data.numValues()):
                        sec = security_data.getValueAsElement(i)
                        field_data = sec.getElement("fieldData")
                        if field_data.hasElement("PX_ROUND_LOT_SIZE"):
                            result = field_data.getElementAsFloat("PX_ROUND_LOT_SIZE")
                if ev.eventType() == blpapi.Event.RESPONSE:
                    break

        cached_value = bb._round_lot_sizes.get(ticker)
        return ApiResponse(
            success=True,
            data={
                "ticker": ticker,
                "queried_round_lot": result,
                "cached_round_lot": cached_value,
                "match": result == cached_value if result is not None and cached_value is not None else None,
            },
            message=f"PX_ROUND_LOT_SIZE for {ticker}: queried={result}, cached={cached_value}",
        )
    except Exception as e:
        logger.error(f"[DEBUG_BDP] Error querying {ticker}: {e}")
        return ApiResponse(success=False, error=str(e))

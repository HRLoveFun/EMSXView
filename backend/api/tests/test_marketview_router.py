"""Tests for MarketView router — now served by standalone service, not backend.

Phase B3: The marketview router has been removed from backend/api/routers/.
MarketView endpoints are served by the standalone MarketView service (:8001).
This test verifies that the backend core no longer exposes marketview routes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# Import only core routes — marketview is no longer part of backend
from routers import connection, auth, orders, routes, broker, debug, realtime


def _build_core_app() -> FastAPI:
    """Build a FastAPI app with only core ExecutionView routers."""
    app = FastAPI()
    app.include_router(connection.router)
    app.include_router(auth.router)
    app.include_router(orders.router)
    app.include_router(routes.router)
    app.include_router(broker.router)
    app.include_router(debug.router)
    app.include_router(realtime.router)
    return app


def test_marketview_snapshot_returns_404_from_backend_core():
    """Core backend no longer exposes /api/marketview/* — served by standalone MarketView."""
    client = TestClient(_build_core_app())

    response = client.get("/api/marketview/snapshot")
    assert response.status_code == 404, (
        "MarketView snapshot endpoint should return 404 from core backend; "
        "it is served by the standalone MarketView service (:8001)"
    )

    response = client.get("/api/marketview/intraday-features?tickers=AAPL")
    assert response.status_code == 404, (
        "Intraday features endpoint should return 404 from core backend"
    )


def test_marketview_handoff_endpoint_returns_404_from_backend_core():
    """Core backend no longer exposes /api/marketview/handoff/execution."""
    client = TestClient(_build_core_app())

    response = client.post(
        "/api/marketview/handoff/execution",
        json={"pool_id": "all", "tickers": ["AAPL"], "limit": 10},
    )
    assert response.status_code == 404, (
        "Handoff endpoint should return 404 from core backend"
    )

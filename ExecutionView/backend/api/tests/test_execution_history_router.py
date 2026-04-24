from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = Path(__file__).resolve().parents[1]
for path in (PROJECT_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from platform_data import (
    ExecutionHistoryFillRow,
    ExecutionHistoryFillSnapshot,
    ExecutionHistoryOrderSummaryRow,
    ExecutionHistoryOrderSummarySnapshot,
    ExecutionHistoryRouteSummaryRow,
    ExecutionHistoryRouteSummarySnapshot,
)
from routers import execution_history as execution_history_router_module


class _FakeExecutionHistoryAdapter:
    def list_fill_history(self, **kwargs):
        return ExecutionHistoryFillSnapshot(
            start_date="20260422",
            end_date="20260422",
            row_count=1,
            rows=[
                ExecutionHistoryFillRow(
                    order_id="1001",
                    route_id="7",
                    fill_id="F1",
                    order_as_of_date="20260422",
                    source_date="20260422",
                    local_fill_datetime="2026-04-22T10:00:00",
                    exchange_exec_time="10:00:00",
                    route_as_of_time="09:45:00",
                    ny_fill_datetime="2026-04-22T22:00:00",
                    broker="BMTB",
                    strategy_type="VWAP",
                    algo="VWAP",
                    trader_name="TRADER1",
                    exchange="US",
                    side="BUY",
                    equ_ticker="AAPL US Equity",
                    ccy_ticker="USD Curncy",
                    exec_type="TRADE",
                    amount=1000.0,
                    route_shares=100.0,
                    fill_price=189.25,
                    fill_shares=100.0,
                    fetched_at="2026-04-22T10:06:00",
                )
            ],
        )

    def list_order_history(self, **kwargs):
        return ExecutionHistoryOrderSummarySnapshot(
            start_date="20260422",
            end_date="20260422",
            row_count=1,
            rows=[
                ExecutionHistoryOrderSummaryRow(
                    order_id="1001",
                    order_as_of_date="20260422",
                    equ_ticker="AAPL US Equity",
                    side="BUY",
                    route_count=1,
                    fill_count=1,
                    total_fill_shares=100.0,
                    average_fill_price=189.25,
                    first_fill_time="2026-04-22T10:00:00",
                    last_fill_time="2026-04-22T10:00:00",
                )
            ],
        )

    def list_route_history(self, **kwargs):
        return ExecutionHistoryRouteSummarySnapshot(
            start_date="20260422",
            end_date="20260422",
            row_count=1,
            rows=[
                ExecutionHistoryRouteSummaryRow(
                    order_id="1001",
                    route_id="7",
                    order_as_of_date="20260422",
                    broker="BMTB",
                    algo="VWAP",
                    trader_name="TRADER1",
                    exchange="US",
                    side="BUY",
                    equ_ticker="AAPL US Equity",
                    fill_count=1,
                    total_fill_shares=100.0,
                    average_fill_price=189.25,
                    first_fill_time="2026-04-22T10:00:00",
                    last_fill_time="2026-04-22T10:00:00",
                )
            ],
        )


def _build_client(monkeypatch) -> TestClient:
    app = FastAPI()
    monkeypatch.setattr(
        execution_history_router_module,
        "platform_data",
        SimpleNamespace(execution_history=_FakeExecutionHistoryAdapter()),
    )
    app.include_router(execution_history_router_module.router)
    return TestClient(app)


def test_execution_history_router_returns_fill_history(monkeypatch):
    client = _build_client(monkeypatch)

    response = client.get("/api/execution-history/fills", params={"order_id": "1001", "limit": 25})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["row_count"] == 1
    assert body["data"]["rows"][0]["fill_id"] == "F1"


def test_execution_history_router_returns_order_and_route_summaries(monkeypatch):
    client = _build_client(monkeypatch)

    order_response = client.get("/api/execution-history/orders", params={"order_id": "1001"})
    route_response = client.get("/api/execution-history/routes", params={"order_id": "1001"})

    assert order_response.status_code == 200
    assert order_response.json()["data"]["rows"][0]["route_count"] == 1
    assert route_response.status_code == 200
    assert route_response.json()["data"]["rows"][0]["route_id"] == "7"


def test_execution_history_router_rejects_inverted_date_window(monkeypatch):
    client = _build_client(monkeypatch)

    response = client.get(
        "/api/execution-history/fills",
        params={"start_date": "20260423", "end_date": "20260422"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "start_date must be <= end_date"
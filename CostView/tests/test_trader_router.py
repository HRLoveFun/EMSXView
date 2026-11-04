"""trader 路由契约测试（PR-1）：信封 / 200 / 422 / 503（data_not_ready 与缺库）。"""

from __future__ import annotations

import pytest

from CostView.tests.trader_fixtures import make_manager


def _client(monkeypatch, mgr) -> object:
    """独立 FastAPI app + 指定连接管理器（聚焦路由契约，不启动全量 app）。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from CostView.api.routers.trader import router
    from CostView.src import trader_service

    monkeypatch.setattr(trader_service, "DEFAULT_MANAGER", mgr)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    mgr = make_manager(tmp_path, [
        {"OrderId": "M1", "RouteId": "R1", "fill": 700.0, "fill_count": 4},
        {"OrderId": "M1", "RouteId": "R2", "fill": 200.0,
         "RouteShares": 500.0, "Amount": 500.0, "fill_count": 2},
        {"OrderId": "S1", "fill": 900.0, "fill_count": 3,
         "order_as_of_date": "20261021"},
    ])
    return _client(monkeypatch, mgr)


class TestOrdersEndpoint:
    def test_success_envelope(self, client):
        response = client.get(
            "/api/tca/trader/orders",
            params={"start_date": "20261020", "end_date": "20261022"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["message"]
        assert body["data"]["total_orders"] == 2
        assert {o["order_id"] for o in body["data"]["orders"]} == {"M1", "S1"}
        assert body["data"]["probes"]["spec_version"]

    def test_invalid_enum_is_422(self, client):
        for params in (
            {"quality": "bad"},
            {"completion_bucket": "lt90"},
            {"sort": "hack"},
            {"limit": 201},
            {"start_date": "2026-10-20"},
        ):
            response = client.get("/api/tca/trader/orders", params=params)
            assert response.status_code == 422, params

    def test_default_dates_when_no_data_is_503(self, tmp_path, monkeypatch):
        client = _client(monkeypatch, make_manager(tmp_path, []))
        response = client.get("/api/tca/trader/orders")

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "data_not_ready"

    def test_explicit_dates_empty_is_200(self, client):
        response = client.get(
            "/api/tca/trader/orders",
            params={"start_date": "20270101", "end_date": "20270131"},
        )

        assert response.status_code == 200
        assert response.json()["data"]["total_orders"] == 0

    def test_missing_db_is_503(self, tmp_path, monkeypatch):
        from data_access.storage.connection import ConnectionManager

        missing = ConnectionManager(path_overrides={
            "fill_bdib": tmp_path / "nodir" / "missing.db",
        })
        client = _client(monkeypatch, missing)
        response = client.get(
            "/api/tca/trader/orders",
            params={"start_date": "20261020", "end_date": "20261022"},
        )

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "data_source_unavailable"


class TestFilterOptionsEndpoint:
    def test_success(self, client):
        response = client.get("/api/tca/trader/filter-options")

        assert response.status_code == 200
        data = response.json()["data"]
        assert "HRCHEN" in data["traders"]
        assert data["strategy_types"]
        assert data["symbols"]


class TestOrderDetailEndpoint:
    def test_success(self, client):
        response = client.get("/api/tca/trader/orders/M1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["order"]["order_id"] == "M1"
        assert data["order"]["route_count"] == 2
        assert [r["route_id"] for r in data["routes"]] == ["R1", "R2"]
        assert data["timeline"]["bucket_min"] == 5
        assert data["quality"]["level"]

    def test_unknown_order_is_404(self, client):
        response = client.get("/api/tca/trader/orders/NOPE")
        assert response.status_code == 404

    def test_invalid_bucket_min_is_422(self, client):
        response = client.get("/api/tca/trader/orders/M1", params={"bucket_min": 7})
        assert response.status_code == 422

class TestExportEndpoint:
    """210 §3.4.4：CSV 下载（Content-Type / 文件名 / BOM / 422 上限 / 404 / 503）。"""

    def test_orders_csv_download(self, client):
        response = client.get(
            "/api/tca/trader/export",
            params={"kind": "orders", "start_date": "20261020", "end_date": "20261022"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        disposition = response.headers["content-disposition"]
        assert "attachment; filename=" in disposition
        assert "trader_orders_20261020_20261022_" in disposition
        assert response.content.startswith(b"\xef\xbb\xbf")   # UTF-8-SIG
        text = response.content.decode("utf-8-sig")
        assert text.startswith("# spec_version=")
        assert "order_id,order_as_of_date" in text

    def test_fills_csv_download(self, client):
        response = client.get(
            "/api/tca/trader/export",
            params={"kind": "fills", "start_date": "20261020", "end_date": "20261022"},
        )

        assert response.status_code == 200
        assert "trader_fills_20261020_20261022_" in response.headers["content-disposition"]
        assert "order_id,route_id,fill_id" in response.content.decode("utf-8-sig")

    def test_invalid_kind_is_422(self, client):
        response = client.get("/api/tca/trader/export", params={"kind": "bad"})
        assert response.status_code == 422

    def test_cap_exceeded_is_422(self, client, monkeypatch):
        from CostView.src import trader_service

        monkeypatch.setattr(trader_service, "EXPORT_ORDER_CAP", 1)
        response = client.get(
            "/api/tca/trader/export",
            params={"kind": "orders", "start_date": "20261020", "end_date": "20261022"},
        )

        assert response.status_code == 422
        assert "上限" in response.json()["detail"]

    def test_unknown_order_is_404(self, client):
        response = client.get(
            "/api/tca/trader/export", params={"kind": "fills", "order_id": "NOPE"},
        )
        assert response.status_code == 404

    def test_default_dates_when_no_data_is_503(self, tmp_path, monkeypatch):
        client = _client(monkeypatch, make_manager(tmp_path, []))
        response = client.get("/api/tca/trader/export", params={"kind": "orders"})

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "data_not_ready"

    def test_missing_db_is_503(self, tmp_path, monkeypatch):
        from data_access.storage.connection import ConnectionManager

        missing = ConnectionManager(path_overrides={
            "fill_bdib": tmp_path / "nodir" / "missing.db",
        })
        client = _client(monkeypatch, missing)
        response = client.get(
            "/api/tca/trader/export",
            params={"kind": "orders", "start_date": "20261020", "end_date": "20261022"},
        )

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "data_source_unavailable"


class TestPeerEndpoint:
    """GET /orders/{order_id}/peer：信封、样本不足契约、404。"""

    def test_peer_envelope_and_insufficient_contract(self, client):
        response = client.get("/api/tca/trader/orders/M1/peer")

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        # 夹具里只有 1 个同类订单（S1）且不足 20 → 样本不足但结构完整（无伪分位）
        assert data["sample_insufficient"] is True
        assert data["n"] == 1
        assert data["group"]["excludes_self"] is True
        assert len(data["metrics"]) == 8
        assert all(item["percentile"] is None for item in data["metrics"])
        assert data["hints"] == []
        assert isinstance(data["degraded"], list) and data["degraded"]

    def test_peer_unknown_order_404(self, client):
        response = client.get("/api/tca/trader/orders/NOT_EXIST/peer")

        assert response.status_code == 404


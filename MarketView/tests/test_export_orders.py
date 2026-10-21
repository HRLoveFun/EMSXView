"""盘前单端点测试（057 DL-01）。

策略与 test_marketview_router.py 一致：TestClient + monkeypatch config，
收件箱指向 tmp_path 中的夹具（不依赖真实导出目录）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# conftest 已设置 sys.path；import 顺序与 main.py 保持一致（config 先于 routers）
import config  # noqa: F401
from routers import export_orders

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN_TEXT = (FIXTURES / "emsx_export_golden.csv").read_text(encoding="utf-8-sig")


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(export_orders.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_inbox(monkeypatch):
    """每个用例默认未配置收件箱，避免读取本机真实导出目录。"""
    monkeypatch.setattr(config, "EXPORT_INBOX_DIR", "")
    yield


class TestPreTradeOrdersEndpoint:
    def test_unconfigured_inbox_returns_empty_board(self):
        response = _build_client().get("/api/marketview/pre-trade-orders")

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["order_count"] == 0
        assert body["data"]["orders"] == []
        assert "EMSXVIEW_EXPORT_INBOX_DIR" in body["message"]

    def test_empty_inbox_returns_empty_board_with_message(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "EXPORT_INBOX_DIR", str(tmp_path))

        response = _build_client().get("/api/marketview/pre-trade-orders")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["order_count"] == 0
        assert "No EMSX export file found" in body["message"]

    def test_returns_parsed_board_with_coverage_and_unmatched(self, tmp_path, monkeypatch):
        (tmp_path / "emsx_orders.csv").write_text(GOLDEN_TEXT, encoding="utf-8")
        monkeypatch.setattr(config, "EXPORT_INBOX_DIR", str(tmp_path))

        response = _build_client().get("/api/marketview/pre-trade-orders")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["order_count"] == 5
        assert data["intent_coverage_pct"] == 80.0
        assert data["intent_mapping_version"] == "emsx-pm-note-v1"
        assert data["export_file_name"] == "emsx_orders.csv"
        benchmarks = [order["intent"]["benchmark"] for order in data["orders"]]
        assert benchmarks == ["VWAP", "CLOSE", "MIX", "SPECIAL", "UNMAPPED"]
        assert data["orders"][0]["intent"]["order_key"] == "^7000001^0"
        assert data["orders"][1]["intent"]["close_pct"] == 100.0
        assert data["orders"][2]["intent"]["close_pct"] == 80.0
        # 未匹配清单与连接覆盖率在盘前单可见
        assert len(data["unmatched"]) == 1
        assert data["unmatched"][0]["code"] == "SEC_E"
        assert data["unmatched"][0]["reason"] == "unknown_prefix"
        # 受限列按缺失处理，不出现在响应中
        assert data["orders"][0]["extra_fields"].get("Vs IntervalVWAP (Bps)") is None

    def test_parse_error_maps_to_400(self, tmp_path, monkeypatch):
        (tmp_path / "bad.csv").write_text(
            "Code,Exch Code,Side,Qty,Status,Create Time (As of)\nSEC_A,EX_A,Sell,100,Working,10:29:01\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "EXPORT_INBOX_DIR", str(tmp_path))

        response = _build_client().get("/api/marketview/pre-trade-orders")

        assert response.status_code == 400
        assert "PM Note 13" in response.json()["detail"]

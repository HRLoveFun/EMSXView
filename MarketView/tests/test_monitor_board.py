"""057 节点一监控台：池注册表、聚合端点与行详情端点测试。

覆盖：14 列字段完整性、面板与表格同源同值、缺数据显式 gap、未知池 422、
详情桶序号与价格分档一致、鉴权。策略：monkeypatch 适配器与池注册表，不触真实库。
"""

from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config  # noqa: F401

from platform_data.contracts.monitor_contracts import (
    DetailBucket,
    DetailCell,
    MonitorPoolMember,
    MonitorQuote,
    PrevBucket,
    TickerDetail,
)
from routers import monitor_board
from pool_registry import IndexPool, market_code_for


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "testsecret")


def _auth_headers() -> dict:
    token = jwt.encode({"sub": "u1", "role": "trader"}, "testsecret", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _pool() -> IndexPool:
    return IndexPool(
        pool_id="dev-validation",
        label="Dev Validation",
        description="",
        source="config",
        as_of="2026-10-28",
        members=(
            MonitorPoolMember("AAPL US Equity", "Apple", "US", "US"),
            MonitorPoolMember("MC EU Equity", "LVMH", "EU", "GR"),
        ),
    )


def _quotes() -> list[MonitorQuote]:
    return [
        MonitorQuote(
            equ_ticker="AAPL US Equity",
            trade_date="20261027",
            baseline_date="20261026",
            last=190.5,
            prev_close=188.0,
            chg_pct=1.33,
            close=188.0,
            total_volume=3_000_000.0,
            adv_20d=2_000_000.0,
            adv_5d=2_100_000.0,
            vol_vs_adv20=150.0,
            daily_volatility=28.9,
            intraday_volatility=0.23,
            open=189.0,
            high=191.0,
            low=187.5,
            first_bar_time="09:30:00",
            last_bar_time="15:59:50",
            bar_count=2340,
            liquidity="normal",
            volatility="warning",
        ),
        MonitorQuote(
            equ_ticker="MC EU Equity",
            trade_date="20261027",
            baseline_date=None,
            liquidity="none",
            volatility="none",
            gaps=("baseline", "bars", "adv20", "prev_close"),
        ),
    ]


def _detail() -> TickerDetail:
    return TickerDetail(
        equ_ticker="AAPL US Equity",
        trade_date="20261027",
        bucket_minutes=10,
        buckets=(
            DetailBucket(index=0, label="09:30", volume=100.0, cumulative_volume=100.0, cumulative_pct=0.5),
            DetailBucket(index=1, label="09:40", gap=True),
            DetailBucket(index=2, label="09:50", volume=100.0, cumulative_volume=200.0, cumulative_pct=1.0),
        ),
        prev_buckets=(
            PrevBucket(index=0, label="09:30", cumulative_volume=80.0, cumulative_pct=0.4),
            PrevBucket(index=1, label="09:40"),
            PrevBucket(index=2, label="09:50", cumulative_volume=200.0, cumulative_pct=1.0),
        ),
        prev_days=5,
        prev_dates=("20261026", "20261023"),
        ohlc={"open": 189.0, "high": 191.0, "low": 187.5, "close": 190.5},
        price_low=187.5,
        price_high=191.0,
        price_bin_count=12,
        cells=(DetailCell(bucket=0, price_bin=3, volume=100.0),),
        total_volume=200.0,
        prev_avg_volume=200.0,
        gaps=("09:40",),
    )


class FakeMonitor:
    def __init__(self, quotes=None, detail=None):
        self._quotes = quotes if quotes is not None else _quotes()
        self._detail = detail or _detail()

    def get_quotes(self, members, trade_date=None):
        return trade_date or "20261027", list(self._quotes)

    def get_detail(self, equ_ticker, **_kwargs):
        return self._detail


def _install(monkeypatch, fake=None):
    monkeypatch.setattr(monitor_board, "_get_monitor", lambda: fake or FakeMonitor())
    monkeypatch.setattr(monitor_board, "get_pool", lambda _pool_id=None: _pool())


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(monitor_board.router)
    return TestClient(app)


def test_market_code_aliases():
    assert market_code_for("CH") == "C1"
    assert market_code_for("EU") == "GR"
    assert market_code_for("GY") == "GR"
    assert market_code_for("US") == "US"


def test_dev_pool_config_has_eight_members():
    from pool_registry import load_pools

    pools = load_pools()
    dev = next(pool for pool in pools if pool.pool_id == "dev-validation")
    assert len(dev.members) == 8
    assert {member.equ_ticker for member in dev.members} == {
        "NVDA US Equity",
        "601398 CH Equity",
        "700 HK Equity",
        "285A JP Equity",
        "HSBA LN Equity",
        "MC EU Equity",
        "BHP AU Equity",
        "005930 KS Equity",
    }


def test_board_has_14_columns_and_same_source_highlights(monkeypatch):
    _install(monkeypatch)
    response = _client().get(
        "/api/marketview/monitor-board", params={"pool_id": "dev-validation"}, headers=_auth_headers()
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["row_count"] == 2
    assert payload["pool"]["source"] == "config"
    row = payload["rows"][0]
    for field in (
        "equ_ticker",
        "name",
        "market_status",
        "last",
        "chg_pct",
        "close",
        "total_volume",
        "adv_20d",
        "vol_vs_adv20",
        "daily_volatility",
        "intraday_volatility",
        "liquidity",
        "volatility",
        "risk_notes",
    ):
        assert field in row
    # 面板与表格同源：同一票在 volatility 高亮里的 severity 必须与行内一致
    vol_alert = next(
        item for item in payload["highlights"]["volatility"] if item["equ_ticker"] == "AAPL US Equity"
    )
    assert vol_alert["severity"] == row["volatility"] == "warning"
    assert "Volatility elevated" in "; ".join(row["risk_notes"])


def test_missing_data_is_explicit_not_zero(monkeypatch):
    _install(monkeypatch)
    payload = _client().get("/api/marketview/monitor-board", headers=_auth_headers()).json()["data"]
    row = payload["rows"][1]
    assert row["last"] is None and row["total_volume"] is None and row["adv_20d"] is None
    assert row["source"] == "none"
    assert set(row["data_gaps"]) == {"baseline", "bars", "adv20", "prev_close"}
    assert "No intraday bars" in row["risk_notes"]
    assert any(item["equ_ticker"] == "MC EU Equity" for item in payload["highlights"]["risk_notes"])


def test_unknown_pool_maps_to_422(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(
        monitor_board, "get_pool", lambda _pool_id=None: (_ for _ in ()).throw(ValueError("Unknown index pool"))
    )
    response = _client().get("/api/marketview/monitor-board", headers=_auth_headers())
    assert response.status_code == 422


def test_ticker_detail_returns_shared_axis_and_gaps(monkeypatch):
    _install(monkeypatch)
    response = _client().get(
        "/api/marketview/ticker-detail",
        params={"ticker": "AAPL US Equity"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    labels = [bucket["label"] for bucket in payload["buckets"]]
    assert labels == [bucket["label"] for bucket in payload["prev_buckets"]]
    assert payload["buckets"][1]["gap"] is True
    assert payload["gaps"] == ["09:40"]
    assert payload["prev_days"] == 5
    assert payload["price_bin_count"] == 12
    assert payload["cells"][0]["bucket"] == 0
    assert payload["buckets"][-1]["cumulative_pct"] == 1.0


def test_requires_token(monkeypatch):
    _install(monkeypatch)
    assert _client().get("/api/marketview/monitor-board").status_code == 401
    assert _client().get("/api/marketview/ticker-detail", params={"ticker": "AAPL US Equity"}).status_code == 401

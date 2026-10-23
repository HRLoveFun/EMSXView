"""057 DL-11：市场级状态端点测试（MarketView standalone 路由）。

策略与 test_baseline_router.py 一致：TestClient + monkeypatch 替换
路由模块级 `_events` 单例为 fake adapter（不连真实库）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# conftest 已设置 sys.path；import 顺序与 main.py 保持一致
import config  # noqa: F401
from routers import regime
from platform_data.contracts import EventFlag, MarketRegimeState


def _fake_state(**overrides) -> MarketRegimeState:
    base = dict(
        market_code="ZZ",
        as_of="20261021",
        liq_regime="normal",
        vol_regime="normal",
        trend_regime="range",
        macro_events=(
            EventFlag(code="fictional_event", severity="high", window_days=2, source="macro-calendar"),
        ),
        config_version="v0_test",
    )
    base.update(overrides)
    return MarketRegimeState(**base)


class _FakeEvents:
    def __init__(self, states=None):
        self.states = states if states is not None else [_fake_state()]
        self.calls: list[dict] = []

    def get_market_states(self, market_codes, *, as_of=None):
        self.calls.append({"markets": list(market_codes), "as_of": as_of})
        return self.states


def _build_client(fake: _FakeEvents) -> TestClient:
    app = FastAPI()
    app.include_router(regime.router)
    regime._events = fake
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_singleton():
    yield
    regime._events = None


class TestRegimeEndpoint:
    def test_returns_states_and_events(self):
        client = _build_client(_FakeEvents())

        response = client.get("/api/marketview/market-regime", params={"markets": "ZZ"})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        state = body["data"]["states"][0]
        assert state["market_code"] == "ZZ"
        assert state["liq_regime"] == "normal"
        assert state["macro_events"][0]["code"] == "fictional_event"
        assert body["data"]["missing"] == []
        assert body["data"]["schema_version"] == "market-regime-v1"

    def test_missing_markets_reported(self):
        client = _build_client(_FakeEvents(states=[]))

        response = client.get("/api/marketview/market-regime", params={"markets": "ZZ,NOPE"})

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["states"] == []
        assert set(body["data"]["missing"]) == {"ZZ", "NOPE"}
        assert "missing" in body["message"]

    def test_forwards_as_of(self):
        fake = _FakeEvents()
        client = _build_client(fake)

        client.get("/api/marketview/market-regime", params={"markets": "ZZ", "as_of": "20261021"})

        assert fake.calls[0]["as_of"] == "20261021"

    def test_rejects_empty_markets(self):
        client = _build_client(_FakeEvents())

        response = client.get("/api/marketview/market-regime", params={"markets": " , "})

        assert response.status_code == 400
        assert "at least one" in response.json()["detail"]

    def test_maps_unexpected_error_to_500(self, monkeypatch):
        from platform_data.adapters.events import EventRegimeAdapter

        def _boom(self, codes, *, as_of=None):
            raise RuntimeError("regime db down")

        monkeypatch.setattr(EventRegimeAdapter, "get_market_states", _boom)
        regime._events = None
        app = FastAPI()
        app.include_router(regime.router)
        client = TestClient(app)

        response = client.get("/api/marketview/market-regime", params={"markets": "ZZ"})

        assert response.status_code == 500

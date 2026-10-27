"""057 DL-14：盘前单装配测试（MarketView standalone 路由）。

策略与 test_baseline_router.py 一致：TestClient + monkeypatch 替换路由模块
依赖（load_pre_trade_board / 适配器 / 模型加载 / ADV 点查），不连真实库。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# conftest 已设置 sys.path；import 顺序与 main.py 保持一致
import config  # noqa: F401
from routers import pretrade
from platform_data.contracts import PreTradeBoardItem


class _FakeOrder:
    def __init__(self, code: str, qty: float, benchmark: str = "VWAP"):
        self.code = code
        self.qty = qty
        self.intent = type("Intent", (), {"order_key": f"^{code}^0", "benchmark": benchmark, "close_pct": None})()
        self.name = code


class _FakeBoard:
    def __init__(self, orders):
        self.orders = orders
        self.export_file_name = "fake.csv"


class _FakeBaselineAdapter:
    def __init__(self, baselines=None):
        self.baselines = baselines if baselines is not None else {}

    def get_baseline(self, tickers, *, as_of=None, connection_manager=None):
        return [self.baselines[t] for t in tickers if t in self.baselines]


class _FakeRegimeAdapter:
    def __init__(self, states=None):
        self.states = states if states is not None else []

    def get_market_states(self, market_codes, *, as_of=None, connection_manager=None):
        return [s for s in self.states if s.market_code in market_codes]


class _FakeSessionAdapter:
    def market_code_for(self, exchange_code: str) -> str:
        return exchange_code.upper()

    def get_session(self, exchange_code: str):
        return None


def _install(monkeypatch, *, board=None, baselines=None, states=None, adv20=None, model=None):
    """替换 pretrade 路由的全部外部依赖。"""
    board = board if board is not None else _FakeBoard([_FakeOrder("SEC_A US Equity", 50_000)])
    monkeypatch.setattr(pretrade, "load_pre_trade_board", lambda inbox: board)
    monkeypatch.setattr(pretrade, "_baseline", _FakeBaselineAdapter(baselines or {}))
    monkeypatch.setattr(pretrade, "_regime", _FakeRegimeAdapter(states or []))
    monkeypatch.setattr(pretrade, "_session", _FakeSessionAdapter())
    monkeypatch.setattr(pretrade, "_load_adv20", lambda mgr, t, d: adv20)

    import CostView.src.evaluation.expected_cost as ec

    monkeypatch.setattr(ec, "load_expected_cost_model", lambda market: model)


def _fake_baseline():
    from platform_data.contracts import MarketBaseline

    return MarketBaseline(
        equ_ticker="SEC_A US Equity",
        as_of="20261021",
        log_volume_z=1.2,
        vol_percentile=80.0,
        intraday_vol_percentile=60.0,
        overnight_gap_sigma=0.5,
        auction_open_pct=None,
        auction_close_pct=12.0,
        adv5_adv60_ratio=0.95,
        spread_proxy_bps=5.0,
        n_days=60,
    )


def _fake_state():
    from platform_data.contracts import MarketRegimeState

    return MarketRegimeState(
        market_code="US",
        as_of="20261021",
        liq_regime="normal",
        vol_regime="normal",
        trend_regime="range",
    )


def _fake_model():
    from CostView.src.evaluation.cost_model import ImpactModel

    return ImpactModel(
        intercept=1.0,
        slope_participation=0.5,
        slope_volatility=0.3,
        n_observations=100,
        r_squared=0.1,
        participation_domain=(0.0001, 0.5),
        volatility_domain=(5.0, 60.0),
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(pretrade.router)
    return TestClient(app)


class TestAssemble:
    """① 装配逻辑（monkeypatch 依赖）。"""

    def test_full_assembly(self, monkeypatch):
        _install(
            monkeypatch,
            baselines={"SEC_A US Equity": _fake_baseline()},
            states=[_fake_state()],
            adv20=1_000_000,
            model=_fake_model(),
        )

        items = pretrade.assemble_items()

        assert len(items) == 1
        item = items[0]
        assert item.equ_ticker == "SEC_A US Equity"
        assert item.order_key == "^SEC_A US Equity^0"
        assert item.benchmark == "VWAP"
        assert item.log_volume_z == 1.2
        assert item.liq_regime == "normal"
        assert item.expected_cost_bps is not None
        assert item.in_domain is True
        assert item.model_version == "cost-model-v1"
        assert item.model_calibrated is False  # DL-13 v1 未达标恒定标注
        assert item.data_gaps == ()

    def test_missing_products_record_gaps(self, monkeypatch):
        # 无基线、无状态、无模型、无 ADV20 —— 四路全缺
        _install(monkeypatch)

        items = pretrade.assemble_items()

        item = items[0]
        assert set(item.data_gaps) == {"baseline", "regime", "cost_model", "adv20"}
        assert item.log_volume_z is None
        assert item.liq_regime is None
        assert item.expected_cost_bps is None
        assert item.in_domain is False

    def test_empty_board_returns_empty(self, monkeypatch):
        _install(monkeypatch, board=None)
        monkeypatch.setattr(pretrade, "load_pre_trade_board", lambda inbox: None)

        assert pretrade.assemble_items() == []

    def test_market_folding_used_for_state_lookup(self, monkeypatch):
        # GR → EU 折叠后按 EU 查状态（fake state 用 EU）
        from platform_data.contracts import MarketRegimeState

        board = _FakeBoard([_FakeOrder("SEC_G GR Equity", 50_000)])
        eu_state = MarketRegimeState(
            market_code="EU", as_of="20261021", liq_regime="thin",
            vol_regime="high", trend_regime="downtrend",
        )

        class _FoldSession:
            def market_code_for(self, code):
                return "EU"

            def get_session(self, code):
                return None

        monkeypatch.setattr(pretrade, "load_pre_trade_board", lambda inbox: board)
        monkeypatch.setattr(pretrade, "_baseline", _FakeBaselineAdapter())
        monkeypatch.setattr(pretrade, "_regime", _FakeRegimeAdapter([eu_state]))
        monkeypatch.setattr(pretrade, "_session", _FoldSession())
        monkeypatch.setattr(pretrade, "_load_adv20", lambda mgr, t, d: None)

        items = pretrade.assemble_items()

        assert items[0].market_code == "EU"
        assert items[0].liq_regime == "thin"
        assert set(items[0].data_gaps) == {"baseline", "cost_model", "adv20"}


class TestEndpoint:
    """③ 端点。"""

    def test_empty_board_message(self, monkeypatch):
        monkeypatch.setattr(pretrade, "assemble_items", lambda: [])
        response = _client().get("/api/marketview/pretrade-board")

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["items"] == []
        assert "EMSXVIEW_EXPORT_INBOX_DIR" in body["message"]
        assert body["data"]["schema_version"] == "market-to-execution-v2"

    def test_assembly_error_maps_to_500(self, monkeypatch):
        def _boom():
            raise RuntimeError("inbox missing")

        monkeypatch.setattr(pretrade, "assemble_board", _boom)
        response = _client().get("/api/marketview/pretrade-board")

        assert response.status_code == 500

"""057 DL-22/214：影子运行核心测试。

覆盖：契约 v2、改写原因、报价价差、订单触发/去重、无计划降级、
实际路由关联、SQLite 覆盖率与回填。
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

# backend config 在 import 时校验 JWT_SECRET（deployment-only 闸门）；测试环境给一个最小值
os.environ.setdefault("JWT_SECRET", "test-shadow-run-secret-0123456789abcdef")

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from platform_data.contracts import (  # noqa: E402
    DECISION_SCHEMA_VERSION,
    REWRITE_BROKER_CHANGED,
    REWRITE_EXTRA_ROUTE,
    REWRITE_PARAMS_CHANGED,
    REWRITE_QUANTITY_CHANGED,
    REWRITE_UNCLASSIFIED,
    SOURCE_ENGINE,
    SOURCE_ENGINE_DEFAULT,
    RoutingDecision,
    DecisionCandidate,
)
from services import decision_log_service, shadow_run_service  # noqa: E402


def _order(order_id: str = "O-1") -> SimpleNamespace:
    return SimpleNamespace(
        id=order_id, symbol="AAPL US Equity", side="BUY", status="WORKING",
        remainingQuantity=1000, price=100.0,
    )


def _plan() -> SimpleNamespace:
    return SimpleNamespace(id=7, split_type="BROKER_SPLIT", participation_rate=0.15)


def _proposals() -> list[dict]:
    return [
        {"broker": "EQ-AAA", "quantity": 600, "slice_index": 1,
         "strategy_params": {"PctVol": "15.0"}},
        {"broker": "EQ-BBB", "quantity": 400, "slice_index": 2,
         "strategy_params": {"PctVol": "15.0"}},
    ]


class TestContractV2:
    def test_defaults_are_backward_compatible(self) -> None:
        decision = RoutingDecision(
            decision_id="d", trace_id="t", order_id="o", ticker="AAPL US Equity",
            side="BUY", as_of="2026-11-25T10:00:00+00:00", plan_id=None,
            split_type="", mode="SHADOW",
            candidates=(DecisionCandidate(broker="A", quantity=1),),
        )
        assert decision.schema_version == DECISION_SCHEMA_VERSION == "routing-decision-v2"
        assert decision.source == SOURCE_ENGINE
        assert decision.actual_routes == ()
        assert decision.constraint_violations == ()

    def test_context_populates_v2_fields(self) -> None:
        decision = decision_log_service.build_shadow_decision(
            _order(), _plan(), _proposals(),
            context={
                "source": SOURCE_ENGINE,
                "quote_spread_bps": 12.5,
                "market_state": {"symbol": "AAPL US Equity"},
                "constraint_violations": [{"code": "X", "severity": "BLOCK"}],
            },
        )
        assert decision.source == SOURCE_ENGINE
        assert decision.quote_spread_bps == 12.5
        assert decision.market_state["symbol"] == "AAPL US Equity"
        assert decision.constraint_violations[0]["severity"] == "BLOCK"


class TestRewriteReason:
    def test_extra_route(self) -> None:
        candidates = [{"broker": "A", "quantity": 100}]
        actual = [{"broker": "A", "quantity": 100}, {"broker": "C", "quantity": 50}]
        assert shadow_run_service.rewrite_reason(candidates, actual) == REWRITE_EXTRA_ROUTE

    def test_broker_changed(self) -> None:
        assert shadow_run_service.rewrite_reason(
            [{"broker": "A", "quantity": 100}], [{"broker": "B", "quantity": 100}],
        ) == REWRITE_BROKER_CHANGED

    def test_quantity_changed(self) -> None:
        assert shadow_run_service.rewrite_reason(
            [{"broker": "A", "quantity": 100}], [{"broker": "A", "quantity": 80}],
        ) == REWRITE_QUANTITY_CHANGED

    def test_params_changed(self) -> None:
        assert shadow_run_service.rewrite_reason(
            [{"broker": "A", "quantity": 100, "strategy_params": {"strategy_type": "VWAP"}}],
            [{"broker": "A", "quantity": 100, "strategy_type": "TWAP"}],
        ) == REWRITE_PARAMS_CHANGED

    def test_unclassified(self) -> None:
        assert shadow_run_service.rewrite_reason([], [{"broker": "A"}]) == REWRITE_UNCLASSIFIED


class TestQuoteSpread:
    def test_dict_quote(self) -> None:
        class _Bloomberg:
            def get_quote(self, symbol):
                return {"bid": 99.0, "ask": 101.0}

        spread = asyncio.run(shadow_run_service.quote_spread_bps(_Bloomberg(), "AAPL US Equity"))
        assert spread == pytest.approx(200.0)

    def test_missing_quote_returns_none(self) -> None:
        assert asyncio.run(shadow_run_service.quote_spread_bps(object(), "AAPL US Equity")) is None


class _FakeRepo:
    async def list_active_auto_plans(self):
        return [_plan()]


class _FakeEngine:
    def __init__(self, match: bool = True) -> None:
        self.repo = _FakeRepo()
        self.match = match
        self.record_shadow_calls: list[bool] = []

    def match_plans(self, order, plans):
        return plans if self.match else []

    async def generate_proposals(self, order, plan, *, record_shadow=True):
        self.record_shadow_calls.append(record_shadow)
        return _proposals()


class _Bloomberg:
    def get_quote(self, symbol):
        return {"bid": 99.0, "ask": 101.0}


def _wire(monkeypatch, engine: _FakeEngine):
    recorded: list = []
    checks: list = []

    async def fake_record(decision):
        recorded.append(decision)
        return True

    async def fake_update(order_id, routes, rewrite_reason=""):
        checks.append((order_id, list(routes), rewrite_reason))
        return True

    monkeypatch.setattr(decision_log_service, "shadow_run_enabled", lambda: True)
    monkeypatch.setattr(decision_log_service, "record_decision", fake_record)
    monkeypatch.setattr(decision_log_service, "update_actual_routes", fake_update)

    async def fake_pre_trade(order, proposal, bloomberg=None):
        return [{"code": "BLOCK-1", "severity": "BLOCK", "message": "test"}]

    import services.pre_trade_checks as ptc

    monkeypatch.setattr(ptc, "pre_trade_checks", fake_pre_trade)
    runner = shadow_run_service.ShadowRunner(engine, _Bloomberg())
    return runner, recorded, checks


def test_on_order_records_and_dedupes(monkeypatch) -> None:
    engine = _FakeEngine()
    runner, recorded, _ = _wire(monkeypatch, engine)

    asyncio.run(runner.on_order(_order()))
    asyncio.run(runner.on_order(_order()))

    assert len(recorded) == 1
    assert recorded[0].source == SOURCE_ENGINE
    assert recorded[0].candidate_count() == 2
    assert recorded[0].constraint_violations[0]["severity"] == "BLOCK"
    assert recorded[0].quote_spread_bps == pytest.approx(200.0)
    assert engine.record_shadow_calls == [False]


def test_on_order_without_plan_records_no_suggestion(monkeypatch) -> None:
    engine = _FakeEngine(match=False)
    runner, recorded, _ = _wire(monkeypatch, engine)

    asyncio.run(runner.on_order(_order()))

    assert len(recorded) == 1
    assert recorded[0].source == SOURCE_ENGINE_DEFAULT
    assert recorded[0].candidate_count() == 0
    assert recorded[0].rationale == "no_matching_plan"


def test_on_route_associates_and_backfills(monkeypatch) -> None:
    engine = _FakeEngine()
    runner, recorded, checks = _wire(monkeypatch, engine)
    asyncio.run(runner.on_order(_order()))

    route = SimpleNamespace(
        sequence="O-1", routeId=11, broker="EQ-AAA", quantity=600,
        strategyType="VWAP", status="WORKING", filledQuantity=0, limitPrice=100.0,
    )
    asyncio.run(runner.on_route(route))
    assert checks[-1][0] == "O-1"
    assert checks[-1][1][0]["route_id"] == "11"
    # 建议 A+B，实际只看到 A → 缺券商
    assert checks[-1][2] == REWRITE_BROKER_CHANGED

    second = SimpleNamespace(
        sequence="O-1", routeId=12, broker="EQ-BBB", quantity=400,
        strategyType="VWAP", status="WORKING", filledQuantity=0, limitPrice=100.0,
    )
    asyncio.run(runner.on_route(second))
    assert checks[-1][2] == REWRITE_UNCLASSIFIED

    extra = SimpleNamespace(
        sequence="O-1", routeId=13, broker="EQ-CCC", quantity=50,
        strategyType="VWAP", status="WORKING", filledQuantity=0, limitPrice=100.0,
    )
    asyncio.run(runner.on_route(extra))
    assert checks[-1][2] == REWRITE_EXTRA_ROUTE


@pytest.fixture()
def sqlite_db(monkeypatch, tmp_path):
    db_path = tmp_path / "ops" / "emsx_ops.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    import db as db_mod

    reloaded = importlib.reload(db_mod)
    ok, msg = asyncio.run(reloaded.initialize_database())
    assert ok, msg
    yield db_path
    asyncio.run(reloaded.dispose_engine())


def test_update_actual_routes_and_coverage(sqlite_db) -> None:
    decision = decision_log_service.build_shadow_decision(
        _order(), _plan(), _proposals(),
        context={"constraint_violations": [{"code": "X", "severity": "BLOCK"}]},
    )
    assert asyncio.run(decision_log_service.record_decision(decision)) is True
    assert asyncio.run(
        decision_log_service.update_actual_routes(
            "O-1", [{"route_id": "11", "broker": "EQ-AAA", "quantity": 600}],
            REWRITE_UNCLASSIFIED,
        )
    ) is True

    records = asyncio.run(decision_log_service.load_decisions(order_id="O-1"))
    assert records[0]["payload"]["actual_routes"][0]["route_id"] == "11"
    assert records[0]["payload"]["rewrite_reason"] == REWRITE_UNCLASSIFIED

    summary = asyncio.run(decision_log_service.coverage())
    assert summary["total_decisions"] == 1
    assert summary["hard_violations"] == 1
    assert summary["actual_linked"] == 1
    assert summary["by_source"] == {SOURCE_ENGINE: 1}

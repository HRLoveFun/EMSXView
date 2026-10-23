"""057 DL-21/075：路由决策日志（影子方式）测试。

覆盖：契约字段、build_shadow_decision 组装、SQLite 夹具下的 record/load、
降级（DB 不可用不抛）、开关、影子不改变提案。
"""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from platform_data.contracts import (  # noqa: E402
    CONSTRAINT_MATRIX_VERSION,
    DECISION_SCHEMA_VERSION,
    MODE_SHADOW,
    RoutingDecision,
)
from services import decision_log_service  # noqa: E402


def _order():
    return SimpleNamespace(id="O-1", symbol="AAPL US Equity", side="BUY", exchange="US")


def _plan():
    return SimpleNamespace(
        id=7, split_type="BROKER_SPLIT", participation_rate=0.15
    )


def _proposals():
    return [
        {"broker": "EQ-AAA", "quantity": 600, "slice_index": 1, "strategy_params": {"PctVol": "15.0"}},
        {"broker": "EQ-BBB", "quantity": 400, "slice_index": 2, "strategy_params": {"PctVol": "15.0"}},
    ]


class TestBuildShadowDecision:
    """① 契约装配（字段完整性 + 四版本号）。"""

    def test_fields(self):
        decision = decision_log_service.build_shadow_decision(_order(), _plan(), _proposals())

        assert decision.order_id == "O-1"
        assert decision.ticker == "AAPL US Equity"
        assert decision.side == "BUY"
        assert decision.mode == MODE_SHADOW
        assert decision.plan_id == 7
        assert decision.split_type == "BROKER_SPLIT"
        assert decision.candidate_count() == 2
        assert decision.total_quantity() == 1000
        assert decision.candidates[0].broker == "EQ-AAA"
        assert decision.candidates[0].quantity == 600
        assert decision.candidates[0].participation_pct == 0.15
        assert set(decision.versions) == {"registry", "constraints", "params", "decision"}
        assert decision.versions["constraints"] == CONSTRAINT_MATRIX_VERSION
        assert decision.schema_version == DECISION_SCHEMA_VERSION

    def test_empty_proposals(self):
        decision = decision_log_service.build_shadow_decision(_order(), _plan(), [])
        assert decision.candidate_count() == 0
        assert decision.total_quantity() == 0


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


class TestRecordAndLoad:
    """② 写入与查询（真实 SQLite 运营库）。"""

    def test_roundtrip(self, sqlite_db):
        decision = decision_log_service.build_shadow_decision(_order(), _plan(), _proposals())
        assert asyncio.run(decision_log_service.record_decision(decision)) is True

        records = asyncio.run(decision_log_service.load_decisions(order_id="O-1"))
        assert len(records) == 1
        record = records[0]
        assert record["decision_id"] == decision.decision_id
        assert record["mode"] == MODE_SHADOW
        assert record["payload"]["candidates"][0]["broker"] == "EQ-AAA"
        assert record["payload"]["versions"]["params"]
        # 直接读库确认表与列
        conn = sqlite3.connect(str(sqlite_db))
        try:
            count = conn.execute("SELECT COUNT(*) FROM routing_decisions").fetchone()[0]
        finally:
            conn.close()
        assert count == 1

    def test_load_filters_by_order(self, sqlite_db):
        first = decision_log_service.build_shadow_decision(_order(), _plan(), _proposals())
        other_order = SimpleNamespace(id="O-2", symbol="MSFT US Equity", side="SELL", exchange="US")
        second = decision_log_service.build_shadow_decision(other_order, _plan(), _proposals())
        assert asyncio.run(decision_log_service.record_decision(first)) is True
        assert asyncio.run(decision_log_service.record_decision(second)) is True

        assert len(asyncio.run(decision_log_service.load_decisions(order_id="O-1"))) == 1
        assert len(asyncio.run(decision_log_service.load_decisions())) == 2


class TestDegrade:
    """③ 降级：DB 不可用不抛、返回 False。"""

    def test_record_failure_returns_false(self, monkeypatch):
        def _boom():
            raise RuntimeError("db unavailable")

        monkeypatch.setattr("db.get_db_session", _boom)
        decision = decision_log_service.build_shadow_decision(_order(), _plan(), _proposals())
        assert asyncio.run(decision_log_service.record_decision(decision)) is False


class TestSwitch:
    """④ 开关（默认关闭）。"""

    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("EMSXVIEW_DECISION_LOG_ENABLED", raising=False)
        assert decision_log_service.decision_log_enabled() is False

    def test_enabled(self, monkeypatch):
        for value in ("1", "true", "TRUE", "yes"):
            monkeypatch.setenv("EMSXVIEW_DECISION_LOG_ENABLED", value)
            assert decision_log_service.decision_log_enabled() is True


class TestShadowDoesNotChangeProposals:
    """⑤ 影子方式不改变提案（开关开/关输出一致）。"""

    @pytest.mark.asyncio
    async def test_proposals_identical(self, monkeypatch, sqlite_db):
        from services.route_engine import RouteEngine

        def _alloc(broker, pct):
            return SimpleNamespace(
                allocation_type="PERCENTAGE",
                allocation_value=pct,
                broker=broker,
                strategy_params=None,
                order_type=None,
                limit_price=None,
                tif=None,
            )

        class _Repo:
            async def get_allocations_for_plan(self, plan_id):
                return [_alloc("EQ-AAA", 60.0), _alloc("EQ-BBB", 40.0)]

        engine = RouteEngine(_Repo())
        order = SimpleNamespace(
            id="O-9", symbol="AAPL US Equity", side="BUY", exchange="US",
            remainingQuantity=1000, broker="", orderType="LMT", price=100.0, timeInForce="DAY",
        )
        plan = SimpleNamespace(
            id=9, split_type="BROKER_SPLIT", participation_rate=0.1,
            default_broker="", default_order_type="LMT", default_tif="DAY",
            default_strategy_params={"PctVol": "10.0"},
        )

        monkeypatch.delenv("EMSXVIEW_DECISION_LOG_ENABLED", raising=False)
        baseline = await engine.generate_proposals(order, plan)
        monkeypatch.setenv("EMSXVIEW_DECISION_LOG_ENABLED", "true")
        with_logging = await engine.generate_proposals(order, plan)

        assert baseline == with_logging  # 提案逐字段一致（影子不改写）
        records = await decision_log_service.load_decisions(order_id="O-9")
        assert len(records) == 1

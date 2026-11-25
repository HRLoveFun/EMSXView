"""219（DL-25 第一批）：提交回写 decision_id / 改写原因 + 周报口径。"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("JWT_SECRET", "test-batch-prefill-secret-0123456789abcdef")

import pytest  # noqa: E402

from services import decision_log_service, shadow_weekly_service  # noqa: E402


def _order(order_id: str = "O-1") -> SimpleNamespace:
    return SimpleNamespace(id=order_id, symbol="AAPL US Equity", side="BUY")


def _plan() -> SimpleNamespace:
    return SimpleNamespace(id=7, split_type="BROKER_SPLIT", participation_rate=0.1)


def _proposals() -> list[dict]:
    return [{"broker": "A", "quantity": 100, "slice_index": 1, "strategy_params": {}}]


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


def _record(context: dict) -> str:
    decision = decision_log_service.build_shadow_decision(
        _order(), _plan(), _proposals(), context=context,
    )
    assert asyncio.run(decision_log_service.record_decision(decision)) is True
    return decision.decision_id


def test_link_submission_writes_decision_and_reason(sqlite_db) -> None:
    decision_id = _record({
        "actual_routes": [{"broker": "A", "quantity": 100}],
        "rewrite_reason": "UNCLASSIFIED",
    })

    assert asyncio.run(decision_log_service.link_submission(
        "O-1", decision_id=decision_id, rewrite_reason="BROKER_CHANGED",
    )) is True

    record = asyncio.run(decision_log_service.load_decisions(order_id="O-1"))[0]
    payload = record["payload"]
    assert payload["submission_decision_id"] == decision_id
    assert payload["trader_rewrite_reason"] == "BROKER_CHANGED"
    assert payload["submitted_at"]

    report = asyncio.run(shadow_weekly_service.weekly_report())
    assert report["totals"]["reason_counts"] == {"BROKER_CHANGED": 1}
    assert report["totals"]["trader_reason_counts"] == {"BROKER_CHANGED": 1}
    assert report["totals"]["trader_reason_coverage"] == 1.0


def test_link_submission_invalid_reason_is_ignored(sqlite_db) -> None:
    decision_id = _record({
        "actual_routes": [{"broker": "A", "quantity": 100}],
        "rewrite_reason": "QUANTITY_CHANGED",
    })

    assert asyncio.run(decision_log_service.link_submission(
        "O-1", decision_id=decision_id, rewrite_reason="NOT_A_REASON",
    )) is True

    payload = asyncio.run(decision_log_service.load_decisions(order_id="O-1"))[0]["payload"]
    assert "trader_rewrite_reason" not in payload
    assert payload["submission_decision_id"] == decision_id


def test_link_submission_unknown_decision_returns_false(sqlite_db) -> None:
    assert asyncio.run(decision_log_service.link_submission(
        "UNKNOWN", decision_id="missing", rewrite_reason="UNCHANGED",
    )) is False


def test_weekly_falls_back_to_route_reason_without_trader_reason(sqlite_db) -> None:
    _record({
        "actual_routes": [{"broker": "A", "quantity": 100}],
        "rewrite_reason": "EXTRA_ROUTE",
    })

    report = asyncio.run(shadow_weekly_service.weekly_report())
    assert report["totals"]["reason_counts"] == {"EXTRA_ROUTE": 1}
    assert report["totals"]["trader_reason_counts"] == {}
    assert report["totals"]["trader_reason_coverage"] == 0.0

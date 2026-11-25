"""057 DL-22/215：影子周报聚合测试。"""

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

os.environ.setdefault("JWT_SECRET", "test-shadow-weekly-secret-0123456789abcdef")

import pytest  # noqa: E402

from platform_data.contracts import (  # noqa: E402
    REWRITE_BROKER_CHANGED,
    REWRITE_UNCLASSIFIED,
    SOURCE_ENGINE,
    SOURCE_ENGINE_DEFAULT,
)
from services import decision_log_service, shadow_weekly_service  # noqa: E402


def _order(order_id: str = "O-1") -> SimpleNamespace:
    return SimpleNamespace(id=order_id, symbol="AAPL US Equity", side="BUY")


def _plan() -> SimpleNamespace:
    return SimpleNamespace(id=7, split_type="BROKER_SPLIT", participation_rate=0.1)


def _proposals(*items: tuple[str, int, float | None]) -> list[dict]:
    return [
        {"broker": broker, "quantity": qty, "slice_index": index,
         "strategy_params": {}, "estimated_cost_bps": cost}
        for index, (broker, qty, cost) in enumerate(items)
    ]


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


def _record(order_id, proposals, *, context=None):
    decision = decision_log_service.build_shadow_decision(
        _order(order_id), _plan(), proposals, context=context or {},
    )
    assert asyncio.run(decision_log_service.record_decision(decision)) is True


def test_weekly_report_metrics(sqlite_db) -> None:
    # D1：建议与实际完全一致
    _record("O-1", _proposals(("A", 600, None), ("B", 400, None)), context={
        "actual_routes": [{"broker": "A", "quantity": 600}, {"broker": "B", "quantity": 400}],
        "rewrite_reason": REWRITE_UNCLASSIFIED,
    })
    # D2：换券商 + 硬违例
    _record("O-2", _proposals(("A", 100, None)), context={
        "actual_routes": [{"broker": "B", "quantity": 100}],
        "rewrite_reason": REWRITE_BROKER_CHANGED,
        "constraint_violations": [{"code": "X", "severity": "BLOCK"}],
    })
    # D3：无匹配计划（无建议）
    decision = decision_log_service.build_shadow_decision(
        _order("O-3"), SimpleNamespace(id=None, split_type="", participation_rate=None), [],
        context={"source": SOURCE_ENGINE_DEFAULT, "rationale": "no_matching_plan"},
    )
    assert asyncio.run(decision_log_service.record_decision(decision)) is True
    # D4：有建议、无实际路由
    _record("O-4", _proposals(("A", 100, None)))
    # D5：带预期成本
    _record("O-5", _proposals(("A", 100, 8.0)))

    report = asyncio.run(shadow_weekly_service.weekly_report())
    totals = report["totals"]

    assert totals["decisions"] == 5
    assert totals["actual_linked"] == 2
    assert totals["agreed"] == 1
    assert totals["agreement_rate"] == 0.5
    assert totals["rewritten"] == 1
    assert totals["rewrite_rate"] == 0.5
    assert totals["reason_counts"] == {
        REWRITE_UNCLASSIFIED: 1, REWRITE_BROKER_CHANGED: 1,
    }
    assert totals["no_suggestion"] == 1
    assert totals["hard_violations"] == 1
    assert totals["by_source"] == {SOURCE_ENGINE: 4, SOURCE_ENGINE_DEFAULT: 1}
    assert totals["expected_cost"]["available"] is True
    assert totals["expected_cost"]["suggested_mean_bps"] == 8.0
    assert report["weeks"], "ISO week bucket expected"


def test_weekly_report_empty_range(sqlite_db) -> None:
    _record("O-1", _proposals(("A", 100, None)))

    report = asyncio.run(
        shadow_weekly_service.weekly_report("20240101", "20240102")
    )

    assert report["totals"]["decisions"] == 0
    assert report["totals"]["agreement_rate"] is None
    assert report["weeks"] == {}

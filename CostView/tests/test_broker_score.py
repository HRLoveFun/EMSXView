"""217（DL-24）BrokerScoreSnapshot 与分项得分测试。"""

from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from CostView.src.evaluation.broker_score import build_broker_scores
from CostView.src.evaluation.governance import assert_governance_complete
from CostView.src.evaluation.ranking import rank_brokers
from CostView.src.evaluation.report import build_evaluation_report
from platform_data.contracts import (
    BROKER_SCORE_VERSION,
    BrokerScoreSnapshot,
    ScoreComponent,
)


def _route(
    broker: str,
    day: str,
    cost: float,
    *,
    fill: float = 500.0,
    shares: float = 1000.0,
    fill_count: int = 1,
    opportunity: float = 0.0,
    **overrides,
) -> SimpleNamespace:
    base = {
        "Broker": broker,
        "order_as_of_date": day,
        "arrival_cost_bps": cost,
        "fill": fill,
        "RouteShares": shares,
        "fill_count": fill_count,
        "opportunity_cost": opportunity,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _synthetic(days: int = 10, per_day: int = 5):
    routes = []
    for day in range(days):
        for _ in range(per_day):
            routes.append(_route("A", f"202611{day + 1:02d}", 5.0, opportunity=1.0))
            routes.append(_route("B", f"202611{day + 1:02d}", 9.0, fill=400.0,
                                 fill_count=0, opportunity=3.0))
    return routes


def _score(routes, ranking, spec_version: str = "2026.11.25e"):
    return build_broker_scores(
        routes,
        ranking,
        as_of="2026-11-25T12:00:00+00:00",
        window_start="20261101",
        window_end="20261130",
        spec_version=spec_version,
    )


def test_contract_defaults() -> None:
    component = ScoreComponent(
        name="cost", value=5.0, unit="bps", sample_size=10, available=True,
    )
    snapshot = BrokerScoreSnapshot(
        broker="A", as_of="2026-11-25T12:00:00+00:00",
        window_start="20261101", window_end="20261130",
    )
    payload = asdict(snapshot)
    assert payload["spec_version"] == BROKER_SCORE_VERSION
    assert payload["weights"] == {}
    assert payload["composite"] is None
    assert component.available is True


def test_build_broker_scores_components_and_governance() -> None:
    routes = _synthetic()
    ranking = rank_brokers(routes, n_boot=50, simulations=100, seed=7)

    payload = _score(routes, ranking)

    assert payload["available"] is True
    assert payload["schema_version"] == BROKER_SCORE_VERSION
    assert payload["coverage"]["brokers"] == 2
    assert_governance_complete(payload["governance"])

    snapshots = {snapshot["broker"]: snapshot for snapshot in payload["snapshots"]}
    components = {
        component["name"]: component for component in snapshots["A"]["components"]
    }
    assert components["cost"]["value"] == pytest.approx(
        next(unit for unit in ranking["units"] if unit["broker"] == "A")["posterior_mean"]
    )
    assert components["completion"]["value"] == pytest.approx(0.5)
    assert components["operational"]["value"] == pytest.approx(1.0)
    assert components["opportunity_cost"]["value"] == pytest.approx(1.0)
    assert components["leakage"]["available"] is False
    assert components["leakage"]["value"] is None

    components_b = {
        component["name"]: component for component in snapshots["B"]["components"]
    }
    assert components_b["operational"]["value"] == pytest.approx(0.0)
    assert snapshots["A"]["composite"] is None
    assert snapshots["A"]["weights"] == {}


def test_cusum_alerts_on_step_shift_and_not_on_stable() -> None:
    routes = []
    for day in range(20):
        cost = 5.0 if day < 10 else 25.0
        for _ in range(5):
            routes.append(_route("DRIFT", f"202611{day + 1:02d}", cost))
            routes.append(_route("STABLE", f"202611{day + 1:02d}", 5.0 + (day % 2) * 0.1))
    ranking = rank_brokers(routes, n_boot=50, simulations=100, seed=7)
    payload = _score(routes, ranking)
    snapshots = {snapshot["broker"]: snapshot for snapshot in payload["snapshots"]}

    assert snapshots["DRIFT"]["cusum"]["alert"] is True
    assert snapshots["DRIFT"]["cusum"]["direction"] in {"up", "down"}
    assert snapshots["STABLE"]["cusum"]["alert"] is False


def test_misaligned_samples_are_separated() -> None:
    routes = _synthetic(days=5, per_day=2)
    routes.append(_route("A", "", 99.0))
    ranking = rank_brokers(routes, n_boot=50, simulations=100, seed=7)

    payload = _score(routes, ranking)
    snapshot_a = next(item for item in payload["snapshots"] if item["broker"] == "A")
    assert snapshot_a["misaligned_samples"] == 1
    assert payload["coverage"]["misaligned_samples"] == 1


def test_empty_routes() -> None:
    payload = _score([], rank_brokers([]))
    assert payload["available"] is False
    assert payload["snapshots"] == []
    assert_governance_complete(payload["governance"])


def test_report_includes_broker_scores_section() -> None:
    payload = build_evaluation_report([], {})
    assert "broker_scores" in payload["sections"]
    assert payload["sections"]["broker_scores"]["available"] is False

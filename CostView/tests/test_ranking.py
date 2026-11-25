"""216（DL-23）聚类推断与收缩排名测试。"""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from CostView.src.evaluation import ranking
from CostView.src.evaluation.report import build_evaluation_report


def _route(broker: str, day: str, cost: float, **overrides) -> SimpleNamespace:
    base = {
        "Broker": broker,
        "order_as_of_date": day,
        "arrival_cost_bps": cost,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_cluster_robust_mean_larger_than_iid_when_clustered() -> None:
    values: list[float] = []
    clusters: list[str] = []
    for day, shock in enumerate([10.0, -10.0, 5.0, -5.0, 0.0]):
        for index in range(5):
            values.append(shock + index * 0.1)
            clusters.append(f"D{day}")

    mean, cluster_se, clustered = ranking.cluster_robust_mean(values, clusters)
    _, iid_se, _ = ranking.cluster_robust_mean(
        values, [f"O{index}" for index in range(len(values))]
    )

    assert clustered is True
    assert mean == pytest.approx(0.2)
    assert cluster_se is not None and iid_se is not None
    assert cluster_se > iid_se


def test_cluster_robust_mean_falls_back_with_one_cluster() -> None:
    mean, se, clustered = ranking.cluster_robust_mean([1.0, 2.0, 3.0], ["D1", "D1", "D1"])
    assert clustered is False
    assert mean == pytest.approx(2.0)
    assert se == pytest.approx(1.0 / (3 ** 0.5))


def test_block_bootstrap_reproducible() -> None:
    values = [1.0, 2.0, 3.0, 10.0, 11.0, 12.0]
    clusters = ["D1", "D1", "D1", "D2", "D2", "D2"]
    first = ranking.block_bootstrap_ci(values, clusters, n_boot=200, seed=7)
    second = ranking.block_bootstrap_ci(values, clusters, n_boot=200, seed=7)
    assert first == second
    assert first[0] is not None and first[1] is not None and first[0] <= first[1]


def test_dersimonian_laird_zero_tau() -> None:
    pooled = ranking.dersimonian_laird([10.0, 10.0], [1.0, 1.0])
    assert pooled["tau2"] == 0.0
    assert pooled["mu"] == pytest.approx(10.0)


def test_dersimonian_laird_heterogeneity() -> None:
    pooled = ranking.dersimonian_laird([5.0, 15.0], [1.0, 1.0])
    assert pooled["tau2"] > 0
    assert pooled["mu"] == pytest.approx(10.0, abs=0.5)


def test_shrink_estimates_pulls_noisy_unit() -> None:
    units = [
        {"broker": "A", "mean": 5.0, "se": 0.1, "n": 100, "days": 20},
        {"broker": "B", "mean": 10.0, "se": 5.0, "n": 5, "days": 5},
    ]
    shrunk, pooled = ranking.shrink_estimates(units)
    by_broker = {unit["broker"]: unit for unit in shrunk}
    assert pooled["mu"] is not None
    assert by_broker["B"]["posterior_mean"] is not None
    assert by_broker["B"]["posterior_mean"] < 10.0
    assert by_broker["B"]["posterior_mean"] >= pooled["mu"] - 1e-9


def test_p_top_k_is_directional_and_sums_to_k() -> None:
    units = [
        {"posterior_mean": 1.0, "posterior_sd": 0.1},
        {"posterior_mean": 2.0, "posterior_sd": 0.1},
        {"posterior_mean": 3.0, "posterior_sd": 0.1},
    ]
    probabilities = ranking.p_top_k(units, top_k=2, simulations=500, seed=7)
    assert probabilities[0] == pytest.approx(1.0)
    assert probabilities[1] == pytest.approx(1.0)
    assert probabilities[2] == pytest.approx(0.0)
    assert sum(probabilities) == pytest.approx(2.0, abs=0.05)


def _synthetic_routes(brokers: dict[str, float], days: int = 30, per_day: int = 8):
    rng = random.Random(20261125)
    routes = []
    for day in range(days):
        shock = rng.gauss(0.0, 2.0)
        for broker, true_mean in brokers.items():
            for _ in range(per_day):
                value = true_mean + shock + rng.gauss(0.0, 1.0)
                routes.append(_route(broker, f"202611{day + 1:02d}", value))
    return routes


def test_rank_brokers_recovers_order_and_is_reproducible() -> None:
    routes = _synthetic_routes({"A": 5.0, "B": 7.0, "C": 9.0, "D": 11.0, "E": 14.0})

    first = ranking.rank_brokers(
        routes, metric="arrival_cost_bps", n_boot=200, simulations=1000, seed=7,
    )
    second = ranking.rank_brokers(
        routes, metric="arrival_cost_bps", n_boot=200, simulations=1000, seed=7,
    )

    assert first["available"] is True
    assert [unit["broker"] for unit in first["units"]] == ["A", "B", "C", "D", "E"]
    assert first["units"][0]["p_top_k"] > first["units"][-1]["p_top_k"]
    assert first["coverage"]["routes"] == len(routes)
    assert first["indistinguishable"]
    assert [unit["posterior_mean"] for unit in first["units"]] == [
        unit["posterior_mean"] for unit in second["units"]
    ]
    assert [unit["p_top_k"] for unit in first["units"]] == [
        unit["p_top_k"] for unit in second["units"]
    ]


def test_rank_brokers_excludes_provisional_and_flags_low_sample() -> None:
    routes = _synthetic_routes({"A": 5.0}, days=5, per_day=2)
    routes.append(_route("A", "20261122", 99.0, is_provisional=True))
    routes.extend(_route("NEW", f"202611{day:02d}", 8.0) for day in range(1, 3))

    result = ranking.rank_brokers(routes, n_boot=50, simulations=100, seed=7)

    assert result["coverage"]["excluded_non_formal"] == 1
    new_unit = next(unit for unit in result["units"] if unit["broker"] == "NEW")
    assert new_unit["low_sample"] is True
    assert new_unit["n"] == 2


def test_rank_brokers_empty() -> None:
    result = ranking.rank_brokers([])
    assert result["available"] is False
    assert result["units"] == []


def test_report_includes_ranking_section() -> None:
    payload = build_evaluation_report([], {})
    assert "ranking" in payload["sections"]
    assert payload["sections"]["ranking"]["available"] is False

"""213（DL-20）订单内配对评估 D1 的单元测试。"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from CostView.src.evaluation import pairing
from CostView.src.evaluation.report import build_evaluation_report
from CostView.src.monitoring import report_spec
from CostView.src.monitoring.env_context import RouteEnvContext, env_route_key


def _route(
    order: str = "O1",
    route_id: str = "R1",
    date: str = "20260418",
    broker: str = "A",
    cost: Any = 5.0,
    fill: Any = 100.0,
    p_avg: Any = 10.0,
    shares: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        OrderId=order,
        RouteId=route_id,
        order_as_of_date=date,
        Broker=broker,
        arrival_cost_bps=cost,
        fill=fill,
        p_avg=p_avg,
        RouteShares=shares,
    )


def _key(route: SimpleNamespace) -> tuple[str, str, str]:
    return env_route_key(route.OrderId, route.RouteId, route.order_as_of_date)


def _env(routes: list[SimpleNamespace], times: list[str]) -> dict[Any, RouteEnvContext]:
    return {
        _key(route): RouteEnvContext(start_time=time)
        for route, time in zip(routes, times)
    }


def _group(routes: list[SimpleNamespace]) -> pairing.PairGroup:
    return pairing.PairGroup(
        group_id="O1|20260418|10:00:00",
        order_id="O1",
        order_as_of_date="20260418",
        window_start="10:00:00",
        routes=list(routes),
        brokers=tuple(sorted({route.Broker for route in routes})),
    )


def test_pair_groups_requires_two_brokers_and_window() -> None:
    within = [_route(route_id="R1", broker="A"), _route(route_id="R2", broker="B")]
    groups, excluded = pairing.pair_groups(within, _env(within, ["10:00:00", "10:01:00"]))
    assert len(groups) == 1
    assert groups[0].brokers == ("A", "B")
    assert excluded == {"no_time": 0, "single_broker_orders": 0}

    outside = [_route(route_id="R1", broker="A"), _route(route_id="R2", broker="B")]
    groups, excluded = pairing.pair_groups(outside, _env(outside, ["10:00:00", "10:06:00"]))
    assert groups == []
    assert excluded["single_broker_orders"] == 1

    single = [_route(route_id="R1", broker="A"), _route(route_id="R2", broker="A")]
    groups, excluded = pairing.pair_groups(single, _env(single, ["10:00:00", "10:01:00"]))
    assert groups == []
    assert excluded["single_broker_orders"] == 1


def test_pair_groups_missing_time_is_excluded() -> None:
    routes = [_route(route_id="R1", broker="A"), _route(route_id="R2", broker="B")]
    env = {
        _key(routes[0]): RouteEnvContext(),
        _key(routes[1]): RouteEnvContext(start_time="10:00:00"),
    }
    groups, excluded = pairing.pair_groups(routes, env)
    assert groups == []
    assert excluded["no_time"] == 1


def test_relative_cost_weighted_mean() -> None:
    equal = _group([
        _route(broker="A", cost=5.0, fill=100.0),
        _route(route_id="R2", broker="B", cost=10.0, fill=100.0),
    ])
    rows = pairing.relative_costs(equal)
    assert [row["relative_cost_bps"] for row in rows] == [-2.5, 2.5]

    skewed = _group([
        _route(broker="A", cost=5.0, fill=300.0),
        _route(route_id="R2", broker="B", cost=10.0, fill=100.0),
    ])
    rows = pairing.relative_costs(skewed)
    assert rows[0]["relative_cost_bps"] == pytest.approx(-1.25)
    assert rows[1]["relative_cost_bps"] == pytest.approx(3.75)


def test_relative_cost_requires_weight() -> None:
    group = _group([
        _route(broker="A", cost=5.0, p_avg=None),
        _route(route_id="R2", broker="B", cost=10.0, p_avg=None),
    ])
    assert pairing.relative_costs(group) == []


def test_wilcoxon_and_sign_detect_effect() -> None:
    diffs = [-5.0] * 12
    wilcoxon = pairing.wilcoxon_signed_rank(diffs)
    signs = pairing.sign_test(diffs)
    assert wilcoxon["n"] == 12
    assert wilcoxon["p_value"] is not None and wilcoxon["p_value"] < 0.05
    assert signs["n"] == 12 and signs["negative"] == 12
    assert signs["p_value"] is not None and signs["p_value"] < 0.05


def test_broker_pair_tests() -> None:
    routes: list[SimpleNamespace] = []
    times: list[str] = []
    for index in range(12):
        routes.append(_route(order=f"O{index}", route_id="R1", broker="A", cost=5.0))
        times.append("10:00:00")
        routes.append(_route(order=f"O{index}", route_id="R2", broker="B", cost=10.0))
        times.append("10:01:00")
    groups, _ = pairing.pair_groups(routes, _env(routes, times))
    rows = [row for group in groups for row in pairing.relative_costs(group)]

    results = pairing.broker_pair_tests(rows, min_pairs=10)

    assert len(results) == 1
    pair = results[0]
    assert pair["pairs"] == 12
    assert pair["median_diff_bps"] == pytest.approx(-5.0)
    assert pair["wilcoxon"]["p_value"] < 0.05


def test_fixed_effects_recovers_broker_effect() -> None:
    routes: list[SimpleNamespace] = []
    times: list[str] = []
    for index in range(20):
        share_a = 0.2 + 0.03 * index
        share_b = 1.0 - share_a
        base = 10.0 + index * 0.1
        routes.append(_route(
            order=f"O{index}", route_id="R1", broker="A",
            cost=base + 2.0 * share_a, shares=share_a,
        ))
        times.append("10:00:00")
        routes.append(_route(
            order=f"O{index}", route_id="R2", broker="B",
            cost=base + 5.0 + 2.0 * share_b, shares=share_b,
        ))
        times.append("10:01:00")
    groups, _ = pairing.pair_groups(routes, _env(routes, times))
    rows = [row for group in groups for row in pairing.relative_costs(group)]

    result = pairing.fixed_effects_broker_effects(rows, min_groups=10)

    assert result["available"] is True
    assert result["reference_broker"] == "A"
    effect_b = next(item for item in result["effects"] if item["broker"] == "B")
    assert effect_b["coefficient_bps"] == pytest.approx(5.0, abs=1.0)
    assert result["share_coefficient_bps_per_share"] == pytest.approx(2.0, abs=1.0)


def test_d1_section_coverage_and_spec_binding() -> None:
    routes: list[SimpleNamespace] = []
    times: list[str] = []
    for index in range(3):
        routes.append(_route(order=f"O{index}", route_id="R1", broker="A", cost=5.0))
        times.append("10:00:00")
        routes.append(_route(order=f"O{index}", route_id="R2", broker="B", cost=10.0))
        times.append("10:01:00")
    # 一个单券商订单（不计入候选）
    routes.append(_route(order="SINGLE", route_id="R1", broker="A"))
    times.append("10:00:00")

    section = pairing.d1_section(routes, _env(routes, times))

    assert section["coverage"]["total_orders"] == 4
    assert section["coverage"]["candidate_orders"] == 3
    assert section["coverage"]["groups"] == 3
    assert section["coverage"]["brokers"] == 2
    assert section["excluded"]["single_broker_orders"] == 1

    spec = report_spec.REPORT_SPEC["pairing"]
    assert spec["min_brokers"] == pairing.PAIR_MIN_BROKERS
    assert spec["max_spread_minutes"] == pairing.PAIR_MAX_SPREAD_MINUTES
    assert spec["cost_key"] == pairing.DEFAULT_COST_KEY
    assert spec["weight_expression"] == pairing.COST_WEIGHT_EXPRESSION


def test_d1_section_empty_is_safe() -> None:
    section = pairing.d1_section([], {})
    assert section["coverage"]["groups"] == 0
    assert section["relative_cost"]["n"] == 0
    assert section["broker_pair_tests"] == []
    assert section["fixed_effects"]["available"] is False


def test_evaluation_report_includes_pairing_section() -> None:
    payload = build_evaluation_report([], {})
    assert "pairing" in payload["sections"]
    assert payload["sections"]["pairing"]["coverage"]["groups"] == 0

"""TcaOrderAggregate 聚合逻辑单元测试（003-tca-core-benchmarks Phase 2）。

覆盖 plan.md §3.2 的 route→order 聚合策略：
- 货币成本 SUM
- 价格基准取最早 route
- bps 成交额加权平均
- 完成率求和比
- 风险取 max
"""
from __future__ import annotations

import pytest

from platform_data.contracts import TcaOrderAggregate
from CostView.src.tca_query_service import TcaQueryService


def _make_route(**overrides) -> dict:
    """构造一条 tca_route_summary 行（默认买入完整成交）。"""
    row = {
        "OrderId": "O1", "RouteId": "R1", "order_as_of_date": "20260421",
        "equ_ticker": "AAPL US Equity", "Exchange": "US", "Side": "Buy",
        "Broker": "BRK", "algo": "VWAP", "TraderName": "TRADER",
        "fill_count": 1, "fill": 1000.0, "RouteShares": 1000.0,
        "p_avg": 10.0,
        "p_arrival": 9.9, "p_decision": 9.9, "p_close": 10.1,
        "arrival_cost_bps": 10.0, "close_cost_bps": -20.0, "wagner_is_bps": -10.0,
        "delay_cost": 0.0, "trading_cost": 100.0, "opportunity_cost": 0.0,
        "wagner_is": 100.0,
        "temp_impact_5min_bps": 5.0, "perm_impact_bps": 8.0,
        "cost_stddev": 1.0, "cost_p95": 2.0, "cost_cvar": 2.5,
        "order_duration_sec": 600.0,
        "recovery_truncated": 0,
    }
    row.update(overrides)
    return row


class TestOrderAggregation:
    """order 聚合策略测试。"""

    def test_single_route_passthrough(self) -> None:
        """单 route 订单聚合后值应与 route 一致。"""
        route = _make_route()
        agg = TcaQueryService._aggregate_order("O1", "20260421", [route])

        assert isinstance(agg, TcaOrderAggregate)
        assert agg.route_count == 1
        assert agg.delay_cost == pytest.approx(0.0)
        assert agg.trading_cost == pytest.approx(100.0)
        assert agg.wagner_is == pytest.approx(100.0)
        assert agg.fill == pytest.approx(1000.0)
        assert agg.par_rate == pytest.approx(1.0)

    def test_currency_cost_sum(self) -> None:
        """货币成本跨 route SUM。"""
        r1 = _make_route(RouteId="R1", delay_cost=10.0, trading_cost=100.0, opportunity_cost=5.0, wagner_is=115.0)
        r2 = _make_route(RouteId="R2", delay_cost=20.0, trading_cost=50.0, opportunity_cost=0.0, wagner_is=70.0)
        agg = TcaQueryService._aggregate_order("O1", "20260421", [r1, r2])

        assert agg.delay_cost == pytest.approx(30.0)
        assert agg.trading_cost == pytest.approx(150.0)
        assert agg.opportunity_cost == pytest.approx(5.0)
        assert agg.wagner_is == pytest.approx(185.0)
        assert agg.route_count == 2

    def test_turnover_weighted_bps(self) -> None:
        """bps 绩效按成交额加权平均（权重 = fill × p_avg）。"""
        # route1: fill=1000, p_avg=10, weight=10000, bps=10
        r1 = _make_route(RouteId="R1", fill=1000.0, p_avg=10.0, arrival_cost_bps=10.0)
        # route2: fill=3000, p_avg=10, weight=30000, bps=30
        r2 = _make_route(RouteId="R2", fill=3000.0, p_avg=10.0, arrival_cost_bps=30.0)
        agg = TcaQueryService._aggregate_order("O1", "20260421", [r1, r2])

        # (10*10000 + 30*30000) / (10000+30000) = (100000+900000)/40000 = 25
        assert agg.arrival_cost_bps == pytest.approx(25.0, abs=0.01)

    def test_fill_rate_sum_ratio(self) -> None:
        """完成率 = Σfill / Σroute_shares。"""
        r1 = _make_route(RouteId="R1", fill=500.0, RouteShares=1000.0)
        r2 = _make_route(RouteId="R2", fill=1500.0, RouteShares=2000.0)
        agg = TcaQueryService._aggregate_order("O1", "20260421", [r1, r2])

        assert agg.fill == pytest.approx(2000.0)
        assert agg.route_shares == pytest.approx(3000.0)
        assert agg.par_rate == pytest.approx(2000.0 / 3000.0)

    def test_risk_takes_max(self) -> None:
        """风险指标 order 取 max（保守）。"""
        r1 = _make_route(RouteId="R1", cost_stddev=1.0, cost_p95=2.0, cost_cvar=2.5)
        r2 = _make_route(RouteId="R2", cost_stddev=3.0, cost_p95=4.0, cost_cvar=4.5)
        agg = TcaQueryService._aggregate_order("O1", "20260421", [r1, r2])

        assert agg.cost_stddev == pytest.approx(3.0)
        assert agg.cost_p95 == pytest.approx(4.0)
        assert agg.cost_cvar == pytest.approx(4.5)

    def test_price_benchmark_first_route(self) -> None:
        """价格基准取第一条 route（稳定排序）。"""
        r1 = _make_route(RouteId="R1", p_arrival=9.9, p_decision=9.9, p_close=10.1)
        r2 = _make_route(RouteId="R2", p_arrival=9.5, p_decision=9.5, p_close=10.5)
        agg = TcaQueryService._aggregate_order("O1", "20260421", [r1, r2])

        assert agg.p_arrival == pytest.approx(9.9)
        assert agg.p_decision == pytest.approx(9.9)
        assert agg.p_close == pytest.approx(10.1)

    def test_exec_rate_recomputed(self) -> None:
        """执行速率在 order 层重算 = Σfill / (duration/60)。"""
        r1 = _make_route(RouteId="R1", fill=1000.0, order_duration_sec=600.0)
        r2 = _make_route(RouteId="R2", fill=2000.0, order_duration_sec=1200.0)
        agg = TcaQueryService._aggregate_order("O1", "20260421", [r1, r2])

        # duration 取 max=1200，fill=3000 → rate = 3000/(1200/60) = 150
        assert agg.exec_rate_shares_per_min == pytest.approx(150.0, abs=0.1)

    def test_nan_cleaned(self) -> None:
        """NaN 值被清理为 None。"""
        r = _make_route(trading_cost=float("nan"))
        agg = TcaQueryService._aggregate_order("O1", "20260421", [r])

        assert agg.trading_cost is None
        assert agg.wagner_is == pytest.approx(100.0)  # 其他字段不受影响

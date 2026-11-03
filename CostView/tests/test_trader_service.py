"""trader_service 测试（PR-1）：分页组装 / 日期默认 / 校验 / 与 analyze-orders 对账 100 单。"""

from __future__ import annotations

import pytest

from CostView.src import trader_service
from CostView.src.trader_models import TraderFilters
from CostView.tests.trader_fixtures import make_manager

_CONTRACT_KEYS = {
    "filters", "generated_at", "total_orders", "offset", "limit",
    "kpi", "probes", "orders",
}


def _rows_fixture() -> list[dict]:
    return [
        {"OrderId": "M1", "RouteId": "R1", "fill": 700.0, "RouteShares": 1000.0,
         "Amount": 1000.0, "p_avg": 100.0, "fill_count": 4},
        {"OrderId": "M1", "RouteId": "R2", "fill": 200.0, "RouteShares": 500.0,
         "Amount": 500.0, "p_avg": 110.0, "fill_count": 2,
         "order_as_of_date": "20261022"},
        {"OrderId": "S1", "fill": 900.0, "fill_count": 3,
         "order_as_of_date": "20261021"},
        {"OrderId": "S2", "fill": 100.0, "RouteShares": 1000.0,
         "fill_count": 1, "order_as_of_date": "20261020"},
    ]


class TestOrderPage:
    def test_payload_contract_and_slicing(self, tmp_path):
        mgr = make_manager(tmp_path, _rows_fixture())
        filters = TraderFilters(
            start_date="20261020", end_date="20261022", limit=2, offset=1,
            sort="date", sort_dir="desc",
        )
        payload = trader_service.build_order_page(filters, mgr=mgr)

        assert set(payload) == _CONTRACT_KEYS
        assert payload["total_orders"] == 3
        assert payload["offset"] == 1 and payload["limit"] == 2
        # date desc：M1(22) / S1(21) / S2(20) → offset=1 取后两条
        assert [o["order_id"] for o in payload["orders"]] == ["S1", "S2"]
        assert set(payload["kpi"]) >= {"orders", "low_completion_ratio", "anomaly_orders"}
        checks = payload["probes"]["checks"]
        assert [c["id"] for c in checks] == [
            "quantity", "participation", "cost_missing", "fill_quality",
        ]
        assert payload["probes"]["spec_version"] == trader_service.TRADER_SPEC_VERSION

    def test_date_defaults_recent_trading_days(self, tmp_path):
        mgr = make_manager(tmp_path, [
            {"OrderId": f"A{i}", "order_as_of_date": f"202610{20 + i}"}
            for i in range(6)
        ])
        payload = trader_service.build_order_page_from_query(mgr=mgr)

        # 最近 5 个交易日 = 20261021..20261025（20261020 落在窗口外）
        assert payload["filters"]["start_date"] == "20261021"
        assert payload["filters"]["end_date"] == "20261025"
        assert payload["total_orders"] == 5

    def test_empty_db_raises_data_not_ready(self, tmp_path):
        mgr = make_manager(tmp_path, [])
        with pytest.raises(trader_service.DataNotReadyError):
            trader_service.build_order_page_from_query(mgr=mgr)

    def test_explicit_dates_empty_returns_zero_orders(self, tmp_path):
        mgr = make_manager(tmp_path, _rows_fixture())
        payload = trader_service.build_order_page_from_query(
            mgr=mgr, start_date="20270101", end_date="20270131",
        )
        assert payload["total_orders"] == 0
        assert payload["orders"] == []
        assert payload["kpi"]["orders"]["value"] == 0.0

    @pytest.mark.parametrize("kwargs,match", [
        ({"limit": 201}, "limit"),
        ({"offset": -1}, "offset"),
        ({"sort": "hack"}, "sort"),
        ({"sort_dir": "up"}, "sort_dir"),
        ({"completion_bucket": "lt90"}, "completion_bucket"),
        ({"quality": "bad"}, "quality"),
    ])
    def test_validation_errors(self, tmp_path, kwargs, match):
        mgr = make_manager(tmp_path, _rows_fixture())
        with pytest.raises(ValueError, match=match):
            trader_service.build_order_page_from_query(
                mgr=mgr, start_date="20261020", end_date="20261022", **kwargs,
            )


class TestReconcileWithAnalyzeOrders:
    """出口条件：聚合口径与 analyze-orders（TcaQueryService.build_order_report）对账 100 单。"""

    @staticmethod
    def _fixture_rows() -> list[dict]:
        rows: list[dict] = []
        for i in range(100):
            order_id = f"O{i:03d}"
            route_count = 1 + (i % 3)          # 1..3 条路由
            for r in range(route_count):
                rows.append({
                    "OrderId": order_id, "RouteId": f"R{r + 1}",
                    "fill": 100.0 * (r + 1) + i, "RouteShares": 500.0 + 10 * r,
                    "p_avg": 10.0 + 0.5 * r, "fill_count": 2 + r,
                    "arrival_cost_bps": -1.0 * (r + 1), "wagner_is_bps": -3.0 * (r + 1),
                    "opportunity_cost": -5.0 * (r + 1), "wagner_is": -20.0 * (r + 1),
                    "cost_cvar": 2.0 + r, "order_duration_sec": 60.0 * (r + 1),
                })
        return rows

    def test_100_orders_match_aggregate_semantics(self, tmp_path):
        from data_access.storage.connection import AccessTier
        from platform_data.contracts import TcaFilters
        from CostView.src import trader_query as tq
        from CostView.src.tca_query_service import TcaQueryService

        mgr = make_manager(tmp_path, self._fixture_rows())
        filters = TraderFilters(start_date="20261022", end_date="20261022", limit=200)
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        try:
            raw_rows = {r["OrderId"]: r for r in tq.query_order_rows(conn, filters)}
        finally:
            conn.close()
        payload_rows = {
            r["order_id"]: r for r in trader_service.build_order_page(filters, mgr=mgr)["orders"]
        }
        aggregates = {
            a.OrderId: a for a in TcaQueryService(connection_manager=mgr).build_order_report(
                TcaFilters(start_date="20261022", end_date="20261022",
                           aggregation="aggregated", limit=500),
            )
        }

        assert len(raw_rows) == 100
        assert set(raw_rows) == set(aggregates)
        for order_id, row in raw_rows.items():
            agg = aggregates[order_id]
            assert row["fill_count"] == agg.fill_count
            assert row["route_count"] == agg.route_count
            assert row["fill"] == pytest.approx(agg.fill)
            assert row["route_shares"] == pytest.approx(agg.route_shares)
            assert row["completion"] == pytest.approx(agg.par_rate)
            assert row["arrival_cost_bps"] == pytest.approx(agg.arrival_cost_bps)
            assert row["wagner_is_bps"] == pytest.approx(agg.wagner_is_bps)
            assert row["opportunity_cost"] == pytest.approx(agg.opportunity_cost)
            assert row["cost_cvar"] == pytest.approx(agg.cost_cvar)
            assert row["order_duration_sec"] == pytest.approx(agg.order_duration_sec)
            # 列表 payload 与 SQL 聚合同值（契约字段同源）
            assert payload_rows[order_id]["fill"] == pytest.approx(row["fill"])
            assert payload_rows[order_id]["arrival_cost_bps"] == pytest.approx(
                row["arrival_cost_bps"],
            )

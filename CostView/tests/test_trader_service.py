"""trader_service 测试（PR-1）：分页组装 / 日期默认 / 校验 / 与 analyze-orders 对账 100 单。"""

from __future__ import annotations

import pytest

from CostView.src import trader_service
from CostView.src.trader_models import TraderFilters
from CostView.tests.trader_fixtures import make_manager

_CONTRACT_KEYS = {
    "filters", "generated_at", "total_orders", "offset", "limit",
    "kpi", "probes", "anomaly_summary", "orders",
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


class TestAnomalySummaryPayload:
    """210 §4.11：订单级异常摘要随列表 payload 下发，KPI 与摘要同口径。"""

    def test_default_rules_apply_at_order_level(self, tmp_path) -> None:
        mgr = make_manager(tmp_path, [
            # completion 0.5 → fill_pct 命中 critical（严重未完成）
            {"OrderId": "LOW", "fill": 500.0, "par_rate": 0.01},
            {"OrderId": "FULL", "fill": 1000.0, "par_rate": 0.01},
        ])
        filters = TraderFilters(start_date="20261022", end_date="20261022")
        payload = trader_service.build_order_page(filters, mgr=mgr)
        summary = payload["anomaly_summary"]

        assert summary["orders_total"] == 1
        assert summary["critical"] == 1
        assert [item["key"] for item in summary["by_rule"]] == ["fill_pct"]
        assert summary["top_orders"][0]["order_id"] == "LOW"
        assert summary["top_orders"][0]["reasons"][0]["key"] == "fill_pct"
        # KPI 与摘要同一并集口径（不再只数 overfill/cost_missing）
        assert payload["kpi"]["anomaly_orders"]["value"] == summary["orders_total"]
        assert payload["probes"]["spec_version"] == "2026.11.04"

    def test_order_level_skips_route_only_metrics(self, tmp_path) -> None:
        """区间/逐笔类规则在订单层不评估：不会因缺字段而误报或崩溃。"""
        mgr = make_manager(tmp_path, [
            {"OrderId": "P1", "par_rate_continuous": 0.9, "pnl_vwap_continuous": 5.0,
             "RPM": 3.0, "par_rate": 0.01, "fill": 1000.0},
        ])
        filters = TraderFilters(start_date="20261022", end_date="20261022")
        summary = trader_service.build_order_page(filters, mgr=mgr)["anomaly_summary"]

        keys = {item["key"] for item in summary["by_rule"]}
        assert "volume_pct_interval" not in keys
        assert "intraday_volatility" not in keys
        assert "price_movement_pct" not in keys
        assert "订单级口径" in summary["note"]


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


# ── PR-2：订单详情 / 逐桶参与率 / 成本分解 / 逐笔补列 ────────────────────────


def _detail_fixture() -> dict:
    """单路由 VWAP 订单 D1：桶/参与率/成本/延迟全可算（含 unknown Liquidity 40%）。"""
    route = {
        "OrderId": "D1", "RouteId": "R1", "fill": 1000.0, "RouteShares": 1000.0,
        "fill_count": 3, "par_rate": 0.1, "p_avg": 150.0, "p_arrival": 149.0,
        "p_decision": 100.0, "p_close": 151.0, "algo": "vwap",
        "delay_cost": -100.0, "trading_cost": -200.0, "opportunity_cost": -50.0,
        "wagner_is": -350.0, "wagner_is_bps": -35.0, "arrival_cost_bps": -4.0,
    }
    fills = [
        {"OrderId": "D1", "fill_id": "F1", "exec_time": "09:31:00",
         "price": 150.0, "shares": 300.0},
        {"OrderId": "D1", "fill_id": "F2", "exec_time": "09:36:00",
         "price": 150.0, "shares": 300.0},
        {"OrderId": "D1", "fill_id": "F3", "exec_time": "09:41:00",
         "price": 150.0, "shares": 400.0},
    ]
    raw = [
        {"OrderId": "D1", "fill_id": "F1", "liquidity": "1"},
        {"OrderId": "D1", "fill_id": "F2", "liquidity": "2"},
        {"OrderId": "D1", "fill_id": "F3", "liquidity": "Z"},
    ]
    bars = [
        {"ts": "09:31:10", "volume": 3000.0},
        {"ts": "09:36:10", "volume": 3000.0},
        {"ts": "09:41:10", "volume": 4000.0},
    ]
    return {"route": route, "fills": fills, "raw": raw, "bars": bars}


def _make_detail_manager(tmp_path, fixture: dict, extra_rows=None, extra_fills=None):
    rows = [fixture["route"]] + (extra_rows or [])
    fills = [
        {"OrderId": f["OrderId"], "fill_id": f["fill_id"], "exec_time": f["exec_time"],
         "price": f["price"], "shares": f["shares"],
         "auction": f.get("auction", 0)}
        for f in fixture["fills"] + (extra_fills or [])
    ]
    raw = [
        {"OrderId": r["OrderId"], "fill_id": r["fill_id"], "liquidity": r["liquidity"]}
        for r in fixture["raw"]
    ]
    bars = [{"ts": b["ts"], "volume": b["volume"]} for b in fixture["bars"]]
    return make_manager(tmp_path, rows, fills=fills, raw_fills=raw, bars=bars)


class TestOrderDetail:
    def test_bucket_sum_participation_and_cost(self, tmp_path):
        """出口条件：桶和=总成交；单路由参与率比值 0.99–1.01；残差 <0.5bps。"""
        from CostView.src import trader_service

        mgr = _make_detail_manager(tmp_path, _detail_fixture())
        detail = trader_service.build_order_detail("D1", mgr=mgr)

        buckets = detail["timeline"]["buckets"]
        assert sum(b["fill"] for b in buckets) == 1000.0
        assert buckets[-1]["cum_completion"] == pytest.approx(1.0)
        check = detail["timeline"]["par_rate_check"]
        assert check["note"] is None
        assert 0.99 <= check["ratio"] <= 1.01
        cost = detail["cost"]
        assert cost["residual_bps"] == pytest.approx(0.0, abs=0.5)
        assert cost["residual_flag"] is None
        assert cost["denominator"] == pytest.approx(100_000.0)

    def test_liquidity_latency_and_quality(self, tmp_path):
        from CostView.src import trader_service

        mgr = _make_detail_manager(tmp_path, _detail_fixture())
        detail = trader_service.build_order_detail("D1", mgr=mgr)

        assert detail["liquidity"]["passive_share_strict"] == pytest.approx(0.3)
        assert detail["liquidity"]["unknown_share"] == pytest.approx(0.4)
        latency = detail["latency"]
        assert latency["order_to_route_sec"] == pytest.approx(300.0)
        assert latency["route_to_first_fill_sec"] == pytest.approx(300.0)
        assert latency["first_continuous_fill_sec"] == pytest.approx(60.0)
        assert latency["scheduled"] is False
        flags = {f["id"]: f["severity"] for f in detail["quality"]["flags"]}
        assert flags["liquidity_unknown"] == "warn"
        assert detail["quality"]["level"] == "warn"

    def test_single_fill_returns_na(self, tmp_path):
        """单笔成交：fill_span/speed 为 None（不是 0），速度/加速度 N/A。"""
        from CostView.src import trader_service

        fixture = _detail_fixture()
        fixture["route"].update({"OrderId": "D2", "fill_count": 1})
        fixture["fills"] = [{
            "OrderId": "D2", "fill_id": "F1", "exec_time": "09:31:00",
            "price": 150.0, "shares": 1000.0,
        }]
        fixture["raw"] = [{"OrderId": "D2", "fill_id": "F1", "liquidity": "1"}]
        fixture["bars"] = []
        mgr = _make_detail_manager(tmp_path, fixture)
        detail = trader_service.build_order_detail("D2", mgr=mgr)

        assert detail["order"]["fill_span_sec"] is None
        assert detail["order"]["speed_shares_per_min"] is None
        assert detail["fill_stats"]["cv"] is None
        assert len(detail["timeline"]["buckets"]) == 1

    def test_auction_bucket_unavailable_and_scheduled(self, tmp_path):
        """收盘竞价桶 participation_status=unavailable；收盘单 scheduled=true。"""
        from CostView.src import trader_service

        fixture = _detail_fixture()
        fixture["route"].update({
            "OrderId": "D3", "algo": "close", "fill_count": 2,
        })
        fixture["fills"] = [
            {"OrderId": "D3", "fill_id": "F1", "exec_time": "15:55:00",
             "price": 150.0, "shares": 300.0},
            {"OrderId": "D3", "fill_id": "F2", "exec_time": "16:00:00",
             "price": 150.0, "shares": 700.0, "auction": 1},
        ]
        fixture["raw"] = [
            {"OrderId": "D3", "fill_id": "F1", "liquidity": "4"},
            {"OrderId": "D3", "fill_id": "F2", "liquidity": "4"},
        ]
        fixture["bars"] = [{"ts": "15:55:10", "volume": 1000.0}]
        mgr = _make_detail_manager(tmp_path, fixture)
        detail = trader_service.build_order_detail("D3", mgr=mgr)

        buckets = detail["timeline"]["buckets"]
        assert buckets[-1]["participation_status"] == "unavailable"
        assert buckets[-1]["participation"] is None
        assert detail["latency"]["scheduled"] is True

    def test_missing_order_raises_404_semantics(self, tmp_path):
        from CostView.src import trader_service

        mgr = _make_detail_manager(tmp_path, _detail_fixture())
        with pytest.raises(trader_service.OrderNotFound):
            trader_service.build_order_detail("NOPE", mgr=mgr)

    def test_invalid_bucket_min(self, tmp_path):
        from CostView.src import trader_service

        mgr = _make_detail_manager(tmp_path, _detail_fixture())
        with pytest.raises(ValueError, match="bucket_min"):
            trader_service.build_order_detail("D1", bucket_min=7, mgr=mgr)


class TestPageFillEnrichment:
    def test_rows_get_span_speed_passive(self, tmp_path):
        """列表当前页逐笔补列（fill_span/speed/passive_ratio）+ fill_quality 探针。"""
        from CostView.src import trader_service

        fixture = _detail_fixture()
        fixture["route"].update({"OrderId": "E1"})
        for f in fixture["fills"]:
            f["OrderId"] = "E1"
        for r in fixture["raw"]:
            r["OrderId"] = "E1"
        fixture["fills"] = fixture["fills"][:2]
        fixture["raw"] = fixture["raw"][:2]
        mgr = _make_detail_manager(tmp_path, fixture)
        payload = trader_service.build_order_page_from_query(
            mgr=mgr, start_date="20261022", end_date="20261022",
        )

        row = payload["orders"][0]
        assert row["fill_span_sec"] == pytest.approx(300.0)
        assert row["speed_shares_per_min"] == pytest.approx(120.0)  # 600 / 5min
        assert row["passive_ratio"] == pytest.approx(0.5)           # 300 passive / 600
        probes = {c["id"]: c for c in payload["probes"]["checks"]}
        assert probes["fill_quality"]["checked"] is True

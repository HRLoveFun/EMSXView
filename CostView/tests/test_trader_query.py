"""trader_query SQL 层测试（PR-1）：聚合口径 / EXISTS 过滤 / 排序白名单 / 筛选项。"""

from __future__ import annotations

import pytest
from data_access.storage.connection import AccessTier

from CostView.src import trader_query as tq
from CostView.src.trader_models import TraderFilters
from CostView.tests.trader_fixtures import insert_route, make_manager

# ── 多路由聚合与 dominant 维度 ──────────────────────────────────────────────


def _multi_route_rows() -> list[dict]:
    return [
        # M1：两路由（R1 fill 大 → dominant），跨 broker/algo → mixed；
        # Amount 与 RouteShares 逐路由一致，避免 amount_qty_mismatch 旗标干扰
        {"OrderId": "M1", "RouteId": "R1", "Broker": "BROKER_A", "algo": "vwap",
         "fill": 700.0, "RouteShares": 1000.0, "Amount": 1000.0, "p_avg": 100.0,
         "arrival_cost_bps": -2.0, "fill_count": 4},
        {"OrderId": "M1", "RouteId": "R2", "Broker": "BROKER_B", "algo": "pov",
         "fill": 200.0, "RouteShares": 500.0, "Amount": 500.0, "p_avg": 110.0,
         "arrival_cost_bps": -8.0, "fill_count": 2},
        # S1：单路由
        {"OrderId": "S1", "RouteId": "R1", "Broker": "BROKER_A", "algo": "vwap",
         "fill": 900.0, "RouteShares": 1000.0, "p_avg": 150.0,
         "arrival_cost_bps": -4.0, "fill_count": 3},
    ]


def _filters(**overrides) -> TraderFilters:
    base = {"start_date": "20261001", "end_date": "20261031", "limit": 50}
    base.update(overrides)
    return TraderFilters(**base)


def _rows(mgr, **overrides) -> list[dict]:
    conn = mgr.get_connection("fill_bdib", AccessTier.READ)
    try:
        return tq.query_order_rows(conn, _filters(**overrides))
    finally:
        conn.close()


class TestOrderAggregation:
    def test_multi_route_aggregates_and_dominant_dims(self, tmp_path):
        """指标按全部路由聚合；维度头取 fill 最大路由；跨 broker/algo 标 mixed。"""
        mgr = make_manager(tmp_path, _multi_route_rows())
        rows = {r["OrderId"]: r for r in _rows(mgr)}

        m1 = rows["M1"]
        assert m1["route_count"] == 2
        assert m1["fill"] == pytest.approx(900.0)          # 700 + 200
        assert m1["route_shares"] == pytest.approx(1500.0)  # 1000 + 500
        assert m1["completion"] == pytest.approx(0.6)       # 900 / 1500
        assert m1["fill_count"] == 6
        # vwap = (700×100 + 200×110) / 900
        assert m1["vwap"] == pytest.approx((700 * 100.0 + 200 * 110.0) / 900.0)
        # arrival 加权 = (-2×700×100 + -8×200×110) / (700×100 + 200×110)
        num = -2.0 * 700 * 100 + -8.0 * 200 * 110
        den = 700 * 100 + 200 * 110
        assert m1["arrival_cost_bps"] == pytest.approx(num / den)
        assert m1["broker"] == "BROKER_A"                  # R1 fill 700 最大
        assert m1["algo"] == "vwap"
        assert bool(m1["mixed"]) is True
        assert bool(rows["S1"]["mixed"]) is False

    def test_any_route_match_keeps_full_aggregation(self, tmp_path):
        """多路由筛选 broker=A：命中订单仍按全部路由聚合（不只算 A 的路由）。"""
        mgr = make_manager(tmp_path, _multi_route_rows())
        rows = _rows(mgr, broker="BROKER_A")

        assert [r["OrderId"] for r in rows] == ["M1", "S1"]
        m1 = rows[0]
        assert m1["fill"] == pytest.approx(900.0)  # 含 BROKER_B 路由的 200

    def test_dimension_filters_match_any_route(self, tmp_path):
        """algo=pov 只命中 M1（R2 命中），S1 不出现。"""
        mgr = make_manager(tmp_path, _multi_route_rows())
        rows = _rows(mgr, algo="pov")
        assert [r["OrderId"] for r in rows] == ["M1"]

    def test_exchange_filter_matches_any_route(self, tmp_path):
        """市场维度筛选：订单内**任一路由**命中即命中；订单头仍取 dominant 路由的 Exchange。"""
        rows = [dict(row) for row in _multi_route_rows()]
        # M1 的次路由 R2（fill 200，非 dominant）落在 LN → exchange=LN 应命中 M1
        rows[1]["Exchange"] = "LN"
        rows.append(
            {"OrderId": "L1", "RouteId": "R1", "Exchange": "LN",
             "fill": 500.0, "RouteShares": 500.0, "p_avg": 200.0},
        )
        mgr = make_manager(tmp_path, rows)

        ln_rows = {r["OrderId"]: r for r in _rows(mgr, exchange="LN")}
        assert set(ln_rows) == {"M1", "L1"}
        assert ln_rows["L1"]["exchange"] == "LN"
        # M1 只有次路由命中 LN，dominant 路由（R1, fill 700）仍是 US
        assert ln_rows["M1"]["exchange"] == "US"
        assert {r["OrderId"] for r in _rows(mgr, exchange=("US", "LN"))} == {"M1", "S1", "L1"}
        assert _rows(mgr, exchange="HK") == []

    def test_empty_table_returns_empty(self, tmp_path):
        mgr = make_manager(tmp_path, [])
        assert _rows(mgr) == []


class TestBucketQualitySort:
    def test_completion_bucket_filter(self, tmp_path):
        mgr = make_manager(tmp_path, _multi_route_rows())
        # M1 completion 0.6 → 50to80；S1 0.9 → 80to100
        assert [r["OrderId"] for r in _rows(mgr, completion_bucket="50to80")] == ["M1"]
        assert [r["OrderId"] for r in _rows(mgr, completion_bucket="80to100")] == ["S1"]
        assert _rows(mgr, completion_bucket="lt50") == []

    def test_quality_filter_par_suspect_and_clean(self, tmp_path):
        rows = _multi_route_rows() + [
            {"OrderId": "P1", "RouteId": "R1", "fill": 900.0, "par_rate": 1.5},
        ]
        mgr = make_manager(tmp_path, rows)
        assert [r["OrderId"] for r in _rows(mgr, quality="par_suspect")] == ["P1"]
        assert set(r["OrderId"] for r in _rows(mgr, quality="clean")) == {"M1", "S1"}

    def test_sort_whitelist_and_direction(self, tmp_path):
        mgr = make_manager(tmp_path, _multi_route_rows())
        rows = _rows(mgr, sort="completion", sort_dir="asc")
        assert [r["OrderId"] for r in rows] == ["M1", "S1"]
        rows = _rows(mgr, sort="date", sort_dir="desc")
        assert {r["OrderId"] for r in rows} == {"M1", "S1"}

    def test_unknown_sort_raises(self):
        """排序键走白名单：非法值在进 SQL 前被拒绝（注入面封死）。"""
        from CostView.src import trader_service

        filters = TraderFilters(
            start_date="20261001", end_date="20261031",
            sort="; DROP TABLE tca_route_summary", limit=10,
        )
        with pytest.raises(ValueError, match="sort"):
            trader_service.validate_options(filters)


class TestFilterOptions:
    def test_traders_and_strategy_types_distinct(self, tmp_path):
        mgr = make_manager(tmp_path, [
            {"OrderId": "A1", "TraderName": "HRCHEN", "StrategyType": "VWAP"},
            {"OrderId": "A2", "TraderName": "ALICE", "StrategyType": "CLOSE"},
            {"OrderId": "A3", "TraderName": "HRCHEN", "StrategyType": "VWAP"},
        ])
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        try:
            options = tq.query_filter_options(conn)
        finally:
            conn.close()

        assert options["traders"] == ["ALICE", "HRCHEN"]
        assert options["strategy_types"] == ["CLOSE", "VWAP"]
        # 维度表缺失 → exchanges 回退 tca_route_summary DISTINCT（默认夹具 US）
        assert options["exchanges"] == ["US"]

    def test_ticker_prefix_autocomplete(self, tmp_path):
        mgr = make_manager(tmp_path, [
            {"OrderId": "A1", "equ_ticker": "ABCD US Equity"},
            {"OrderId": "A2", "equ_ticker": "BBCD US Equity"},
        ])
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        try:
            options = tq.query_filter_options(conn, ticker_prefix="A")
        finally:
            conn.close()

        assert options["symbols"] == ["ABCD US Equity"]

    def test_recent_trading_dates_ascending(self, tmp_path):
        mgr = make_manager(tmp_path, [
            {"OrderId": "A1", "order_as_of_date": "20261022"},
            {"OrderId": "A2", "order_as_of_date": "20261021"},
            {"OrderId": "A3", "order_as_of_date": "20261020"},
            {"OrderId": "A4", "order_as_of_date": "20261019"},
        ])
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        try:
            dates = tq.recent_trading_dates(conn, 3)
        finally:
            conn.close()

        assert dates == ["20261020", "20261021", "20261022"]


class TestDetailQueries:
    """PR-2：详情逐笔/行情取数（processed_fills / raw_fills / raw_bdib）。"""

    def test_order_routes_fills_raw_and_bars(self, tmp_path):
        mgr = make_manager(
            tmp_path, [{"OrderId": "D1"}],
            fills=[{"OrderId": "D1", "fill_id": "F1", "exec_time": "09:31:00"}],
            raw_fills=[{"OrderId": "D1", "fill_id": "F1", "liquidity": "1"}],
            bars=[{"ts": "09:30:10", "volume": 500.0}],
        )
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        try:
            routes = tq.query_order_routes(conn, "D1")
        finally:
            conn.close()
        assert [r["RouteId"] for r in routes] == ["R1"]

        conn = mgr.get_connection("processed_fills", AccessTier.READ)
        try:
            fills = tq.query_order_fills(conn, "D1", "20261022")
        finally:
            conn.close()
        assert [f["FillId"] for f in fills] == ["F1"]

        conn = mgr.get_connection("raw_fills", AccessTier.READ)
        try:
            raw = tq.query_order_raw_fills(conn, "D1", "20261022")
        finally:
            conn.close()
        assert raw[0]["Liquidity"] == "1"

        conn = mgr.get_connection("raw_bdib", AccessTier.READ)
        try:
            bars = tq.query_order_bars(conn, "ABCD US Equity", "20261022")
        finally:
            conn.close()
        assert bars[0]["volume"] == 500.0

    def test_detail_queries_degrade_on_missing_table(self, tmp_path):
        """库在但表缺失 → 查询层降级空列表（009 语义，不抛错）。"""
        import sqlite3

        from data_access.storage.connection import ConnectionManager

        empty = tmp_path / "empty.db"
        sqlite3.connect(str(empty)).close()
        mgr = ConnectionManager(path_overrides={
            "processed_fills": empty, "raw_fills": empty, "raw_bdib": empty,
        })
        conn = mgr.get_connection("processed_fills", AccessTier.READ)
        try:
            assert tq.query_order_fills(conn, "D1", "20261022") == []
            assert tq.query_order_raw_fills(conn, "D1", "20261022") == []
            assert tq.query_order_bars(conn, "ABCD", "20261022") == []
        finally:
            conn.close()

    def test_missing_db_file_raises_for_router_503(self, tmp_path):
        """库文件不存在 → FileNotFoundError（路由层映射 503 data_source_unavailable）。"""
        from data_access.storage.connection import ConnectionManager

        mgr = ConnectionManager(path_overrides={
            "processed_fills": tmp_path / "nodir" / "missing.db",
        })
        with pytest.raises(FileNotFoundError):
            mgr.get_connection("processed_fills", AccessTier.READ)

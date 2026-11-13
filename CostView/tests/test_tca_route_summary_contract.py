"""CCP-20261112-sqlite.tca_route_summary — 消费者侧契约测试（CostView）。

上游 EMSXDataPipeline 在 ``tca_route_summary`` 增加两个可空列：

- ``adv_20d`` REAL — 20 交易日平均日成交量（shares）
- ``daily_volatility`` REAL — 年化历史波动率（百分比，``26.0`` = 26%）

A 类增量（只加可空列）。本测试用临时 SQLite 锁死消费方行为：

1. 新 schema：两列可读、可序列化；
2. 旧 schema（无两列）：查询不报错，未知列按缺失处理（``SELECT *`` 容忍）；
3. ``NULL`` 必须保持 ``None``，**不得被 0 填充**。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from CostView.src.tca_query_builder import get_tca_route_summaries
from CostView.src.tca_query_service import TcaFilters, TcaQueryService
from CostView.src.trader_service import _routes_payload
from CostView.api.routers.costview import _serialize_route


_BASE_DDL = """
    CREATE TABLE tca_route_summary (
        OrderId TEXT, RouteId TEXT, order_as_of_date TEXT,
        Exchange TEXT, equ_ticker TEXT,
        {liquidity_columns}
        PRIMARY KEY (OrderId, RouteId, order_as_of_date)
    )
"""


def _make_db(
    path: Path,
    *,
    with_columns: bool,
    adv_20d: float | None = None,
    daily_volatility: float | None = None,
) -> Path:
    """建最小 tca_route_summary 临时库；with_columns=False 模拟旧 schema。"""
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            _BASE_DDL.format(
                liquidity_columns=(
                    "adv_20d REAL, daily_volatility REAL,"
                    if with_columns
                    else ""
                )
            )
        )
        if with_columns:
            conn.execute(
                "INSERT INTO tca_route_summary "
                "(OrderId, RouteId, order_as_of_date, Exchange, equ_ticker, "
                " adv_20d, daily_volatility) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("O1", "R1", "20260418", "US", "AAPL US Equity",
                 adv_20d, daily_volatility),
            )
        else:
            conn.execute(
                "INSERT INTO tca_route_summary "
                "(OrderId, RouteId, order_as_of_date, Exchange, equ_ticker) "
                "VALUES (?, ?, ?, ?, ?)",
                ("O1", "R1", "20260418", "US", "AAPL US Equity"),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _service(db_path: Path) -> TcaQueryService:
    return TcaQueryService(fill_bdib_db_path=str(db_path))


def _filters() -> TcaFilters:
    return TcaFilters(
        start_date="20260418", end_date="20260418", limit=50, offset=0,
    )


class TestNewColumnsPresent:
    """新 schema：两列在各层可读且单位保持原样。"""

    def test_query_returns_both_columns(self, tmp_path: Path) -> None:
        db = _make_db(
            tmp_path / "fill_bdib.db", with_columns=True,
            adv_20d=4_600_000.0, daily_volatility=26.0,
        )
        svc = _service(db)

        rows, total = get_tca_route_summaries(svc._mgr, _filters())

        assert total == 1
        assert rows[0]["adv_20d"] == 4_600_000.0
        assert rows[0]["daily_volatility"] == 26.0

    def test_report_maps_columns_to_contract(self, tmp_path: Path) -> None:
        db = _make_db(
            tmp_path / "fill_bdib.db", with_columns=True,
            adv_20d=4_600_000.0, daily_volatility=26.0,
        )
        svc = _service(db)

        report = svc.build_tca_report(_filters(), include_time_series=False)

        route = report.orders[0]
        assert route.adv_20d == 4_600_000.0
        assert route.daily_volatility == 26.0

    def test_api_serializer_exposes_columns(self, tmp_path: Path) -> None:
        db = _make_db(
            tmp_path / "fill_bdib.db", with_columns=True,
            adv_20d=4_600_000.0, daily_volatility=26.0,
        )
        svc = _service(db)

        route = svc.build_tca_report(_filters(), include_time_series=False).orders[0]
        payload = _serialize_route(route)

        assert payload["adv_20d"] == 4_600_000.0
        assert payload["daily_volatility"] == 26.0


class TestOldSchemaTolerance:
    """旧 schema（无两列）：查询继续工作，缺失按 None 处理。"""

    def test_query_ignores_unknown_columns(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path / "fill_bdib.db", with_columns=False)
        svc = _service(db)

        rows, total = get_tca_route_summaries(svc._mgr, _filters())

        assert total == 1
        assert "adv_20d" not in rows[0]
        assert "daily_volatility" not in rows[0]

    def test_report_and_serializer_degrade_to_none(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path / "fill_bdib.db", with_columns=False)
        svc = _service(db)

        route = svc.build_tca_report(_filters(), include_time_series=False).orders[0]
        payload = _serialize_route(route)

        assert route.adv_20d is None
        assert route.daily_volatility is None
        assert payload["adv_20d"] is None
        assert payload["daily_volatility"] is None


class TestNullIsMissingNotZero:
    """新 schema + NULL：必须保持 None，不得变成 0。"""

    def test_null_survives_query_and_serialization(self, tmp_path: Path) -> None:
        db = _make_db(
            tmp_path / "fill_bdib.db", with_columns=True,
            adv_20d=None, daily_volatility=None,
        )
        svc = _service(db)

        rows, _ = get_tca_route_summaries(svc._mgr, _filters())
        assert rows[0]["adv_20d"] is None
        assert rows[0]["daily_volatility"] is None

        route = svc.build_tca_report(_filters(), include_time_series=False).orders[0]
        payload = _serialize_route(route)
        assert payload["adv_20d"] is None
        assert payload["daily_volatility"] is None
        assert payload["adv_20d"] != 0
        assert payload["daily_volatility"] != 0

    def test_trader_route_payload_preserves_null(self) -> None:
        """交易员详情路由子表同样保留 NULL（旧 schema 缺键也返回 None）。"""
        payload = _routes_payload([
            {
                "RouteId": "R1", "Broker": "B", "algo": "VWAP",
                "RouteShares": 100.0, "fill": 50.0,
                "arrival_cost_bps": 1.0, "wagner_is_bps": 2.0,
                "adv_20d": None, "daily_volatility": 26.0,
            },
            {  # 旧 schema：行里没有这两个键
                "RouteId": "R2", "Broker": "B", "algo": "TWAP",
                "RouteShares": 100.0, "fill": 100.0,
            },
        ])

        assert payload[0]["adv_20d"] is None
        assert payload[0]["daily_volatility"] == 26.0
        assert payload[1]["adv_20d"] is None
        assert payload[1]["daily_volatility"] is None

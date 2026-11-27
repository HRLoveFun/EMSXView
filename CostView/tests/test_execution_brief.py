"""执行简报（230）服务与路由测试：期间解析 / 买卖拆分 / 完成分桶 / 成本 / 缺口披露。"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from data_access.storage.connection import ConnectionManager

from CostView.src import execution_brief
from CostView.tests.trader_fixtures import TCA_DDL, insert_route, make_manager


def _rows() -> list[dict]:
    return [
        # 多路由部分成交（BUY）
        {"OrderId": "M1", "RouteId": "R1", "order_as_of_date": "20261022",
         "fill": 700.0, "RouteShares": 1000.0, "Amount": 1000.0,
         "p_avg": 100.0, "p_arrival": 99.0, "p_decision": 99.5, "p_close": 101.0,
         "fill_count": 4, "arrival_cost_bps": -12.0, "wagner_is_bps": -20.0,
         "pnl_vwap": -8.0, "opportunity_cost": -50.0, "delay_cost": -20.0,
         "trading_cost": -30.0, "StrategyType": "VWAP", "algo": "vwap",
         "Side": "BUY", "TraderName": "HRCHEN"},
        {"OrderId": "M1", "RouteId": "R2", "order_as_of_date": "20261022",
         "fill": 200.0, "RouteShares": 500.0, "Amount": 500.0,
         "p_avg": 110.0, "p_arrival": 109.0, "p_decision": 109.5, "p_close": 111.0,
         "fill_count": 2, "arrival_cost_bps": -10.0, "wagner_is_bps": -18.0,
         "pnl_vwap": -7.0, "opportunity_cost": -10.0, "delay_cost": -5.0,
         "trading_cost": -8.0, "StrategyType": "VWAP", "algo": "vwap",
         "Side": "BUY", "TraderName": "HRCHEN"},
        # 完全成交（SELL）
        {"OrderId": "S1", "RouteId": "R1", "order_as_of_date": "20261021",
         "fill": 1000.0, "RouteShares": 1000.0, "Amount": 1000.0,
         "p_avg": 50.0, "p_arrival": 51.0, "p_decision": 50.5, "p_close": 49.0,
         "fill_count": 3, "arrival_cost_bps": 8.0, "wagner_is_bps": 5.0,
         "pnl_vwap": 2.0, "opportunity_cost": 0.0, "delay_cost": 2.0,
         "trading_cost": 3.0, "StrategyType": "ARRIVAL", "algo": "arrival",
         "Side": "SELL", "TraderName": "LI"},
        # 零成交（BUY）
        {"OrderId": "Z1", "RouteId": "R1", "order_as_of_date": "20261020",
         "fill": 0.0, "RouteShares": 5000.0, "Amount": 5000.0,
         "p_avg": None, "p_arrival": 20.0, "p_decision": 20.0, "p_close": 21.0,
         "fill_count": 0, "arrival_cost_bps": None, "wagner_is_bps": None,
         "pnl_vwap": None, "opportunity_cost": -100.0, "delay_cost": None,
         "trading_cost": None, "StrategyType": "POV", "algo": "pov",
         "Side": "BUY", "TraderName": "HRCHEN", "equ_ticker": "ZZZZ US Equity"},
    ]


def test_brief_overview_and_buckets(tmp_path):
    mgr = make_manager(tmp_path, _rows())
    data = execution_brief.build_brief(
        start_date="20261020", end_date="20261022", mgr=mgr,
    )

    assert data["period"]["preset"] == "custom"
    assert data["period"]["label"] == "自定义区间"
    assert data["coverage"]["orders"] == 3
    assert data["coverage"]["symbols"] == 2
    assert data["coverage"]["route_count"] == 4
    # 委托金额：有成交按 p_avg 计价，零成交按 p_arrival 回退
    assert data["coverage"]["order_notional_usd"] == pytest.approx(
        (1000 * 100.0 + 500 * 110.0) + 1000 * 50.0 + 5000 * 20.0, rel=1e-9,
    )
    # 买卖拆分：BUY 2 单 / SELL 1 单
    assert data["sides"]["buy"]["orders"] == 2
    assert data["sides"]["sell"]["orders"] == 1
    assert data["sides"]["buy"]["completion"] == pytest.approx(900 / 6500)
    assert data["sides"]["sell"]["completion"] == pytest.approx(1.0)

    buckets = {b["key"]: b for b in data["completion_buckets"]}
    assert buckets["complete"]["orders"] == 1
    assert buckets["partial"]["orders"] == 1
    assert buckets["zero"]["orders"] == 1
    assert buckets["overfill"]["orders"] == 0
    assert buckets["zero"]["share_of_orders"] == pytest.approx(1 / 3)


def test_brief_cost_and_unfilled(tmp_path):
    mgr = make_manager(tmp_path, _rows())
    data = execution_brief.build_brief(
        start_date="20261020", end_date="20261022", mgr=mgr,
    )

    overview = data["overview"]
    assert overview["unfilled_notional_usd"] is not None
    # 零成交单按 p_arrival 回退计价：5000 × 20 = 100000
    assert data["coverage"]["order_notional_unpriced_orders"] == 0
    top_unfilled = data["top_orders"]["by_unfilled"]
    assert top_unfilled[0]["order_id"] == "Z1"
    assert top_unfilled[0]["unfilled_notional_usd"] == pytest.approx(100000.0)

    # 成本符号：负 = 不利，Top 为最不利（最小）的 M1
    assert data["top_orders"]["by_arrival"][0]["order_id"] == "M1"
    assert data["top_orders"]["by_opportunity"][0]["order_id"] == "Z1"


def test_brief_strategy_mix_and_traders(tmp_path):
    mgr = make_manager(tmp_path, _rows())
    data = execution_brief.build_brief(
        start_date="20261020", end_date="20261022", mgr=mgr,
    )

    strategies = {item["key"]: item for item in data["strategy_mix"]}
    assert strategies["VWAP"]["orders"] == 1
    assert strategies["ARRIVAL"]["orders"] == 1
    assert strategies["POV"]["orders"] == 1

    traders = {item["key"]: item for item in data["top_traders"]}
    assert traders["HRCHEN"]["orders"] == 2
    assert traders["LI"]["orders"] == 1


def test_brief_anomaly_and_data_gaps(tmp_path):
    mgr = make_manager(tmp_path, _rows())
    data = execution_brief.build_brief(
        start_date="20261020", end_date="20261022", mgr=mgr,
    )

    assert data["anomaly"]["orders_total"] >= 1
    assert data["anomaly"]["scope"] == "order-level"
    gaps = {item["key"]: item for item in data["data_availability"]}
    assert gaps["portfolio"]["status"] == "unavailable"
    assert gaps["order_status"]["status"] == "unavailable"
    assert any("负 = 不利" in note for note in data["notes"])


def test_brief_last_day_uses_latest_tca_date(tmp_path):
    mgr = make_manager(tmp_path, _rows())
    data = execution_brief.build_brief(last="day", mgr=mgr, today=date(2027, 1, 1))

    assert data["period"]["start_date"] == "20261022"
    assert data["period"]["end_date"] == "20261022"
    assert data["period"]["label"] == "每日"
    assert data["coverage"]["orders"] == 1


def test_brief_last_day_without_data_raises(tmp_path):
    mgr = make_manager(tmp_path, [])
    with pytest.raises(execution_brief.DataNotReadyError):
        execution_brief.build_brief(last="day", mgr=mgr)


def test_brief_invalid_range_is_value_error(tmp_path):
    mgr = make_manager(tmp_path, _rows())
    with pytest.raises(ValueError):
        execution_brief.build_brief(
            start_date="20261022", end_date="20261020", mgr=mgr,
        )


def test_brief_filters_are_multi_value(tmp_path):
    mgr = make_manager(tmp_path, _rows())
    data = execution_brief.build_brief(
        start_date="20261020", end_date="20261022", side="BUY", mgr=mgr,
    )
    assert data["coverage"]["orders"] == 2
    assert data["filters"]["side"] == ["BUY"]


def test_brief_normalizes_b_s_side_and_filter(tmp_path):
    """上游实测 Side 为 B/S；简报输出统一 BUY/SELL，筛选同时接受两套写法。"""
    mgr = make_manager(tmp_path, [
        {"OrderId": "B1", "Side": "B", "order_as_of_date": "20261022"},
        {"OrderId": "S1", "Side": "S", "order_as_of_date": "20261022"},
    ])
    data = execution_brief.build_brief(
        start_date="20261022", end_date="20261022", mgr=mgr,
    )
    assert data["sides"]["buy"]["orders"] == 1
    assert data["sides"]["sell"]["orders"] == 1
    assert data["sides"]["other"]["orders"] == 0

    filtered = execution_brief.build_brief(
        start_date="20261022", end_date="20261022", side="BUY", mgr=mgr,
    )
    assert filtered["coverage"]["orders"] == 1
    assert filtered["sides"]["buy"]["orders"] == 1


def test_brief_missing_table_is_warned_not_silent_zero(tmp_path):
    """表不存在时返回空简报 + data_source_warning，不把「查不了」伪装成「没有委托」。"""
    db = tmp_path / "fill_bdib.db"
    sqlite3.connect(str(db)).close()  # 空库（无 tca_route_summary）
    mgr = ConnectionManager(path_overrides={"fill_bdib": db})

    data = execution_brief.build_brief(
        start_date="20261022", end_date="20261022", mgr=mgr,
    )
    assert data["coverage"]["orders"] == 0
    assert "不存在" in data["data_source_warning"]


def test_brief_uses_fill_bdib_fx_backfill(tmp_path):
    """fx_rate 缺失时按 fill_bdib 回填；CTE 日期参数顺序不得错位。"""
    db = tmp_path / "fill_bdib.db"
    conn = sqlite3.connect(str(db))
    conn.execute(TCA_DDL)
    conn.execute("ALTER TABLE tca_route_summary ADD COLUMN fx_rate REAL")
    insert_route(
        conn, "USD1", "20261022", Currency="USD", fill=100.0,
        RouteShares=100.0, p_avg=10.0, fx_rate=1.0,
    )
    insert_route(
        conn, "GBP1", "20261022", Currency="GBP", fill=100.0,
        RouteShares=100.0, p_avg=10.0, fx_rate=None,
    )
    conn.execute(
        "CREATE TABLE fill_bdib (OrderId TEXT, RouteId TEXT, order_as_of_date TEXT,"
        " fill_volume REAL, fx_rate REAL)"
    )
    conn.execute(
        "INSERT INTO fill_bdib VALUES ('GBP1', 'R1', '20261022', 100.0, 1.25)"
    )
    conn.commit()
    conn.close()

    mgr = ConnectionManager(path_overrides={"fill_bdib": db})
    data = execution_brief.build_brief(
        start_date="20261022", end_date="20261022", mgr=mgr,
    )

    assert data["coverage"]["orders"] == 2
    assert data["coverage"]["fx_missing_orders"] == 0
    assert data["coverage"]["fill_notional_usd"] == pytest.approx(1000.0 + 1250.0)


# ── 路由契约 ───────────────────────────────────────────────────────────────


def _client(monkeypatch, mgr):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from CostView.api.routers.brief import router

    monkeypatch.setattr(execution_brief, "DEFAULT_MANAGER", mgr)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_router_envelope(tmp_path, monkeypatch):
    client = _client(monkeypatch, make_manager(tmp_path, _rows()))
    response = client.get(
        "/api/tca/brief",
        params={"start_date": "20261020", "end_date": "20261022"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["coverage"]["orders"] == 3
    assert body["data"]["spec_version"] == execution_brief.BRIEF_SPEC_VERSION


def test_router_rejects_invalid_preset(tmp_path, monkeypatch):
    client = _client(monkeypatch, make_manager(tmp_path, _rows()))
    response = client.get("/api/tca/brief", params={"last": "custom"})
    assert response.status_code == 422


def test_router_data_not_ready_is_503(tmp_path, monkeypatch):
    client = _client(monkeypatch, make_manager(tmp_path, []))
    response = client.get("/api/tca/brief", params={"last": "day"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "data_not_ready"

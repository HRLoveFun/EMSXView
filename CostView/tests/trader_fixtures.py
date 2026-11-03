"""交易员复盘台测试夹具（test_trader_query / test_trader_service / test_trader_router 共用）。

与 test_report_metrics 同构的最小 tca_route_summary 表结构（含 38 项计算指标列）。
010-extract-pipeline：EMSXView 只读消费者，fixture 用 sqlite3 直写临时库。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from data_access.storage.connection import ConnectionManager

TCA_DDL = """
    CREATE TABLE tca_route_summary (
        OrderId TEXT, RouteId TEXT, order_as_of_date TEXT, Exchange TEXT,
        Account TEXT, equ_ticker TEXT, Currency TEXT, Side TEXT,
        Amount REAL, RouteShares REAL, Type TEXT, LimitPrice REAL,
        StopPrice REAL, Broker TEXT, StrategyType TEXT, algo TEXT,
        TraderName TEXT,
        fill_count INTEGER, fill REAL, fill_continuous REAL, fill_close REAL,
        par_rate REAL, par_rate_continuous REAL, par_rate_close REAL,
        p_avg REAL, p_avg_continuous REAL,
        pnl_vwap REAL, pnl_vwap_continuous REAL,
        RPM REAL, RPM_continuous REAL,
        pwp_5 REAL, pwp_10 REAL, pwp_15 REAL, pwp_20 REAL, pwp_25 REAL,
        p_arrival REAL, p_close REAL, arrival_cost_bps REAL, close_cost_bps REAL,
        opportunity_cost REAL,
        p_decision REAL, delay_cost REAL, trading_cost REAL, wagner_is REAL,
        wagner_is_bps REAL, cost_stddev REAL, cost_p95 REAL, cost_cvar REAL,
        order_duration_sec REAL, exec_rate_shares_per_min REAL,
        temp_impact_5min_bps REAL, temp_impact_10min_bps REAL,
        temp_impact_30min_bps REAL, perm_impact_bps REAL,
        recovery_truncated INTEGER,
        PRIMARY KEY (OrderId, RouteId, order_as_of_date)
    )
"""


def insert_route(conn: sqlite3.Connection, order_id: str, oad: str = "20261022", **overrides: Any) -> None:
    """插入一条最小 tca_route_summary 记录（默认多路由聚合用例的通用值）。"""
    values: dict[str, Any] = {
        "OrderId": order_id, "RouteId": "R1", "order_as_of_date": oad,
        "Exchange": "US", "equ_ticker": "ABCD US Equity", "Side": "BUY",
        "Currency": "USD", "Amount": 1000.0, "RouteShares": 1000.0,
        "Broker": "BROKER_A", "StrategyType": "VWAP", "algo": "vwap",
        "TraderName": "HRCHEN", "fill_count": 3, "fill": 900.0,
        "par_rate": 0.15, "p_avg": 150.0, "p_arrival": 149.0, "p_decision": 149.5,
        "p_close": 151.0, "pnl_vwap": -2.5, "arrival_cost_bps": -4.0,
        "wagner_is_bps": -9.0, "opportunity_cost": -1.0, "wagner_is": -90.0,
    }
    values.update(overrides)
    cols = ", ".join(values)
    marks = ", ".join(["?"] * len(values))
    conn.execute(f"INSERT INTO tca_route_summary ({cols}) VALUES ({marks})", list(values.values()))


def make_manager(tmp_path: Path, rows: Optional[list[dict[str, Any]]] = None) -> ConnectionManager:
    """构造含 tca_route_summary 的临时 fill_bdib 库并返回只读 ConnectionManager。"""
    db_path = tmp_path / "fill_bdib.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(TCA_DDL)
    for idx, row in enumerate(rows or []):
        payload = dict(row)
        order_id = str(payload.pop("OrderId", f"O{idx}"))
        oad = str(payload.pop("order_as_of_date", "20261022"))
        insert_route(conn, order_id, oad, **payload)
    conn.commit()
    conn.close()
    return ConnectionManager(path_overrides={
        "fill_bdib": db_path,
        "processed_fills": tmp_path / "processed_fills.db",
        "raw_bdib": tmp_path / "raw_bdib.db",
    })

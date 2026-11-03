"""交易员复盘台测试夹具（test_trader_* 共用）。

与 test_report_metrics 同构的最小 tca_route_summary 表结构（含 38 项计算指标列），
另建 processed_fills / raw_fills / raw_bdib 最小列集（只含被查询的列）。
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

PROCESSED_FILLS_DDL = """
    CREATE TABLE processed_fills (
        FillId TEXT, OrderId TEXT, RouteId TEXT, order_as_of_date TEXT,
        local_fill_datetime TEXT, exchange_exec_time TEXT, route_as_of_time TEXT,
        FillPrice REAL, FillShares REAL, is_closing_auction INTEGER,
        equ_ticker TEXT, Exchange TEXT,
        PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)
    )
"""

RAW_FILLS_DDL = """
    CREATE TABLE raw_fills (
        OrderId TEXT, RouteId TEXT, FillId TEXT, order_as_of_date TEXT,
        Liquidity TEXT, FillShares TEXT,
        NyOrderCreateAsOfDateTime TEXT,
        NyTranCreateAsOfDateTime TEXT, DateTimeOfFill TEXT,
        PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)
    )
"""

RAW_BDIB_DDL = """
    CREATE TABLE raw_bdib (
        equ_ticker TEXT, order_as_of_date TEXT, mkt_timestamp TEXT,
        open REAL, high REAL, low REAL, close REAL, volume REAL,
        PRIMARY KEY (equ_ticker, order_as_of_date, mkt_timestamp)
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


def _insert(conn: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    cols = ", ".join(values)
    marks = ", ".join(["?"] * len(values))
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(values.values()))


def insert_fill(
    conn: sqlite3.Connection, order_id: str, *, oad: str = "20261022",
    route_id: str = "R1", fill_id: str = "1", exec_time: str = "09:35:00",
    route_as_of: str = "09:30:00", price: float = 150.0, shares: float = 300.0,
    auction: int = 0, **extra: Any,
) -> None:
    """processed_fills 逐笔（默认连续竞价 300 股）。"""
    values: dict[str, Any] = {
        "OrderId": order_id, "RouteId": route_id, "FillId": fill_id,
        "order_as_of_date": oad,
        "local_fill_datetime": f"{oad[:4]}-{oad[4:6]}-{oad[6:]} {exec_time}",
        "exchange_exec_time": exec_time, "route_as_of_time": route_as_of,
        "FillPrice": price, "FillShares": shares, "is_closing_auction": auction,
        "equ_ticker": "ABCD US Equity", "Exchange": "US",
    }
    values.update(extra)
    _insert(conn, "processed_fills", values)


def insert_raw_fill(
    conn: sqlite3.Connection, order_id: str, *, oad: str = "20261022",
    route_id: str = "R1", fill_id: str = "1", liquidity: str = "1",
    shares: float = 300.0,
    order_create: str = "2026-10-22T09:25:00.000-04:00",
    route_create: str = "2026-10-22T09:30:00.000-04:00",
    fill_time: str = "2026-10-22T09:35:00.000-04:00", **extra: Any,
) -> None:
    """raw_fills 逐笔（Liquidity + FillShares + NY 时间戳）。"""
    values: dict[str, Any] = {
        "OrderId": order_id, "RouteId": route_id, "FillId": fill_id,
        "order_as_of_date": oad, "Liquidity": liquidity,
        "FillShares": str(shares),
        "NyOrderCreateAsOfDateTime": order_create,
        "NyTranCreateAsOfDateTime": route_create,
        "DateTimeOfFill": fill_time,
    }
    values.update(extra)
    _insert(conn, "raw_fills", values)


def insert_bar(
    conn: sqlite3.Connection, *, oad: str = "20261022",
    equ_ticker: str = "ABCD US Equity", ts: str = "09:30:10",
    volume: float = 1000.0, close: float = 150.0, **extra: Any,
) -> None:
    """raw_bdib 10s bar（最小列）。"""
    values: dict[str, Any] = {
        "equ_ticker": equ_ticker, "order_as_of_date": oad,
        "mkt_timestamp": ts, "open": close, "high": close, "low": close,
        "close": close, "volume": volume,
    }
    values.update(extra)
    _insert(conn, "raw_bdib", values)


def make_manager(
    tmp_path: Path,
    rows: Optional[list[dict[str, Any]]] = None,
    *,
    fills: Optional[list[dict[str, Any]]] = None,
    raw_fills: Optional[list[dict[str, Any]]] = None,
    bars: Optional[list[dict[str, Any]]] = None,
) -> ConnectionManager:
    """构造 4 库临时夹具（缺省空表）并返回只读 ConnectionManager。"""
    fill_bdib = tmp_path / "fill_bdib.db"
    conn = sqlite3.connect(str(fill_bdib))
    conn.execute(TCA_DDL)
    for idx, row in enumerate(rows or []):
        payload = dict(row)
        order_id = str(payload.pop("OrderId", f"O{idx}"))
        oad = str(payload.pop("order_as_of_date", "20261022"))
        insert_route(conn, order_id, oad, **payload)
    conn.commit()
    conn.close()

    proc = tmp_path / "processed_fills.db"
    conn = sqlite3.connect(str(proc))
    conn.execute(PROCESSED_FILLS_DDL)
    for fill in fills or []:
        payload = dict(fill)
        insert_fill(conn, str(payload.pop("OrderId", "O0")), **payload)
    conn.commit()
    conn.close()

    raw = tmp_path / "raw_fills.db"
    conn = sqlite3.connect(str(raw))
    conn.execute(RAW_FILLS_DDL)
    for fill in raw_fills or []:
        payload = dict(fill)
        insert_raw_fill(conn, str(payload.pop("OrderId", "O0")), **payload)
    conn.commit()
    conn.close()

    bdib = tmp_path / "raw_bdib.db"
    conn = sqlite3.connect(str(bdib))
    conn.execute(RAW_BDIB_DDL)
    for bar in bars or []:
        insert_bar(conn, **bar)
    conn.commit()
    conn.close()

    return ConnectionManager(path_overrides={
        "fill_bdib": fill_bdib,
        "processed_fills": proc,
        "raw_fills": raw,
        "raw_bdib": bdib,
    })

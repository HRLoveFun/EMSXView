from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from CostView.src.execution_history_service import ExecutionHistoryQueryService
from CostView.src.processing_config import ProcessingConfig as Config


def _seed_processed_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"""
            CREATE TABLE {Config.PROCESSED_FILLS_TABLE} (
                OrderId TEXT,
                RouteId TEXT,
                FillId TEXT,
                order_as_of_date TEXT,
                local_fill_datetime TEXT,
                exchange_exec_time TEXT,
                route_as_of_time TEXT,
                DateTimeOfFill TEXT,
                Broker TEXT,
                StrategyType TEXT,
                algo TEXT,
                TraderName TEXT,
                Exchange TEXT,
                ExecType TEXT,
                Amount REAL,
                RouteShares REAL,
                FillPrice REAL,
                FillShares REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE route_registry (
                OrderId TEXT,
                RouteId TEXT,
                equ_ticker TEXT,
                Exchange TEXT,
                ccy_ticker TEXT,
                Side TEXT,
                count_fill INTEGER,
                count_broker INTEGER,
                count_algo INTEGER,
                count_trader INTEGER
            )
            """
        )

        conn.executemany(
            f"""
            INSERT INTO {Config.PROCESSED_FILLS_TABLE}
            (OrderId, RouteId, FillId, order_as_of_date, local_fill_datetime, exchange_exec_time,
             route_as_of_time, DateTimeOfFill, Broker, StrategyType, algo, TraderName,
             Exchange, ExecType, Amount, RouteShares, FillPrice, FillShares)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "1001", "7", "F1", "20260422", "2026-04-22T10:00:00", "10:00:00",
                    "09:45:00", "2026-04-22T22:00:00", "BMTB", "VWAP", "VWAP", "TRADER1",
                    "US", "TRADE", 1000.0, 100.0, 189.25, 100.0,
                ),
                (
                    "1001", "8", "F2", "20260422", "2026-04-22T10:05:00", "10:05:00",
                    "09:50:00", "2026-04-22T22:05:00", "BMTB", "VWAP", "VWAP", "TRADER1",
                    "US", "TRADE", 1000.0, 50.0, 190.00, 50.0,
                ),
                (
                    "2001", "3", "F3", "20260423", "2026-04-23T11:00:00", "11:00:00",
                    "10:40:00", "2026-04-23T23:00:00", "OTHER", "TWAP", "TWAP", "TRADER2",
                    "JP", "TRADE", 800.0, 80.0, 150.50, 80.0,
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO route_registry
            (OrderId, RouteId, equ_ticker, Exchange, ccy_ticker, Side, count_fill, count_broker, count_algo, count_trader)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("1001", "7", "AAPL US Equity", "US", "USD Curncy", "BUY", 1, 1, 1, 1),
                ("1001", "8", "AAPL US Equity", "US", "USD Curncy", "BUY", 1, 1, 1, 1),
                ("2001", "3", "7203 JP Equity", "JP", "JPY Curncy", "SELL", 1, 1, 1, 1),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _seed_raw_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"""
            CREATE TABLE {Config.RAW_FILLS_TABLE} (
                OrderId TEXT,
                RouteId TEXT,
                FillId TEXT,
                source_date TEXT,
                fetched_at TEXT
            )
            """
        )
        conn.executemany(
            f"INSERT INTO {Config.RAW_FILLS_TABLE} (OrderId, RouteId, FillId, source_date, fetched_at) VALUES (?, ?, ?, ?, ?)",
            [
                ("1001", "7", "F1", "20260422", "2026-04-22T10:06:00"),
                ("1001", "8", "F2", "20260422", "2026-04-22T10:07:00"),
                ("2001", "3", "F3", "20260423", "2026-04-23T11:06:00"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_execution_history_service_lists_fill_history(tmp_path: Path):
    proc_db = tmp_path / "processed_fills.db"
    raw_db = tmp_path / "raw_fills.db"
    _seed_processed_db(proc_db)
    _seed_raw_db(raw_db)

    service = ExecutionHistoryQueryService(
        proc_fills_db_path=str(proc_db),
        raw_fills_db_path=str(raw_db),
    )

    rows = service.list_fill_history(start_date="20260422", end_date="20260422", limit=10)

    assert len(rows) == 2
    assert rows[0]["order_id"] == "1001"
    assert rows[0]["source_date"] == "20260422"
    assert rows[0]["equ_ticker"] == "AAPL US Equity"


def test_execution_history_service_builds_order_summaries(tmp_path: Path):
    proc_db = tmp_path / "processed_fills.db"
    raw_db = tmp_path / "raw_fills.db"
    _seed_processed_db(proc_db)
    _seed_raw_db(raw_db)

    service = ExecutionHistoryQueryService(
        proc_fills_db_path=str(proc_db),
        raw_fills_db_path=str(raw_db),
    )

    rows = service.list_order_history(order_id="1001", limit=10)

    assert len(rows) == 1
    assert rows[0]["route_count"] == 2
    assert rows[0]["fill_count"] == 2
    assert rows[0]["total_fill_shares"] == 150.0
    assert round(rows[0]["average_fill_price"], 6) == round((189.25 * 100 + 190.0 * 50) / 150, 6)


def test_execution_history_service_builds_route_summaries(tmp_path: Path):
    proc_db = tmp_path / "processed_fills.db"
    raw_db = tmp_path / "raw_fills.db"
    _seed_processed_db(proc_db)
    _seed_raw_db(raw_db)

    service = ExecutionHistoryQueryService(
        proc_fills_db_path=str(proc_db),
        raw_fills_db_path=str(raw_db),
    )

    rows = service.list_route_history(order_id="1001", limit=10)

    assert len(rows) == 2
    assert {row["route_id"] for row in rows} == {"7", "8"}
    route7 = next(row for row in rows if row["route_id"] == "7")
    assert route7["fill_count"] == 1
    assert route7["equ_ticker"] == "AAPL US Equity"
"""tca_route_summary fx_rate 回填口径测试（L4c）。

覆盖：
- fill_volume 加权聚合口径：与 S5.5 的 fill 量加权等价
- 回填仅作用于 fx_rate IS NULL 的行（不动已填充行）
- fill_bdib 无源时保持 NULL（报告侧安全降级，不虚高）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from DataPipeline.config import Config
from DataPipeline.storage.connection import ConnectionManager


# ── 最小 schema：fill_bdib（源）+ tca_route_summary（目标） ────────────────

_FILL_BDIB_DDL = """
    CREATE TABLE fill_bdib (
        OrderId TEXT, RouteId TEXT, order_as_of_date TEXT, mkt_timestamp TEXT,
        equ_ticker TEXT, ccy_ticker TEXT, fill_volume REAL, fill_px REAL,
        fx_rate REAL
    )
"""

_TCA_DDL = """
    CREATE TABLE tca_route_summary (
        OrderId TEXT, RouteId TEXT, order_as_of_date TEXT, Exchange TEXT,
        equ_ticker TEXT, Currency TEXT, fill REAL, p_avg REAL, fx_rate REAL,
        PRIMARY KEY (OrderId, RouteId, order_as_of_date)
    )
"""


def _make_fill_bdib(conn: sqlite3.Connection) -> None:
    """fill_bdib：K1 路由 3 条 fill（EUR，汇率 0.8/0.9/0.7），U1 路由 USD。"""
    conn.executemany(
        "INSERT INTO fill_bdib VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("K1", "R1", "20260820", "09:30:00", "X EU Equity", "USDEUR Curncy", 100.0, 10.0, 0.8),
            ("K1", "R1", "20260820", "09:30:10", "X EU Equity", "USDEUR Curncy", 200.0, 10.0, 0.9),
            ("K1", "R1", "20260820", "09:30:20", "X EU Equity", "USDEUR Curncy", 700.0, 10.0, 0.7),
            ("U1", "R1", "20260820", "09:30:00", "A US Equity", "USD Curncy", 100.0, 10.0, 1.0),
        ],
    )
    conn.commit()


def _make_tca(conn: sqlite3.Connection) -> None:
    """tca_route_summary：K1 fx_rate=NULL（待回填），U1 已有 fx_rate=1.0（不动）。"""
    conn.executemany(
        "INSERT INTO tca_route_summary VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("K1", "R1", "20260820", "FP", "X EU Equity", "EUR", 1000.0, 10.0, None),
            ("U1", "R1", "20260820", "US", "A US Equity", "USD", 100.0, 10.0, 1.0),
        ],
    )
    conn.commit()


def _run_backfill(db_path: Path) -> None:
    """复用回填脚本的核心 SQL（与 backfill_tca_route_fx.py 一致）。"""
    conn = sqlite3.connect(str(db_path))
    table = Config.TCA_ROUTE_SUMMARY_TABLE
    conn.execute(
        f"""
        UPDATE {table}
        SET fx_rate = (
            SELECT SUM(b.fill_volume * b.fx_rate) / NULLIF(SUM(b.fill_volume), 0)
            FROM fill_bdib b
            WHERE b.order_as_of_date = {table}.order_as_of_date
              AND b.OrderId = {table}.OrderId AND b.RouteId = {table}.RouteId
              AND b.fx_rate IS NOT NULL
        )
        WHERE fx_rate IS NULL
          AND EXISTS (
              SELECT 1 FROM fill_bdib b
              WHERE b.order_as_of_date = {table}.order_as_of_date
                AND b.OrderId = {table}.OrderId AND b.RouteId = {table}.RouteId
                AND b.fx_rate IS NOT NULL
          )
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """构造含 fill_bdib + tca_route_summary 的临时 fill_bdib.db。"""
    path = tmp_path / "fill_bdib.db"
    conn = sqlite3.connect(str(path))
    conn.execute(_FILL_BDIB_DDL)
    conn.execute(_TCA_DDL)
    _make_fill_bdib(conn)
    _make_tca(conn)
    conn.close()
    return path


class TestTcaFxBackfill:
    def test_weighted_aggregation(self, db_path: Path):
        """fill_volume 加权聚合：EUR 汇率 = (100×0.8 + 200×0.9 + 700×0.7)/1000。"""
        _run_backfill(db_path)
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT fx_rate FROM tca_route_summary WHERE OrderId='K1'"
        ).fetchone()
        conn.close()
        expected = (100 * 0.8 + 200 * 0.9 + 700 * 0.7) / 1000
        assert row[0] == pytest.approx(expected)

    def test_existing_fx_untouched(self, db_path: Path):
        """已填充的 fx_rate（USD=1.0）不被覆盖。"""
        _run_backfill(db_path)
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT fx_rate FROM tca_route_summary WHERE OrderId='U1'"
        ).fetchone()
        conn.close()
        assert row[0] == 1.0

    def test_no_source_keeps_null(self, tmp_path: Path):
        """fill_bdib 无源的路由保持 NULL（报告侧安全降级）。"""
        path = tmp_path / "fill_bdib.db"
        conn = sqlite3.connect(str(path))
        conn.execute(_FILL_BDIB_DDL)
        conn.execute(_TCA_DDL)
        # 仅 tca 行，fill_bdib 无对应源
        conn.execute(
            "INSERT INTO tca_route_summary VALUES (?,?,?,?,?,?,?,?,?)",
            ("K2", "R1", "20260820", "KS", "Y KS Equity", "KRW", 100.0, 1000.0, None),
        )
        conn.commit()
        conn.close()
        _run_backfill(path)
        conn = sqlite3.connect(str(path))
        row = conn.execute(
            "SELECT fx_rate FROM tca_route_summary WHERE OrderId='K2'"
        ).fetchone()
        conn.close()
        assert row[0] is None

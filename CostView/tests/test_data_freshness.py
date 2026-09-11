"""数据新鲜度回归测试 — business_days_lag 纯函数 + get_latest_tca_date。

对应 B2 整改（/api/tca/data-freshness）：
- business_days_lag：交易日滞后计算口径（周一至周五），与管道
  FRESHNESS_*_BUSINESS_DAYS SLA 同一口径；
- get_latest_tca_date：表缺行 / 表缺失 / 库缺失一律降级 None（fail-safe）。
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from CostView.src.tca_query_service import TcaQueryService
from CostView.src.tca_utils import business_days_lag


# ── business_days_lag（纯函数，无 DB）───────────────────────────────────────

class TestBusinessDaysLag:
    def test_same_day_is_zero(self):
        assert business_days_lag("20260911", date(2026, 9, 11)) == 0

    def test_future_latest_is_zero(self):
        """latest 晚于 today（异常场景）按 0 处理。"""
        assert business_days_lag("20260915", date(2026, 9, 11)) == 0

    def test_one_business_day(self):
        # 2026-09-11 是周五；数据日周五，今日周五 → 0
        assert business_days_lag("20260911", date(2026, 9, 11)) == 0

    def test_friday_to_monday_is_one(self):
        """周五数据 + 周一当天 = 滞后 1 个交易日（跨周末不计）。"""
        assert business_days_lag("20260904", date(2026, 9, 7)) == 1

    def test_weekend_excluded(self):
        """周五数据 + 周日当天 = 滞后 0（周末不算交易日，规避长周末误判）。"""
        assert business_days_lag("20260904", date(2026, 9, 6)) == 0

    def test_one_week_lag(self):
        """周五数据 + 下周五 = 滞后 5 个交易日。"""
        assert business_days_lag("20260904", date(2026, 9, 11)) == 5

    def test_invalid_date_returns_fail_level(self):
        """非法日期返回必然触发 fail 的大值，不静默放行。"""
        assert business_days_lag("not-a-date", date(2026, 9, 11)) == 9999
        assert business_days_lag("", date(2026, 9, 11)) == 9999


# ── get_latest_tca_date（fixture DB）────────────────────────────────────────

def _make_fill_bdib_with_summary(path: str, dates: list[str]) -> None:
    """构造含 tca_route_summary 的 fill_bdib.db（仅日期字段参与断言）。"""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tca_route_summary (
            OrderId TEXT, RouteId TEXT, order_as_of_date TEXT,
            PRIMARY KEY (OrderId, RouteId, order_as_of_date)
        )
    """)
    for i, d in enumerate(dates):
        conn.execute(
            "INSERT INTO tca_route_summary VALUES (?, ?, ?)",
            (f"O{i}", "R1", d),
        )
    conn.commit()
    conn.close()


class TestGetLatestTcaDate:
    def test_returns_max_date(self, tmp_path: Path):
        db = str(tmp_path / "fill_bdib.db")
        _make_fill_bdib_with_summary(db, ["20260901", "20260910", "20260905"])
        svc = TcaQueryService(fill_bdib_db_path=db)
        assert svc.get_latest_tca_date() == "20260910"

    def test_empty_table_returns_none(self, tmp_path: Path):
        db = str(tmp_path / "fill_bdib.db")
        _make_fill_bdib_with_summary(db, [])
        svc = TcaQueryService(fill_bdib_db_path=db)
        assert svc.get_latest_tca_date() is None

    def test_missing_summary_table_returns_none(self, tmp_path: Path):
        """库存在但表缺失（S5.5 未运行）→ None（fail-safe）。"""
        db = str(tmp_path / "fill_bdib.db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE fill_bdib (OrderId TEXT)")
        conn.commit()
        conn.close()
        svc = TcaQueryService(fill_bdib_db_path=db)
        assert svc.get_latest_tca_date() is None

    def test_missing_db_returns_none(self, tmp_path: Path):
        """库文件缺失（mode=ro 抛 FileNotFoundError）→ None（fail-safe）。"""
        svc = TcaQueryService(fill_bdib_db_path=str(tmp_path / "absent.db"))
        assert svc.get_latest_tca_date() is None

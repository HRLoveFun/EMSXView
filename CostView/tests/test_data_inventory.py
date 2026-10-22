"""057 DL-05（064）：数据盘点测试。

覆盖子规格 §2.3 检验方法：
1. 纯函数（minutes_of_day / judge_pair_candidate / par_rate_bucket /
   coverage_pct / mde_for_sample）；
2. D1 配对聚合（≥2 券商 + 时差 ≤5min；时差超限/单券商不计）；
3. 单元样本量与 MDE（细分族分类 + 参与率分桶 + Δ 反解）；
4. BDIB 覆盖（订单簿 vs bar，缺失清单）。

夹具全部虚构数据（SEC_A/SEC_B、EQ-BRK1/2、O/R 编号）。
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest

from CostView.src.monitoring.data_inventory import (
    build_inventory,
    coverage_pct,
    judge_pair_candidate,
    mde_for_sample,
    minutes_of_day,
    par_rate_bucket,
)
from data_access.storage.connection import ConnectionManager


class TestPureFunctions:
    """① 纯函数。"""

    def test_minutes_of_day(self):
        assert minutes_of_day("09:30:00") == 570
        assert minutes_of_day("2026-10-22 14:05:30") == 845
        assert minutes_of_day("") is None
        assert minutes_of_day(None) is None
        assert minutes_of_day("garbage") is None

    def test_judge_pair_candidate(self):
        assert judge_pair_candidate(2, 3.0) is True
        assert judge_pair_candidate(2, 5.0) is True   # 等于不超
        assert judge_pair_candidate(2, 6.0) is False  # 时差超限
        assert judge_pair_candidate(1, 0.0) is False  # 单券商

    def test_par_rate_bucket(self):
        assert par_rate_bucket(0.02) == "<5%"
        assert par_rate_bucket(0.10) == "5-15%"
        assert par_rate_bucket(0.20) == "15-30%"
        assert par_rate_bucket(0.50) == ">=30%"
        assert par_rate_bucket(None) == "unknown"

    def test_coverage_pct(self):
        assert coverage_pct(50, 200) == 25.0
        assert coverage_pct(0, 0) == 0.0

    def test_mde_for_sample(self):
        # n 越大可检测 Δ 越小；与闭式公式一致
        assert mde_for_sample(100) == pytest.approx(math.sqrt(2 * (1.96 + 0.8416) ** 2 / 100), abs=0.01)
        assert mde_for_sample(1000) < mde_for_sample(100)
        assert mde_for_sample(0) is None


@pytest.fixture()
def inventory_dbs(tmp_path: Path) -> ConnectionManager:
    """三库夹具：processed_fills（配对聚合）+ fill_bdib（单元计数）+ raw_bdib（覆盖）。"""
    # processed_fills：O1 双券商同时段（候选）、O2 单券商（非候选）、
    # O3 双券商时差 30min（非候选）；O1 另含 SEC_B（bar 缺失，测覆盖）
    proc_path = tmp_path / "processed_fills.db"
    conn = sqlite3.connect(str(proc_path))
    conn.execute(
        "CREATE TABLE processed_fills ("
        "OrderId TEXT, RouteId TEXT, order_as_of_date TEXT, exchange_exec_time TEXT, "
        "route_as_of_time TEXT, Broker TEXT, StrategyType TEXT, algo TEXT, Exchange TEXT, "
        "equ_ticker TEXT, PRIMARY KEY (OrderId, RouteId, order_as_of_date))"
    )
    conn.executemany(
        "INSERT INTO processed_fills (OrderId, RouteId, order_as_of_date, exchange_exec_time, "
        "route_as_of_time, Broker, StrategyType, algo, Exchange, equ_ticker) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("O1", "R1", "20260418", "10:00:30", "09:58:00", "EQ-BRK1", "VWAP", "vwap", "US", "SEC_A US Equity"),
            ("O1", "R2", "20260418", "10:01:00", "09:59:00", "EQ-BRK2", "VWAP", "vwap", "US", "SEC_A US Equity"),
            ("O2", "R3", "20260418", "11:00:00", "10:55:00", "EQ-BRK1", "CLOSE", "close", "US", "SEC_A US Equity"),
            ("O3", "R4", "20260418", "14:00:00", "09:30:00", "EQ-BRK1", "VWAP", "vwap", "US", "SEC_B US Equity"),
            ("O3", "R5", "20260418", "14:30:00", "10:00:00", "EQ-BRK2", "VWAP", "vwap", "US", "SEC_B US Equity"),
        ],
    )
    conn.commit()
    conn.close()

    # fill_bdib：tca_route_summary 单元计数（含 DL-04 细分族分类：Custom→close）
    fb_path = tmp_path / "fill_bdib.db"
    conn = sqlite3.connect(str(fb_path))
    conn.execute(
        "CREATE TABLE tca_route_summary ("
        "OrderId TEXT, RouteId TEXT, order_as_of_date TEXT, Exchange TEXT, "
        "Broker TEXT, StrategyType TEXT, algo TEXT, par_rate REAL)"
    )
    conn.executemany(
        "INSERT INTO tca_route_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("O1", "R1", "20260418", "US", "EQ-BRK1", "VWAP", "vwap", 0.08),
            ("O1", "R2", "20260418", "US", "EQ-BRK2", "VWAP", "vwap", 0.08),
            ("O2", "R3", "20260418", "US", "EQ-BRK1", "TARGET_MOC", "close", 0.20),
        ],
    )
    conn.commit()
    conn.close()

    # raw_bdib：仅 SEC_A 有 bar（SEC_B 缺失 → 覆盖缺口）
    rb_path = tmp_path / "raw_bdib.db"
    conn = sqlite3.connect(str(rb_path))
    conn.execute(
        "CREATE TABLE raw_bdib ("
        "equ_ticker TEXT, order_as_of_date TEXT, mkt_timestamp TEXT)"
    )
    conn.executemany(
        "INSERT INTO raw_bdib VALUES (?, ?, ?)",
        [("SEC_A US Equity", "20260418", "09:30:00"), ("SEC_A US Equity", "20260418", "09:30:10")],
    )
    conn.commit()
    conn.close()

    return ConnectionManager(
        path_overrides={
            "processed_fills": proc_path,
            "fill_bdib": fb_path,
            "raw_bdib": rb_path,
        }
    )


class TestBuildInventory:
    """②③④ 集成装配。"""

    def test_pair_candidates(self, inventory_dbs):
        result = build_inventory(inventory_dbs, "20260101", "20260418")

        pair = result["pair_candidates"]
        # 3 组（O1 同时段双券商、O2 单券商、O3 双券商时差 30min）→ 仅 O1 候选
        assert pair["groups_total"] == 3
        assert pair["groups_candidate"] == 1
        assert pair["group_pct"] == pytest.approx(33.3333, abs=0.001)
        by = {(r["exchange"], r["algo"]): r for r in pair["by_market_family"]}
        assert by[("US", "vwap")]["candidates"] == 1
        assert by[("US", "close")]["candidates"] == 0

    def test_units_and_mde(self, inventory_dbs):
        result = build_inventory(inventory_dbs, "20260101", "20260418")

        units = {(u["exchange"], u["family"], u["par_bucket"]): u for u in result["units"]}
        # VWAP × 5-15% × 2 条；TARGET_MOC 经 DL-04 兜底规则归 auction_close 族 × 15-30% × 1 条
        # （CUSTOM 不在规则——语义不确定，DL-04 设计决策；虚构 broker 的 Custom 落 unmapped）
        assert units[("US", "vwap", "5-15%")]["n"] == 2
        assert units[("US", "auction_close", "15-30%")]["n"] == 1
        assert units[("US", "vwap", "5-15%")]["mde"] == mde_for_sample(2)
        assert units[("US", "auction_close", "15-30%")]["mde"] is not None

    def test_bdib_coverage(self, inventory_dbs):
        result = build_inventory(inventory_dbs, "20260101", "20260418")

        bdib = result["bdib_coverage"]
        assert bdib["order_book"] == 2  # SEC_A + SEC_B
        assert bdib["with_bars"] == 1
        assert bdib["coverage_pct"] == 50.0
        assert bdib["missing_count"] == 1
        # SEC_B 后缀 US 在白名单 → 真缺口（白名单外缺失单独计数）
        assert bdib["missing_in_whitelist"] == 1
        assert bdib["missing_in_sample"] == ["SEC_B US Equity"]
        assert bdib["missing_outside_whitelist"] == 0

"""057 DL-12（063）：路由到达价与延迟拆分（本侧自给 + 上游对账切换）测试。

覆盖子规格 §2.4 检验方法：
1. 自给口径纯函数（arrival_price_from_bars / latency_seconds）；
2. 三级降级链（resolve_arrival_fields + load_upstream_arrival 列检测）；
3. 对账机制（reconcile_arrival：<1bp 判定、占比、max 差异、跳过规则）；
4. 集成装配（build_route_arrival_context 三库 join + 维度独立降级 + 覆盖率披露）。

夹具全部虚构数据（SEC_A/SEC_B 虚构 ticker、O/R 虚构订单路由号）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from CostView.src.monitoring.route_arrival import (
    RECONCILE_MIN_PCT,
    RECONCILE_TOLERANCE_BPS,
    arrival_coverage,
    arrival_price_from_bars,
    build_route_arrival_context,
    latency_seconds,
    load_upstream_arrival,
    reconcile_arrival,
    resolve_arrival_fields,
)
from data_access.storage.connection import ConnectionManager


def _route(**overrides: Any) -> SimpleNamespace:
    """最小路由替身（build/coverage 只按属性访问）。"""
    base: dict[str, Any] = {
        "OrderId": "O1", "RouteId": "R1", "order_as_of_date": "20260418",
        "equ_ticker": "SEC_A US Equity",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture()
def arrival_dbs(tmp_path: Path) -> ConnectionManager:
    """三库夹具：processed_fills（下达/首笔）+ raw_bdib（bar）+ fill_bdib（汇总表）。

    O1/R1：SEC_A 当日 09:58:00 下达、10:00:30 首笔；bar 09:50/10:00/10:10。
    O2/R2：SEC_B 当日 14:30:00 下达、14:31:00 首笔；raw_bdib 无该 ticker
    （用于验证 p_route_arrival 与 algo_latency_sec 独立降级）。
    """
    proc_path = tmp_path / "processed_fills.db"
    conn = sqlite3.connect(str(proc_path))
    conn.execute(
        "CREATE TABLE processed_fills ("
        "OrderId TEXT, RouteId TEXT, order_as_of_date TEXT, "
        "route_as_of_time TEXT, exchange_exec_time TEXT, "
        "PRIMARY KEY (OrderId, RouteId, order_as_of_date))"
    )
    conn.executemany(
        "INSERT INTO processed_fills VALUES (?, ?, ?, ?, ?)",
        [
            ("O1", "R1", "20260418", "09:58:00", "10:00:30"),
            ("O2", "R2", "20260418", "14:30:00", "14:31:00"),
        ],
    )
    conn.commit()
    conn.close()

    raw_path = tmp_path / "raw_bdib.db"
    conn = sqlite3.connect(str(raw_path))
    conn.execute(
        "CREATE TABLE raw_bdib ("
        "equ_ticker TEXT, order_as_of_date TEXT, mkt_timestamp TEXT, "
        "open REAL, high REAL, low REAL, close REAL, "
        "PRIMARY KEY (equ_ticker, order_as_of_date, mkt_timestamp))"
    )
    conn.executemany(
        "INSERT INTO raw_bdib VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("SEC_A US Equity", "20260418", "09:50:00", 49.5, 50.0, 49.0, 49.8),
            ("SEC_A US Equity", "20260418", "10:00:00", 50.0, 50.5, 49.8, 50.1),
            ("SEC_A US Equity", "20260418", "10:10:00", 50.1, 51.0, 50.0, 50.5),
        ],
    )
    conn.commit()
    conn.close()

    fill_path = tmp_path / "fill_bdib.db"
    conn = sqlite3.connect(str(fill_path))
    conn.execute(
        "CREATE TABLE tca_route_summary ("
        "OrderId TEXT, RouteId TEXT, order_as_of_date TEXT, equ_ticker TEXT, "
        "PRIMARY KEY (OrderId, RouteId, order_as_of_date))"
    )
    conn.executemany(
        "INSERT INTO tca_route_summary VALUES (?, ?, ?, ?)",
        [
            ("O1", "R1", "20260418", "SEC_A US Equity"),
            ("O2", "R2", "20260418", "SEC_B US Equity"),
        ],
    )
    conn.commit()
    conn.close()

    return ConnectionManager(path_overrides={
        "processed_fills": proc_path,
        "raw_bdib": raw_path,
        "fill_bdib": fill_path,
    })


# ── 1. 自给口径纯函数 ────────────────────────────────────────────────────────


class TestArrivalPriceFromBars:
    """bars 为当日升序 (mkt_timestamp, close, open)。"""

    BARS = [
        ("09:50:00", 49.8, 49.5),
        ("10:00:00", 50.1, 50.0),
        ("10:10:00", 50.5, 50.1),
    ]

    def test_prior_bar_close(self) -> None:
        # 09:58:00 之前最近 bar = 09:50:00 的 close
        assert arrival_price_from_bars(self.BARS, "09:58:00") == 49.8

    def test_equal_timestamp_inclusive(self) -> None:
        # <= 语义：恰等某 bar 时刻取该 bar close
        assert arrival_price_from_bars(self.BARS, "10:00:00") == 50.1

    def test_pre_open_takes_first_open(self) -> None:
        # 盘前下达（早于当日首 bar）：取首 bar 的 open（003 p_decision 同口径）
        assert arrival_price_from_bars(self.BARS, "09:30:00") == 49.5

    def test_null_close_skipped(self) -> None:
        # as_of 前最近 bar 的 close 为 NULL → 跳过，取更早的非空 close
        bars = [("09:50:00", 49.8, 49.5), ("10:00:00", None, 50.0)]
        assert arrival_price_from_bars(bars, "10:05:00") == 49.8
        # as_of 前无任何带 close 的 bar → 回退当日首 bar 的 open
        bars_pre_null = [("09:50:00", None, 49.5), ("10:00:00", 50.1, 50.0)]
        assert arrival_price_from_bars(bars_pre_null, "09:58:00") == 49.5

    def test_empty_and_none(self) -> None:
        assert arrival_price_from_bars([], "09:58:00") is None
        assert arrival_price_from_bars(self.BARS, None) is None
        assert arrival_price_from_bars(self.BARS, "") is None


class TestLatencySeconds:
    def test_same_day_diff(self) -> None:
        assert latency_seconds("09:58:00", "10:00:30") == 150.0

    def test_first_fill_before_as_of_is_none(self) -> None:
        # 首笔早于下达 = 数据异常，不产负延迟
        assert latency_seconds("10:00:00", "09:59:00") is None

    def test_invalid_or_empty_is_none(self) -> None:
        assert latency_seconds(None, "10:00:30") is None
        assert latency_seconds("10:00:00", None) is None
        assert latency_seconds("bad", "10:00:00") is None
        assert latency_seconds("10:00:00", "10:00") is None


# ── 2. 三级降级链 ────────────────────────────────────────────────────────────


class TestResolveArrivalFields:
    def test_upstream_first(self) -> None:
        assert resolve_arrival_fields(49.8, 49.81) == (49.8, "upstream")

    def test_selfsup_when_upstream_missing(self) -> None:
        assert resolve_arrival_fields(None, 49.8) == (49.8, "self")

    def test_missing_when_both_absent(self) -> None:
        assert resolve_arrival_fields(None, None) == (None, "missing")

    def test_upstream_zero_is_used(self) -> None:
        # 0 是有效上游值（非 None），不得回退自给
        assert resolve_arrival_fields(0.0, 49.8) == (0.0, "upstream")


# ── 3. 对账机制 ──────────────────────────────────────────────────────────────


class TestReconcileArrival:
    def _selfsup(self, n: int) -> dict:
        return {(f"O{i}", f"R{i}", "20260418"): 50.0 for i in range(n)}

    def test_nine_within_one_over(self) -> None:
        # 10 条中 9 条差异 <1bp、1 条 5bp：占比 90%、max≈5bp、样例含超限行
        upstream = self._selfsup(10)
        upstream[("O0", "R0", "20260418")] = 50.0 * (1 + 5e-4)  # 5bp
        report = reconcile_arrival(upstream, self._selfsup(10))
        assert report["compared"] == 10
        assert report["within_1bp"] == 9
        assert report["pct_within_1bp"] == 90.0
        assert report["pct_within_1bp"] < RECONCILE_MIN_PCT
        assert report["max_diff_bps"] == pytest.approx(5.0, abs=0.01)
        assert report["over_tolerance_examples"][0]["route_key"] == ["O0", "R0", "20260418"]

    def test_all_within(self) -> None:
        upstream = self._selfsup(10)
        upstream[("O3", "R3", "20260418")] = 50.0 * (1 + 0.5e-4)  # 0.5bp
        report = reconcile_arrival(upstream, self._selfsup(10))
        assert report["pct_within_1bp"] == 100.0
        assert report["pct_within_1bp"] >= RECONCILE_MIN_PCT
        assert report["over_tolerance_examples"] == []

    def test_exactly_one_bps_is_over(self) -> None:
        # 恰好等于容差（1.0bp）不计为一致（严格小于）
        upstream = self._selfsup(1)
        upstream[("O0", "R0", "20260418")] = 50.0 * (1 + 1e-4)
        report = reconcile_arrival(upstream, self._selfsup(1))
        assert report["within_1bp"] == 0
        assert report["pct_within_1bp"] == 0.0

    def test_upstream_absent(self) -> None:
        report = reconcile_arrival({}, self._selfsup(3))
        assert report["compared"] == 0
        assert report["pct_within_1bp"] is None
        assert report["max_diff_bps"] is None

    def test_none_or_zero_selfsup_skipped(self) -> None:
        upstream = {("O0", "R0", "20260418"): 50.0, ("O1", "R1", "20260418"): 50.0}
        selfsup = self._selfsup(2)
        selfsup[("O0", "R0", "20260418")] = None
        selfsup[("O1", "R1", "20260418")] = 0.0
        report = reconcile_arrival(upstream, selfsup)
        assert report["compared"] == 0  # 不除零、不误报


# ── 4. IO：上游列检测与集成装配 ──────────────────────────────────────────────


class TestLoadUpstreamArrival:
    def test_columns_absent_returns_empty(self, arrival_dbs: ConnectionManager) -> None:
        # 上游未物化：tca_route_summary 无 p_route_arrival/algo_latency_sec 列
        assert load_upstream_arrival(arrival_dbs, "20260418", "20260418") == {}

    def test_columns_present_reads_values(self, arrival_dbs: ConnectionManager, tmp_path: Path) -> None:
        conn = sqlite3.connect(str(tmp_path / "fill_bdib.db"))
        conn.execute(
            "ALTER TABLE tca_route_summary "
            "ADD COLUMN p_route_arrival REAL"
        )
        conn.execute(
            "ALTER TABLE tca_route_summary "
            "ADD COLUMN algo_latency_sec REAL"
        )
        conn.execute(
            "UPDATE tca_route_summary SET p_route_arrival = 49.8, "
            "algo_latency_sec = 150.0 WHERE OrderId = 'O1'"
        )
        conn.commit()
        conn.close()

        upstream = load_upstream_arrival(arrival_dbs, "20260418", "20260418")
        assert upstream[("O1", "R1", "20260418")] == {
            "p_route_arrival": 49.8, "algo_latency_sec": 150.0,
        }
        assert upstream[("O2", "R2", "20260418")]["p_route_arrival"] is None


class TestBuildRouteArrivalContext:
    def test_selfsupplied_values(self, arrival_dbs: ConnectionManager) -> None:
        routes = [_route(), _route(OrderId="O2", RouteId="R2", equ_ticker="SEC_B US Equity")]
        ctx = build_route_arrival_context(arrival_dbs, routes, "20260418", "20260418")

        # O1/R1：09:58 下达 → 09:50 bar close 49.8；延迟 10:00:30 − 09:58:00 = 150s
        o1 = ctx[("O1", "R1", "20260418")]
        assert o1.route_as_of_time == "09:58:00"
        assert o1.p_route_arrival == 49.8
        assert o1.arrival_bar_time == "09:50:00"
        assert o1.algo_latency_sec == 150.0
        assert o1.first_fill_time == "10:00:30"

        # O2/R2：raw_bdib 无 SEC_B → p 不可得；延迟独立仍可得（60s）
        o2 = ctx[("O2", "R2", "20260418")]
        assert o2.p_route_arrival is None
        assert o2.arrival_bar_time is None
        assert o2.algo_latency_sec == 60.0

    def test_pre_open_arrival(self, arrival_dbs: ConnectionManager) -> None:
        # 盘前下达（早于当日首 bar）→ 首 bar open
        conn = sqlite3.connect(str(arrival_dbs.get_path("processed_fills")))
        conn.execute(
            "UPDATE processed_fills SET route_as_of_time = '09:30:00' "
            "WHERE OrderId = 'O1'"
        )
        conn.commit()
        conn.close()

        ctx = build_route_arrival_context(arrival_dbs, [_route()], "20260418", "20260418")
        o1 = ctx[("O1", "R1", "20260418")]
        assert o1.p_route_arrival == 49.5
        assert o1.arrival_bar_time == "09:50:00"
        assert o1.algo_latency_sec == 1830.0  # 10:00:30 − 09:30:00

    def test_coverage(self, arrival_dbs: ConnectionManager) -> None:
        routes = [_route(), _route(OrderId="O2", RouteId="R2", equ_ticker="SEC_B US Equity")]
        ctx = build_route_arrival_context(arrival_dbs, routes, "20260418", "20260418")
        coverage = arrival_coverage(routes, ctx)
        assert coverage["total_routes"] == 2
        assert coverage["usable"]["p_route_arrival"] == 1  # SEC_B 无 bar
        assert coverage["usable"]["algo_latency_sec"] == 2
        assert coverage["pct"]["algo_latency_sec"] == 100.0

    def test_end_to_end_reconcile(self, arrival_dbs: ConnectionManager, tmp_path: Path) -> None:
        # 上游值与本侧自给值同口径时对账 100% 通过（差异 <1bp 占比 = 100）
        conn = sqlite3.connect(str(tmp_path / "fill_bdib.db"))
        conn.execute("ALTER TABLE tca_route_summary ADD COLUMN p_route_arrival REAL")
        conn.execute("ALTER TABLE tca_route_summary ADD COLUMN algo_latency_sec REAL")
        conn.execute(
            "UPDATE tca_route_summary SET p_route_arrival = 49.8005 "
            "WHERE OrderId = 'O1'"  # 与自给 49.8 差 0.1bp
        )
        conn.commit()
        conn.close()

        routes = [_route()]
        upstream = load_upstream_arrival(arrival_dbs, "20260418", "20260418")
        ctx = build_route_arrival_context(arrival_dbs, routes, "20260418", "20260418")
        report = reconcile_arrival(
            {key: value["p_route_arrival"] for key, value in upstream.items()},
            {key: value.p_route_arrival for key, value in ctx.items()},
        )
        assert report["compared"] == 1
        assert report["pct_within_1bp"] == 100.0
        assert report["pct_within_1bp"] >= RECONCILE_MIN_PCT

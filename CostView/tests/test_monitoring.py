"""监控与报告服务层测试。

覆盖：
- time_range：互斥校验、预设解析、last day 数据日期注入
- metric_coverage：18 指标白名单、覆盖率聚合 SQL、表缺失降级
- bdib_health：双源合并、四级分级（ok/partial/missing/unrecoverable）
- report_aggregator：KPI / 排行 / 直方图 / PWP 曲线
- monitoring router：互斥 422、metrics 白名单 422、响应包装
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from CostView.src.monitoring import (
    BdibHealthService,
    MetricCoverageService,
    TcaReportAggregator,
    fetch_latest_tca_date,
    get_filter_options,
    refresh_dim_values,
    resolve_time_range,
    validate_metrics,
)
from CostView.src.monitoring.metric_coverage import COMPUTED_METRICS
from DataPipeline.storage.connection import AccessTier, ConnectionManager


# ── Fixtures ──────────────────────────────────────────────────────────────

_TCA_DDL = """
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
        -- 003-tca-core-benchmarks: Phase 0 核心基准
        p_arrival REAL, p_close REAL, arrival_cost_bps REAL, close_cost_bps REAL,
        opportunity_cost REAL,
        -- 003-tca-core-benchmarks: Phase 1 Wagner IS / 风险 / 冲击
        p_decision REAL, delay_cost REAL, trading_cost REAL, wagner_is REAL,
        wagner_is_bps REAL, cost_stddev REAL, cost_p95 REAL, cost_cvar REAL,
        order_duration_sec REAL, exec_rate_shares_per_min REAL,
        temp_impact_5min_bps REAL, temp_impact_10min_bps REAL,
        temp_impact_30min_bps REAL, perm_impact_bps REAL,
        recovery_truncated INTEGER,
        PRIMARY KEY (OrderId, RouteId, order_as_of_date)
    )
"""


def _insert_route(conn: sqlite3.Connection, order_id: str, oad: str, **overrides) -> None:
    """插入一条最小 tca_route_summary 记录，指标默认有值，可用 overrides 置 None。

    fill 为成交股数（FillShares 口径，非百分比）；par_rate 为 0-1 小数。
    """
    values = {
        "OrderId": order_id, "RouteId": "R1", "order_as_of_date": oad,
        "Exchange": "US", "equ_ticker": "AAPL US Equity", "Side": "BUY",
        "RouteShares": 1000.0, "Broker": "BROKERA", "algo": "VWAP",
        "fill_count": 3, "fill": 900.0, "par_rate": 0.15, "p_avg": 150.0,
        "pnl_vwap": -2.5, "RPM": 0.3,
        "pwp_5": -10.0, "pwp_10": -11.0, "pwp_15": -12.0,
        "pwp_20": -13.0, "pwp_25": -14.0,
    }
    values.update(overrides)
    cols = ", ".join(values)
    placeholders = ", ".join(["?"] * len(values))
    conn.execute(
        f"INSERT INTO tca_route_summary ({cols}) VALUES ({placeholders})",
        list(values.values()),
    )


@pytest.fixture()
def fill_bdib_db(tmp_path: Path) -> Path:
    """含 tca_route_summary 的临时 fill_bdib.db（附 fill_bdib 时序空表）。"""
    db_path = tmp_path / "fill_bdib.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(_TCA_DDL)
    # analyze 完整链路会查 fill_bdib 时序表，建空表满足查询
    conn.execute("""
        CREATE TABLE fill_bdib (
            OrderId TEXT, RouteId TEXT, order_as_of_date TEXT, mkt_timestamp TEXT,
            equ_ticker TEXT, close REAL, fill_px REAL, fill_volume REAL,
            volume REAL, cum_volume_pct REAL, cum_fill_vwap REAL, cum_vwap REAL,
            cum_slippage_bps REAL, cum_tracking_error REAL
        )
    """)
    # 20260803：两条完整记录
    _insert_route(conn, "O1", "20260803")
    _insert_route(conn, "O2", "20260803", Broker="BROKERB", algo="TWAP",
                  equ_ticker="0700 HK Equity", Exchange="HK", pnl_vwap=1.5)
    # 20260804：一条 pnl_vwap/par_rate 为 NULL（模拟 BDIB 缺失）
    _insert_route(conn, "O3", "20260804", pnl_vwap=None, par_rate=None,
                  pwp_5=None, pwp_10=None, pwp_15=None, pwp_20=None, pwp_25=None)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def mgr(fill_bdib_db: Path, tmp_path: Path) -> ConnectionManager:
    """指向临时数据库的 ConnectionManager。"""
    return ConnectionManager(path_overrides={
        "fill_bdib": fill_bdib_db,
        "processed_fills": tmp_path / "processed_fills.db",
        "raw_bdib": tmp_path / "raw_bdib.db",
    })


# ── time_range ────────────────────────────────────────────────────────────

class TestResolveTimeRange:
    def test_explicit_range(self):
        tr = resolve_time_range("20260101", "20260131")
        assert (tr.start_date, tr.end_date, tr.preset) == ("20260101", "20260131", None)

    def test_conflict_rejected(self):
        with pytest.raises(ValueError, match="不能同时使用"):
            resolve_time_range("20260101", "20260131", "week")

    def test_unpaired_rejected(self):
        with pytest.raises(ValueError, match="必须同时提供"):
            resolve_time_range("20260101", None)

    def test_inverted_range_rejected(self):
        with pytest.raises(ValueError, match="起始日期晚于截止日期"):
            resolve_time_range("20260131", "20260101")

    def test_unknown_preset_rejected(self):
        with pytest.raises(ValueError, match="未知 --last 预设"):
            resolve_time_range(last="bogus")

    def test_default_is_last_day(self):
        tr = resolve_time_range(today=date(2026, 8, 5), latest_data_date="20260803")
        assert (tr.start_date, tr.end_date, tr.preset) == ("20260803", "20260803", "day")

    def test_last_day_requires_data(self):
        with pytest.raises(ValueError, match="tca_route_summary"):
            resolve_time_range(last="day", today=date(2026, 8, 5))

    def test_preset_dates(self):
        today = date(2026, 8, 5)  # 周三
        assert resolve_time_range(last="week", today=today).start_date == "20260727"
        assert resolve_time_range(last="week", today=today).end_date == "20260802"
        assert resolve_time_range(last="month", today=today).start_date == "20260701"
        assert resolve_time_range(last="month", today=today).end_date == "20260731"
        assert resolve_time_range(last="quarter", today=today).start_date == "20260401"
        assert resolve_time_range(last="quarter", today=today).end_date == "20260630"
        assert resolve_time_range(last="year", today=today).start_date == "20250101"
        assert resolve_time_range(last="year", today=today).end_date == "20251231"


# ── metric_coverage ───────────────────────────────────────────────────────

class TestValidateMetrics:
    def test_default_all(self):
        assert validate_metrics(None) == list(COMPUTED_METRICS)
        assert validate_metrics([]) == list(COMPUTED_METRICS)

    def test_subset_keeps_whitelist_order(self):
        assert validate_metrics(["pnl_vwap", "par_rate"]) == ["par_rate", "pnl_vwap"]

    def test_unknown_rejected(self):
        with pytest.raises(ValueError, match="未知指标"):
            validate_metrics(["pnl_vwap", "bogus"])


class TestMetricCoverageService:
    def test_coverage_aggregation(self, mgr: ConnectionManager):
        result = MetricCoverageService(mgr).get_coverage("20260803", "20260804")
        assert len(result["rows"]) == 2
        day1 = result["rows"][0]
        assert day1["date"] == "20260803"
        assert day1["total_routes"] == 2
        assert day1["coverage"]["pnl_vwap"] == 100.0
        day2 = result["rows"][1]
        # 20260804：pnl_vwap 为 NULL → 覆盖率 0
        assert day2["coverage"]["pnl_vwap"] == 0.0
        assert day2["coverage"]["fill"] == 100.0
        assert day2["null_counts"]["pnl_vwap"] == 1

    def test_metrics_subset(self, mgr: ConnectionManager):
        result = MetricCoverageService(mgr).get_coverage(
            "20260803", "20260804", metrics=["pnl_vwap"],
        )
        assert result["metrics"] == ["pnl_vwap"]
        assert "pnl_vwap" in result["bdib_dependent_metrics"]
        assert set(result["rows"][0]["coverage"]) == {"pnl_vwap"}

    def test_group_by_exchange(self, mgr: ConnectionManager):
        result = MetricCoverageService(mgr).get_coverage(
            "20260803", "20260803", group_by_exchange=True,
        )
        exchanges = {r["exchange"] for r in result["rows"]}
        assert exchanges == {"US", "HK"}

    def test_missing_table_returns_warning(self, tmp_path: Path):
        empty_mgr = ConnectionManager(path_overrides={
            "fill_bdib": tmp_path / "fill_bdib.db",  # 空库无表
        })
        result = MetricCoverageService(empty_mgr).get_coverage("20260803", "20260804")
        assert result["rows"] == []
        assert "data_source_warning" in result

    def test_latest_date(self, mgr: ConnectionManager):
        assert fetch_latest_tca_date(mgr) == "20260804"


# ── bdib_health ───────────────────────────────────────────────────────────

@pytest.fixture()
def health_dbs(tmp_path: Path) -> dict[str, Path]:
    """构造 processed_fills + raw_bdib 双库场景。

    - 20260803：2 个成交 ticker，raw_bdib 全覆盖 → ok
    - 20260804：2 个成交 ticker，raw_bdib 只有 1 个 → partial
    - 20260805：2 个成交 ticker，raw_bdib 无数据 → missing
    """
    proc_path = tmp_path / "processed_fills.db"
    conn = sqlite3.connect(str(proc_path))
    conn.execute(
        "CREATE TABLE processed_fills (order_as_of_date TEXT, equ_ticker TEXT)"
    )
    conn.executemany(
        "INSERT INTO processed_fills VALUES (?, ?)",
        [
            ("20260803", "AAPL US Equity"), ("20260803", "MSFT US Equity"),
            ("20260804", "AAPL US Equity"), ("20260804", "MSFT US Equity"),
            ("20260805", "AAPL US Equity"), ("20260805", "MSFT US Equity"),
        ],
    )
    conn.commit()
    conn.close()

    bdib_path = tmp_path / "raw_bdib.db"
    conn = sqlite3.connect(str(bdib_path))
    conn.execute(
        "CREATE TABLE raw_bdib (order_as_of_date TEXT, equ_ticker TEXT, close REAL)"
    )
    conn.executemany(
        "INSERT INTO raw_bdib VALUES (?, ?, ?)",
        [
            ("20260803", "AAPL US Equity", 150.0), ("20260803", "MSFT US Equity", 400.0),
            ("20260804", "AAPL US Equity", 151.0),
        ],
    )
    conn.commit()
    conn.close()
    return {"processed_fills": proc_path, "raw_bdib": bdib_path}


class TestBdibHealthService:
    def _service(self, health_dbs: dict[str, Path], tmp_path: Path) -> BdibHealthService:
        mgr = ConnectionManager(path_overrides=health_dbs)
        # parquet_dir 指向不存在目录 → 仅 SQLite 源
        return BdibHealthService(mgr, parquet_dir=tmp_path / "nonexistent_parquet")

    def test_four_level_classification(self, health_dbs, tmp_path: Path):
        service = self._service(health_dbs, tmp_path)
        result = service.get_health("20260803", "20260805", today=date(2026, 8, 5))
        status_by_date = {d["date"]: d["status"] for d in result["dates"]}
        assert status_by_date == {
            "20260803": "ok",
            "20260804": "partial",
            "20260805": "missing",
        }
        summary = result["summary"]
        assert summary["total_dates"] == 3
        assert summary["ok_dates"] == 1
        assert summary["partial_dates"] == 1
        assert summary["missing_dates"] == 1
        assert summary["latest_gap_date"] == "20260805"

    def test_unrecoverable_beyond_retention(self, health_dbs, tmp_path: Path):
        service = self._service(health_dbs, tmp_path)
        # today 远超保留窗口（180 天）→ 缺口全部不可回补
        result = service.get_health("20260803", "20260805", today=date(2027, 6, 1))
        for d in result["dates"]:
            if d["status"] != "ok":
                assert d["status"] == "unrecoverable"
                assert d["retention_days_left"] < 0

    def test_missing_tickers_listed(self, health_dbs, tmp_path: Path):
        service = self._service(health_dbs, tmp_path)
        result = service.get_health("20260804", "20260804", today=date(2026, 8, 5))
        entry = result["dates"][0]
        assert entry["missing_tickers"] == ["MSFT US Equity"]
        assert entry["coverage_pct"] == 50.0

    def test_no_fills_returns_warning(self, health_dbs, tmp_path: Path):
        service = self._service(health_dbs, tmp_path)
        result = service.get_health("20270101", "20270131", today=date(2027, 2, 1))
        assert result["dates"] == []
        assert "data_source_warning" in result


# ── report_aggregator ─────────────────────────────────────────────────────

class TestTcaReportAggregator:
    def test_kpi_and_series(self, mgr: ConnectionManager):
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        kpi = report["kpi"]
        assert kpi["route_count"] == 3
        assert kpi["total_route_shares"] == 3000.0
        assert kpi["weighted_pnl_vwap"] is not None
        assert len(report["daily_series"]) == 2
        assert len(report["pwp_curve"]) == 5

    def test_rankings_grouped(self, mgr: ConnectionManager):
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        broker_names = {r["name"] for r in report["rankings"]["by_broker"]}
        assert broker_names == {"BROKERA", "BROKERB"}
        algo_names = {r["name"] for r in report["rankings"]["by_algo"]}
        assert algo_names == {"VWAP", "TWAP"}

    def test_histogram_buckets(self, mgr: ConnectionManager):
        report = TcaReportAggregator(mgr).build_report("20260803", "20260803")
        histogram = report["pnl_vwap_histogram"]
        assert histogram
        assert sum(b["count"] for b in histogram) == 2

    def test_filters_applied(self, mgr: ConnectionManager):
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", exchange="HK",
        )
        assert report["kpi"]["route_count"] == 1
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", broker="BROKERA",
        )
        assert report["kpi"]["route_count"] == 2

    def test_multivalue_filters(self, mgr: ConnectionManager):
        """逗号分隔多值 → IN 匹配（007 前端多选）。"""
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", exchange="US,HK",
        )
        assert report["kpi"]["route_count"] == 3
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", broker="BROKERA,BROKERB",
        )
        assert report["kpi"]["route_count"] == 3
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", algo="VWAP,TWAP",
        )
        assert report["kpi"]["route_count"] == 3
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", broker="BROKERA,BROKERB", exchange="HK",
        )
        assert report["kpi"]["route_count"] == 1

    def test_kpi_notional(self, mgr: ConnectionManager):
        """总成交金额：notional（本币）+ notional_usd + fx_coverage（007）。

        fixture 无 fx_rate 列 → notional_usd/fx_coverage 为 None（向后兼容）。
        """
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        kpi = report["kpi"]
        # O1(900×150) + O2(900×150) + O3(900×150) = 405000；O2 fill=900? 见 _insert_route 默认 fill=900
        assert kpi["notional"] == pytest.approx(3 * 900.0 * 150.0)
        assert kpi["notional_usd"] is None  # 无 fx_rate 列
        assert kpi["fx_coverage"] is None

    def test_kpi_notional_usd(self, tmp_path: Path):
        """含 fx_rate 列时计算 USD notional 与 fx 覆盖率（007）。"""
        db_path = tmp_path / "fill_bdib.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(_TCA_DDL)
        conn.execute("ALTER TABLE tca_route_summary ADD COLUMN fx_rate REAL")
        # 两条：JP(JPY, fx_rate=0.006) + US(USD, fx_rate=1.0)
        _insert_route(conn, "JP1", "20260803", Exchange="JP", Currency="JPY",
                      fill=1000.0, p_avg=1000.0, fx_rate=0.006)
        _insert_route(conn, "US1", "20260803", Exchange="US", Currency="USD",
                      fill=1000.0, p_avg=100.0, fx_rate=1.0)
        conn.commit()
        conn.close()

        cm = ConnectionManager(path_overrides={
            "fill_bdib": db_path,
            "processed_fills": tmp_path / "processed_fills.db",
            "raw_bdib": tmp_path / "raw_bdib.db",
        })
        report = TcaReportAggregator(cm).build_report("20260803", "20260803")
        kpi = report["kpi"]
        # notional 本币 = 1000×1000 + 1000×100 = 1,100,000
        assert kpi["notional"] == pytest.approx(1_100_000.0)
        # notional_usd = 1000×1000×0.006 + 1000×100×1.0 = 6000 + 100000 = 106000
        assert kpi["notional_usd"] == pytest.approx(106_000.0)
        # fx_coverage：仅 1 条非 1.0（JPY）→ 1/2 = 0.5
        assert kpi["fx_coverage"] == pytest.approx(0.5)

    def test_kpi_notional_usd_minor_unit(self, tmp_path: Path):
        """小计价单位货币（GBp/ILs/ZAr）USD 成交金额 ÷100（008）。

        本币 notional 不做修正；仅 USD 换算时对 GBp/ILs/ZAr 乘 0.01。
        """
        db_path = tmp_path / "fill_bdib.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(_TCA_DDL)
        conn.execute("ALTER TABLE tca_route_summary ADD COLUMN fx_rate REAL")
        # GBp：1000×100×1.30×0.01 = 1300；ILs：1000×100×0.28×0.01 = 280
        # ZAr：1000×100×0.055×0.01 = 55；USD：1000×100×1.0 = 100000（不修正）
        _insert_route(conn, "G1", "20260803", Exchange="LN", Currency="GBp",
                      fill=1000.0, p_avg=100.0, fx_rate=1.30)
        _insert_route(conn, "I1", "20260803", Exchange="IT", Currency="ILs",
                      fill=1000.0, p_avg=100.0, fx_rate=0.28)
        _insert_route(conn, "Z1", "20260803", Exchange="SJ", Currency="ZAr",
                      fill=1000.0, p_avg=100.0, fx_rate=0.055)
        _insert_route(conn, "U1", "20260803", Exchange="US", Currency="USD",
                      fill=1000.0, p_avg=100.0, fx_rate=1.0)
        conn.commit()
        conn.close()

        cm = ConnectionManager(path_overrides={
            "fill_bdib": db_path,
            "processed_fills": tmp_path / "processed_fills.db",
            "raw_bdib": tmp_path / "raw_bdib.db",
        })
        report = TcaReportAggregator(cm).build_report("20260803", "20260803")
        kpi = report["kpi"]
        # notional_usd = 1300 + 280 + 55 + 100000 = 101635
        assert kpi["notional_usd"] == pytest.approx(101_635.0)
        # 本币 notional 不做 ÷100 修正：1000×100×4 = 400000
        assert kpi["notional"] == pytest.approx(400_000.0)

    def test_kpi_notional_usd_non_usd_missing_fx_excludes_route(self, tmp_path: Path):
        """非 USD 币种 fx_rate 缺失时该 route 贡献被排除（不虚高、不整体置空）。

        KS 市场根因回归：KRW 本币金额若被当作 USD 会虚高 3 个数量级
        （16.74B vs 真实 12M）。修复前 gap sentinel 把整个 KPI 的 notional_usd
        置 NULL（导致「总成交金额(美元)无法计算」）；修复后缺汇率的 route 仅其
        自身贡献为 NULL（SUM 忽略），其余 route 正常计入（此处仅 US 有汇率）。
        """
        db_path = tmp_path / "fill_bdib.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(_TCA_DDL)
        conn.execute("ALTER TABLE tca_route_summary ADD COLUMN fx_rate REAL")
        # KS(KRW, fx_rate=NULL) + US(USD, fx_rate=1.0)：KRW 缺汇率 → 仅该 route 不计入
        _insert_route(conn, "K1", "20260803", Exchange="KS", Currency="KRW",
                      fill=1000.0, p_avg=1000.0, fx_rate=None)
        _insert_route(conn, "U1", "20260803", Exchange="US", Currency="USD",
                      fill=1000.0, p_avg=100.0, fx_rate=1.0)
        conn.commit()
        conn.close()

        cm = ConnectionManager(path_overrides={
            "fill_bdib": db_path,
            "processed_fills": tmp_path / "processed_fills.db",
            "raw_bdib": tmp_path / "raw_bdib.db",
        })
        report = TcaReportAggregator(cm).build_report("20260803", "20260803")
        kpi = report["kpi"]
        # 本币 notional 不受影响
        assert kpi["notional"] == pytest.approx(1000 * 1000.0 + 1000 * 100.0)
        # KRW 缺汇率 → 该 route 不计入，仅 US 部分计入（而非整组 NULL）
        assert kpi["notional_usd"] == pytest.approx(100_000.0)
        # fx_coverage：仅 1 条非 1.0 缺汇率？KRW fx_rate=NULL 不计入 → 0/2 = 0.0
        assert kpi["fx_coverage"] == pytest.approx(0.0)

    def test_kpi_notional_usd_usd_missing_fx_defaults_one(self, tmp_path: Path):
        """USD/未知币种 fx_rate 缺失时仍按 1.0 兜底（USD 无需换算）。"""
        db_path = tmp_path / "fill_bdib.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(_TCA_DDL)
        conn.execute("ALTER TABLE tca_route_summary ADD COLUMN fx_rate REAL")
        _insert_route(conn, "U1", "20260803", Exchange="US", Currency="USD",
                      fill=1000.0, p_avg=100.0, fx_rate=None)
        conn.commit()
        conn.close()

        cm = ConnectionManager(path_overrides={
            "fill_bdib": db_path,
            "processed_fills": tmp_path / "processed_fills.db",
            "raw_bdib": tmp_path / "raw_bdib.db",
        })
        report = TcaReportAggregator(cm).build_report("20260803", "20260803")
        kpi = report["kpi"]
        # USD 缺汇率 → 1.0 兜底，notional_usd = 本币
        assert kpi["notional_usd"] == pytest.approx(100_000.0)

    def test_market_ranking_non_usd_missing_fx_falls_back_notional(self, tmp_path: Path):
        """有 fx_rate 列但非 USD 缺汇率时，市场排名排序回退到本币 notional。"""
        db_path = tmp_path / "fill_bdib.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(_TCA_DDL)
        conn.execute("ALTER TABLE tca_route_summary ADD COLUMN fx_rate REAL")
        # KS(KRW, fx_rate=NULL, 本币大) + US(USD, fx_rate=1.0, 本币小)
        _insert_route(conn, "K1", "20260803", Exchange="KS", Currency="KRW",
                      fill=1000.0, p_avg=1000.0, fx_rate=None)
        _insert_route(conn, "U1", "20260803", Exchange="US", Currency="USD",
                      fill=1000.0, p_avg=100.0, fx_rate=1.0)
        conn.commit()
        conn.close()

        cm = ConnectionManager(path_overrides={
            "fill_bdib": db_path,
            "processed_fills": tmp_path / "processed_fills.db",
            "raw_bdib": tmp_path / "raw_bdib.db",
        })
        report = TcaReportAggregator(cm).build_report("20260803", "20260803")
        ranking = report["market_notional_ranking"]
        # KS 本币成交额更大；notional_usd 因缺汇率排序回退本币 → KS 排第一
        assert [r["exchange"] for r in ranking] == ["KS", "US"]
        assert ranking[0]["notional_usd"] is None
        assert ranking[1]["notional_usd"] == pytest.approx(100_000.0)

    def test_markets_listed(self, mgr: ConnectionManager):
        """markets 清单列出全部市场（忽略 exchange 过滤），按 route 数降序。"""
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        exchanges = {m["exchange"] for m in report["markets"]}
        assert exchanges == {"US", "HK"}
        # US 有 2 条（O1/O3），HK 1 条（O2），US 在前
        assert report["markets"][0]["exchange"] == "US"

    def test_markets_respect_exchange_filter(self, mgr: ConnectionManager):
        """exchange 过滤作用于整个报告（含分市场概览市场清单），不再忽略。"""
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", exchange="HK",
        )
        assert report["kpi"]["route_count"] == 1
        exchanges = {m["exchange"] for m in report["markets"]}
        assert exchanges == {"HK"}

    def test_markets_respect_other_filters(self, mgr: ConnectionManager):
        """broker 过滤作用于市场清单（仅列该 broker 出现的市场）。"""
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", broker="BROKERB",
        )
        exchanges = {m["exchange"] for m in report["markets"]}
        assert exchanges == {"HK"}

    def test_market_notional_ranking(self, mgr: ConnectionManager):
        """按市场成交金额排名：成交额降序 + 中文名（fixture 无 fx_rate → USD 为 None）。"""
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        ranking = report["market_notional_ranking"]
        exchanges = [r["exchange"] for r in ranking]
        assert exchanges == ["US", "HK"]  # US(2 条) 成交额 > HK(1 条)
        assert ranking[0]["name"] == "美国"
        assert ranking[1]["name"] == "香港"
        # 每条含 route 数与成交金额
        assert ranking[0]["route_count"] == 2
        assert ranking[0]["notional"] == pytest.approx(2 * 900.0 * 150.0)
        assert ranking[0]["notional_usd"] is None  # 无 fx_rate 列 → USD 不换算

    def test_market_notional_trend(self, mgr: ConnectionManager):
        """按市场成交金额每日趋势：date × exchange。"""
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        trend = report["market_notional_trend"]
        # 3 条路由：US(20260803, 20260804) + HK(20260803)
        assert len(trend) == 3
        assert {p["date"] for p in trend} == {"20260803", "20260804"}
        assert {p["exchange"] for p in trend} == {"US", "HK"}
        assert all(p["name"] in ("美国", "香港") for p in trend)
        # 无 fx_rate 列 → notional_usd 为 None（前端空态兜底）
        assert all(p["notional_usd"] is None for p in trend)

    def test_market_notional_respects_filters(self, mgr: ConnectionManager):
        """排名/趋势均尊重 broker 过滤（仅含该 broker 的市场）。"""
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", broker="BROKERB",
        )
        ranking = report["market_notional_ranking"]
        assert [r["exchange"] for r in ranking] == ["HK"]
        trend = report["market_notional_trend"]
        assert {p["exchange"] for p in trend} == {"HK"}

    def test_metric_coverage_embedded(self, mgr: ConnectionManager):
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", metrics=["pnl_vwap"],
        )
        assert report["metric_coverage"]["metrics"] == ["pnl_vwap"]
        assert len(report["metric_coverage"]["rows"]) == 2

    def test_extra_kpis_present(self, mgr: ConnectionManager):
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        extra = report["extra_kpis"]
        # 决策基准 / 风险 / 完成率 均返回（值为 None 或数值）
        assert "arrival_cost_bps" in extra
        assert "wagner_is_bps" in extra
        assert "cost_stddev" in extra
        assert "cost_cvar" in extra
        assert "avg_fill" in extra

    def test_impact_breakdown_present(self, mgr: ConnectionManager):
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        impact = report["impact_breakdown"]
        assert "temp_impact_5min_bps" in impact
        assert "perm_impact_bps" in impact
        assert "close_cost_bps" in impact

    def test_anomaly_routes_detected(self, mgr: ConnectionManager):
        """默认阈值下 O1(par_rate 15%>10) / O2(pnl_vwap 15 / fill 30%) 触发异常。

        阈值测试与填充笔数下限解耦（min_fill_count=0），聚焦阈值判定本身。
        """
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", min_fill_count=0, min_notional_usd=0,
        )
        anomaly = report["anomaly"]
        assert anomaly["count"] == 2
        # 单档阈值：命中即异常，无 critical_count 字段
        assert "critical_count" not in anomaly
        assert all(h["unit"] for r in anomaly["rows"] for h in r["hits"])

    def test_anomaly_sorted_by_pnl_vwap_and_fill_count(self, mgr: ConnectionManager):
        """异常路由按 pnl_vwap 从负到正升序；fill_count 字段随行返回。"""
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", min_fill_count=0, min_notional_usd=0,
        )
        rows = report["anomaly"]["rows"]
        pnls = [r["pnl_vwap"] for r in rows if r["pnl_vwap"] is not None]
        assert pnls == sorted(pnls)  # 升序：负 → 正
        assert all(r["fill_count"] == 3 for r in rows)

    def test_anomaly_min_fill_count_excludes_low_fill(self, mgr: ConnectionManager):
        """填充笔数下限默认 10：algo<>close 且 fill_count<10 的路由不计入异常清单。"""
        # 夹具默认 fill_count=3、algo=VWAP/TWAP → 默认下限即排除全部
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        assert report["anomaly"]["count"] == 0
        # 放宽下限后，阈值命中的路由重新计入
        relaxed = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", min_fill_count=0, min_notional_usd=0,
        )
        assert relaxed["anomaly"]["count"] == 2

    def test_anomaly_min_fill_count_skips_close_algo(self, mgr: ConnectionManager):
        """algo="close" 不受填充笔数下限限制：低 fill_count 仍计入。"""
        conn = mgr.get_connection("fill_bdib", AccessTier.WRITE)
        _insert_route(conn, "CLS", "20260803", algo="close", fill_count=2,
                      pnl_vwap=-2.5, par_rate=0.15)
        conn.commit()
        conn.close()
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804", min_notional_usd=0)
        assert any(r["order_id"] == "CLS" for r in report["anomaly"]["rows"])

    def test_anomaly_min_notional_usd_excludes_low_value(self, tmp_path: Path):
        """成交金额(USD)下限（默认 10000）对全部路由生效：低金额路由不计入。"""
        import sqlite3

        db_path = tmp_path / "fill_bdib.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(_TCA_DDL)
        conn.execute("ALTER TABLE tca_route_summary ADD COLUMN fx_rate REAL")
        # BIG / SMALL 均触发 volume_pct_adv20（par_rate 15% >> 5%），填充笔数达标
        _insert_route(conn, "BIG", "20260803", RouteShares=1000.0, fill=900.0,
                      Amount=50000.0, fx_rate=1.0, fill_count=20, par_rate=0.15,
                      pnl_vwap=-2.5)
        _insert_route(conn, "SMALL", "20260803", RouteShares=1000.0, fill=900.0,
                      Amount=5000.0, fx_rate=1.0, fill_count=20, par_rate=0.15,
                      pnl_vwap=-2.5)
        conn.commit()
        conn.close()

        cm = ConnectionManager(path_overrides={
            "fill_bdib": db_path,
            "processed_fills": tmp_path / "processed_fills.db",
            "raw_bdib": tmp_path / "raw_bdib.db",
        })
        # 默认下限 10000：仅 BIG（50000 USD）计入
        default_report = TcaReportAggregator(cm).build_report("20260803", "20260804")
        ids = {r["order_id"] for r in default_report["anomaly"]["rows"]}
        assert ids == {"BIG"}
        # 下限放宽到 0：两条均计入
        relaxed = TcaReportAggregator(cm).build_report(
            "20260803", "20260804", min_notional_usd=0,
        )
        assert {r["order_id"] for r in relaxed["anomaly"]["rows"]} == {"BIG", "SMALL"}

    def test_anomaly_thresholds_overridable(self, mgr: ConnectionManager):
        """放宽 pnl_vwap / fill / par_rate 阈值后无路由触发异常。"""
        thresholds = {
            "tracking_error_bps": {"mode": "absolute-above", "threshold": 50},
            "fill_pct": {"mode": "below", "threshold": 10},
            "volume_pct_adv20": {"mode": "above", "threshold": 50},
        }
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", thresholds=thresholds, min_fill_count=0, min_notional_usd=0,
        )
        assert report["anomaly"]["count"] == 0

    def test_anomaly_empty_on_missing_table(self, tmp_path: Path):
        empty_mgr = ConnectionManager(path_overrides={
            "fill_bdib": tmp_path / "fill_bdib.db",  # 空库无表
        })
        report = TcaReportAggregator(empty_mgr).build_report("20260803", "20260804")
        assert report["anomaly"]["count"] == 0
        assert report["anomaly"]["rows"] == []

    def test_anomaly_fill_pct_uses_completion_rate(self, tmp_path: Path):
        """008: fill_pct 必须用完成率百分比（fill/RouteShares×100）比对阈值，而非原始股数。

        低完成率(30%) + 有本币/USD 成交金额 → 触发 fill_pct 且携带 notional 列。
        """
        import sqlite3

        db_path = tmp_path / "fill_bdib.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(_TCA_DDL)
        conn.execute("ALTER TABLE tca_route_summary ADD COLUMN fx_rate REAL")
        _insert_route(
            conn, "O1", "20260803",
            RouteShares=1000.0, fill=900.0, pnl_vwap=-2.5, par_rate=0.15,
        )
        _insert_route(
            conn, "LOW", "20260803", Exchange="US", Currency="USD",
            RouteShares=1000.0, fill=300.0, Amount=150000.0, fx_rate=1.0,
            pnl_vwap=1.0, par_rate=0.01,
        )
        conn.commit()
        conn.close()

        cm = ConnectionManager(path_overrides={
            "fill_bdib": db_path,
            "processed_fills": tmp_path / "processed_fills.db",
            "raw_bdib": tmp_path / "raw_bdib.db",
        })
        report = TcaReportAggregator(cm).build_report("20260803", "20260804", min_fill_count=0, min_notional_usd=0)
        low = next((r for r in report["anomaly"]["rows"] if r["order_id"] == "LOW"), None)
        assert low is not None
        assert any(h["key"] == "fill_pct" for h in low["hits"])
        assert low["notional_local"] == pytest.approx(150000.0)
        assert low["notional_usd"] == pytest.approx(150000.0)
        assert low["currency"] == "USD"

    def test_anomaly_notional_usd_missing_fx(self, tmp_path: Path):
        """008: fx_rate 缺失时成交金额(美元)为 None（不回退 1.0）。"""
        import sqlite3

        db_path = tmp_path / "fill_bdib.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(_TCA_DDL)
        conn.execute("ALTER TABLE tca_route_summary ADD COLUMN fx_rate REAL")
        _insert_route(
            conn, "NFX", "20260803", Exchange="KS", Currency="KRW",
            RouteShares=1000.0, fill=900.0, Amount=200000.0, fx_rate=None,
            pnl_vwap=30.0, par_rate=0.01,
        )
        conn.commit()
        conn.close()

        cm = ConnectionManager(path_overrides={
            "fill_bdib": db_path,
            "processed_fills": tmp_path / "processed_fills.db",
            "raw_bdib": tmp_path / "raw_bdib.db",
        })
        report = TcaReportAggregator(cm).build_report("20260803", "20260804", min_fill_count=0, min_notional_usd=0)
        row = next((r for r in report["anomaly"]["rows"] if r["order_id"] == "NFX"), None)
        assert row is not None
        assert row["notional_local"] == pytest.approx(200000.0)
        assert row["notional_usd"] is None


# ── report_dims（筛选维度持久化列表）────────────────────────────────────────

class TestReportDims:
    def test_refresh_builds_dims(self, mgr: ConnectionManager):
        """全量抽取：四类维度值 + 水位 + 累计次数。"""
        result = refresh_dim_values(mgr)
        assert result["refreshed"] is True
        assert result["watermark"] == "20260804"
        options = get_filter_options(mgr)
        assert set(options["exchanges"]) == {"US", "HK"}
        assert set(options["brokers"]) == {"BROKERA", "BROKERB"}
        assert set(options["algos"]) == {"VWAP", "TWAP"}
        assert set(options["symbols"]) == {"AAPL US Equity", "0700 HK Equity"}

    def test_refresh_incremental_adds_new(self, mgr: ConnectionManager):
        """增量刷新：仅扫描新日期，存量次数累加、新值首见日期正确。"""
        refresh_dim_values(mgr)
        # 追加新交易日 + 新 broker（模拟日更新增数据）
        conn = mgr.get_connection("fill_bdib", AccessTier.WRITE)
        try:
            _insert_route(conn, "O4", "20260805", Broker="BROKERC")
            conn.commit()
        finally:
            conn.close()
        result = refresh_dim_values(mgr)
        assert result["watermark"] == "20260805"
        options = get_filter_options(mgr)
        assert set(options["brokers"]) == {"BROKERA", "BROKERB", "BROKERC"}
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        try:
            # BROKERA 出现在 O1/O3 两天，次数累加为 2
            row = conn.execute(
                "SELECT occurrences FROM tca_report_dims "
                "WHERE dim_type='broker' AND value='BROKERA'",
            ).fetchone()
            assert row[0] == 2
            # 新值 BROKERC 首见/末见日期均为新日期
            row = conn.execute(
                "SELECT first_seen_date, last_seen_date FROM tca_report_dims "
                "WHERE dim_type='broker' AND value='BROKERC'",
            ).fetchone()
            assert (row[0], row[1]) == ("20260805", "20260805")
        finally:
            conn.close()

    def test_refresh_full_rebuild(self, mgr: ConnectionManager):
        """full=True 清空重建：源表已删除的值从维度表移除。"""
        refresh_dim_values(mgr)
        # 删除 O2（唯一 HK 路由），模拟历史数据回填/清理
        admin = mgr.get_admin_connection("fill_bdib")
        try:
            admin.execute("DELETE FROM tca_route_summary WHERE OrderId='O2'")
            admin.commit()
        finally:
            admin.close()
        refresh_dim_values(mgr, full=True)
        options = get_filter_options(mgr)
        assert "HK" not in options["exchanges"]
        assert "0700 HK Equity" not in options["symbols"]
        assert "BROKERB" not in options["brokers"]

    def test_filter_options_from_dims(self, mgr: ConnectionManager):
        """刷新后 build_report 的 filter_options 来自维度表（时间无关，含 exchanges）。"""
        refresh_dim_values(mgr)
        report = TcaReportAggregator(mgr).build_report("20260803", "20260803")
        options = report["filter_options"]
        assert set(options["brokers"]) == {"BROKERA", "BROKERB"}
        assert set(options["exchanges"]) == {"US", "HK"}
        # 时间范围只影响报告主体，选项覆盖全量日期（BROKERB 仅在范围外日期出现）
        assert "BROKERB" in options["brokers"]

    def test_filter_options_fallback(self, mgr: ConnectionManager):
        """维度表未初始化时回退原时间范围查询，仍返回 exchanges。"""
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        options = report["filter_options"]
        assert set(options["brokers"]) == {"BROKERA", "BROKERB"}
        assert set(options["exchanges"]) == {"US", "HK"}

    def test_get_filter_options_unavailable(self, tmp_path: Path):
        """源库无表时 get_filter_options 返回 None（调用方回退空列表）。"""
        empty_mgr = ConnectionManager(path_overrides={
            "fill_bdib": tmp_path / "fill_bdib.db",
        })
        assert get_filter_options(empty_mgr) is None

    def test_refresh_skips_missing_source(self, tmp_path: Path):
        """源表不存在时刷新不抛异常，返回 refreshed=False。"""
        empty_mgr = ConnectionManager(path_overrides={
            "fill_bdib": tmp_path / "fill_bdib.db",
        })
        result = refresh_dim_values(empty_mgr)
        assert result["refreshed"] is False


# ── monitoring router ─────────────────────────────────────────────────────

class TestMonitoringRouter:
    @pytest.fixture()
    def client(self, mgr: ConnectionManager, monkeypatch):
        """以临时 DB 注入服务构造的 TestClient。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import CostView.api.routers.monitoring as mon

        monkeypatch.setattr(mon, "BdibHealthService", lambda: BdibHealthService(mgr))
        monkeypatch.setattr(mon, "MetricCoverageService", lambda: MetricCoverageService(mgr))
        monkeypatch.setattr(mon, "TcaReportAggregator", lambda: TcaReportAggregator(mgr))
        monkeypatch.setattr(
            mon, "fetch_latest_tca_date", lambda: fetch_latest_tca_date(mgr),
        )

        app = FastAPI()
        app.include_router(mon.router)
        return TestClient(app)

    def test_metric_coverage_ok(self, client):
        resp = client.get("/api/tca/monitoring/metric-coverage",
                          params={"start_date": "20260803", "end_date": "20260804"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]["rows"]) == 2

    def test_anomaly_thresholds_endpoint(self, client):
        """008: 异常路由判定默认阈值端点（后端为唯一真相源）。"""
        resp = client.get("/api/tca/monitoring/anomaly-thresholds")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        rules = body["data"]["rules"]
        assert set(rules.keys()) == {
            "tracking_error_bps", "fill_pct", "volume_pct_adv20",
            "volume_pct_interval", "intraday_volatility", "price_movement_pct",
        }
        # fill_pct 默认阈值应为 completion-rate 口径（below / 80，单档阈值）
        assert rules["fill_pct"] == {"mode": "below", "threshold": 80, "enabled": True}
        meta = body["data"]["rule_meta"]
        # fill_pct 指标字段应为 completion_rate（修正：原误用 fill 股数）
        assert meta["fill_pct"]["metric_field"] == "completion_rate"

    def test_conflict_returns_422(self, client):
        resp = client.get("/api/tca/monitoring/bdib-health", params={
            "start_date": "20260101", "end_date": "20260131", "last": "week",
        })
        assert resp.status_code == 422
        assert "不能同时使用" in resp.json()["detail"]

    def test_unknown_metric_returns_422(self, client):
        resp = client.get("/api/tca/monitoring/metric-coverage",
                          params={"metrics": "bogus"})
        assert resp.status_code == 422
        assert "未知指标" in resp.json()["detail"]

    def test_last_day_default(self, client):
        resp = client.get("/api/tca/monitoring/report-summary")
        assert resp.status_code == 200
        data = resp.json()["data"]
        # last day = 最近数据日期 20260804
        assert data["filters"]["start_date"] == "20260804"
        assert data["kpi"]["route_count"] == 1

    def test_report_summary_filters(self, client):
        resp = client.get("/api/tca/monitoring/report-summary", params={
            "start_date": "20260803", "end_date": "20260804", "exchange": "HK",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["kpi"]["route_count"] == 1

    def test_report_summary_markets(self, client):
        """report-summary 返回 markets 清单（遵循 exchange 过滤，全报告同步收窄）。"""
        resp = client.get("/api/tca/monitoring/report-summary", params={
            "start_date": "20260803", "end_date": "20260804", "exchange": "HK",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        exchanges = {m["exchange"] for m in data["markets"]}
        assert exchanges == {"HK"}

    def test_export_html_ok(self, client):
        resp = client.get("/api/tca/monitoring/export-html", params={
            "start_date": "20260803", "end_date": "20260804",
        })
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        disposition = resp.headers.get("content-disposition", "")
        assert "tca_report_20260803_20260804.html" in disposition
        body = resp.text
        assert "<html" in body
        assert "TCA 可视化报告" in body
        assert "口径" in body          # 口径脚注
        assert "市场冲击分解" in body   # S4
        assert "异常路由明细" in body   # S6

    def test_export_html_market_tabs_radio(self, client):
        """市场概览始终展示全部市场汇总表，不再提供点击市场筛选概览范围的交互。"""
        resp = client.get("/api/tca/monitoring/export-html", params={
            "start_date": "20260803", "end_date": "20260804",
        })
        body = resp.text
        # 市场概览标题与全部市场汇总表存在
        assert "市场概览" in body
        assert "成交金额（美元）" in body
        # 不再渲染 radio 标签页（无点击筛选交互）
        assert 'id="mk-all"' not in body
        assert ':checked ~ .mk-panel' not in body
        assert 'href="#mk-' not in body

    def test_export_html_usd_amount(self, client):
        """HTML 报告落实「总成交金额（美元）」字段（KPI 卡片 + 市场表列头）。"""
        resp = client.get("/api/tca/monitoring/export-html", params={
            "start_date": "20260803", "end_date": "20260804", "min_fill_count": 0, "min_notional_usd": 0,
        })
        body = resp.text
        assert "总成交金额（美元）" in body          # KPI 卡片
        assert "成交金额（美元）" in body            # 市场汇总表列头
        assert "成交金额（本币）" in body
        # 008: 异常路由明细（S6）新增成交金额列
        assert "成交金额(本币)" in body
        assert "成交金额(USD)" in body

    def test_export_html_anomaly_fill_count_column(self, client):
        """异常路由明细表含『填充笔数』列（位于路由股数前）。"""
        resp = client.get("/api/tca/monitoring/export-html", params={
            "start_date": "20260803", "end_date": "20260804", "min_fill_count": 0, "min_notional_usd": 0,
        })
        body = resp.text
        assert "填充笔数" in body
        # 列顺序：订单参与率 → 填充笔数 → 路由股数
        assert "订单参与率</th><th>填充笔数</th><th>路由股数" in body

    def test_export_html_conflict_422(self, client):
        resp = client.get("/api/tca/monitoring/export-html", params={
            "start_date": "20260101", "end_date": "20260131", "last": "week",
        })
        assert resp.status_code == 422
        assert "不能同时使用" in resp.json()["detail"]

    def test_export_html_bad_thresholds_422(self, client):
        resp = client.get("/api/tca/monitoring/export-html", params={
            "start_date": "20260803", "end_date": "20260804",
            "thresholds": "not-json",
        })
        assert resp.status_code == 422
        assert "thresholds 非法" in resp.json()["detail"]

    def test_export_html_empty_data_no_500(self, client):
        """无数据范围返回正常 HTML（route_count=0），不 500。"""
        resp = client.get("/api/tca/monitoring/export-html", params={
            "start_date": "20270101", "end_date": "20270131",
        })
        assert resp.status_code == 200
        assert "<html" in resp.text
        assert "异常路由明细" in resp.text  # 空态提示存在
        assert "本期无异常路由" in resp.text


# ── analyze 默认日期自动触发管道 ─────────────────────────────────────────────

class TestAnalyzeAutoTrigger:
    """analyze 无显式日期且默认日期无数据时自动触发管道（202）。"""

    @pytest.fixture()
    def make_client(self, mgr: ConnectionManager, monkeypatch):
        """构造注入临时 DB 与假 trigger 的 AsyncClient 工厂。"""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        import CostView.api.routers.costview as cv
        from CostView.src.tca_query_service import TcaQueryService

        triggered: list[str] = []

        def _make(has_data: bool, client_host: str = "127.0.0.1") -> AsyncClient:
            monkeypatch.setattr(cv, "_analytics", TcaQueryService(mgr))
            monkeypatch.setattr(
                TcaQueryService, "has_data_for_date", lambda self, d: has_data,
            )
            monkeypatch.setattr(
                cv, "trigger_pipeline",
                lambda host: triggered.append(host) or {
                    "job_id": "test-job", "status": "started", "message": "ok",
                },
            )
            app = FastAPI()
            app.include_router(cv.router)
            return AsyncClient(
                transport=ASGITransport(app=app, client=(client_host, 50000)),
                base_url="http://test",
            )

        _make.triggered = triggered  # type: ignore[attr-defined]
        return _make

    @pytest.mark.asyncio
    async def test_default_date_missing_triggers_pipeline(self, make_client):
        async with make_client(has_data=False) as client:
            resp = await client.post("/api/tca/analyze", json={"filters": {}, "limit": 3})
        assert resp.status_code == 202
        data = resp.json()["data"]
        assert data["pipeline_triggered"] is True
        assert data["job_id"] == "test-job"
        assert data["target_date"]
        assert make_client.triggered == ["127.0.0.1"]

    @pytest.mark.asyncio
    async def test_default_date_present_skips_trigger(self, make_client):
        async with make_client(has_data=True) as client:
            resp = await client.post("/api/tca/analyze", json={"filters": {}, "limit": 3})
        # 有数据则走正常查询流程（临时 DB 默认日期无记录 → 503，但绝不触发管道）
        assert resp.status_code != 202
        assert make_client.triggered == []

    @pytest.mark.asyncio
    async def test_explicit_date_never_triggers(self, make_client):
        async with make_client(has_data=False) as client:
            resp = await client.post("/api/tca/analyze", json={
                "filters": {"start_date": "20260803", "end_date": "20260803"}, "limit": 3,
            })
        assert resp.status_code == 200
        assert resp.json()["data"]["total_orders"] == 2
        assert make_client.triggered == []

    @pytest.mark.asyncio
    async def test_remote_caller_gets_503(self, make_client):
        async with make_client(has_data=False, client_host="10.0.0.9") as client:
            resp = await client.post("/api/tca/analyze", json={"filters": {}, "limit": 3})
        assert resp.status_code == 503
        assert "仅限本机调用" in resp.json()["detail"]
        assert make_client.triggered == []

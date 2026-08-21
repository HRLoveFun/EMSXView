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
    resolve_time_range,
    validate_metrics,
)
from CostView.src.monitoring.metric_coverage import COMPUTED_METRICS
from DataPipeline.storage.connection import ConnectionManager


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

    def test_markets_listed(self, mgr: ConnectionManager):
        """markets 清单列出全部市场（忽略 exchange 过滤），按 route 数降序。"""
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        exchanges = {m["exchange"] for m in report["markets"]}
        assert exchanges == {"US", "HK"}
        # US 有 2 条（O1/O3），HK 1 条（O2），US 在前
        assert report["markets"][0]["exchange"] == "US"

    def test_markets_ignore_exchange_filter(self, mgr: ConnectionManager):
        """exchange 过滤只影响报告主体，不影响市场标签页清单。"""
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", exchange="HK",
        )
        assert report["kpi"]["route_count"] == 1
        exchanges = {m["exchange"] for m in report["markets"]}
        assert exchanges == {"US", "HK"}

    def test_markets_respect_other_filters(self, mgr: ConnectionManager):
        """broker 过滤作用于市场清单（仅列该 broker 出现的市场）。"""
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", broker="BROKERB",
        )
        exchanges = {m["exchange"] for m in report["markets"]}
        assert exchanges == {"HK"}

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
        """默认阈值下 O1(par_rate 15%>10) / O2(pnl_vwap 15 / fill 30%) 触发 critical。"""
        report = TcaReportAggregator(mgr).build_report("20260803", "20260804")
        anomaly = report["anomaly"]
        assert anomaly["count"] == 2
        assert anomaly["critical_count"] == 2
        severities = {r["severity"] for r in anomaly["rows"]}
        assert severities == {"critical"}

    def test_anomaly_thresholds_overridable(self, mgr: ConnectionManager):
        """放宽 pnl_vwap / fill / par_rate 阈值后仅 O1 触发（par_rate 无法豁免时仍触发）。"""
        thresholds = {
            "tracking_error_bps": {"mode": "absolute-above", "warning": 50, "critical": 100},
            "fill_pct": {"mode": "below", "warning": 10, "critical": 5},
            "volume_pct_adv20": {"mode": "above", "warning": 50, "critical": 100},
        }
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260804", thresholds=thresholds,
        )
        assert report["anomaly"]["count"] == 0

    def test_anomaly_empty_on_missing_table(self, tmp_path: Path):
        empty_mgr = ConnectionManager(path_overrides={
            "fill_bdib": tmp_path / "fill_bdib.db",  # 空库无表
        })
        report = TcaReportAggregator(empty_mgr).build_report("20260803", "20260804")
        assert report["anomaly"]["count"] == 0
        assert report["anomaly"]["rows"] == []


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
        """report-summary 返回 markets 清单（忽略 exchange 过滤）。"""
        resp = client.get("/api/tca/monitoring/report-summary", params={
            "start_date": "20260803", "end_date": "20260804", "exchange": "HK",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        exchanges = {m["exchange"] for m in data["markets"]}
        assert exchanges == {"US", "HK"}

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

"""TCA 报告指标口径回归测试。

覆盖 14 项评估指标缺陷中已落地的口径与数据质量规则：
- 缺陷 1：加权均值统一为成交额（fill × p_avg）口径，与 KPI notional 同源
- 缺陷 2：完成率改为组合级 SUM(fill) / SUM(RouteShares)，新增未成交金额缺口
- 缺陷 3：order_par_rate 按 (OrderId, order_as_of_date, Exchange) 聚合，不跨市场求和
- 缺陷 13：overfill（成交超过委托）进入异常判定与一致性探针，不再被静默放过

P0 改造（2026-09-15，见 docs/spec/adr/0018-tca-report-metrics-conventions.md）：
- 作用域统一：默认 BDIB 白名单，全报告小节共用同一 Exchange 口径并披露白名单外选择
- 加权 KPI 披露样本量与权重覆盖率（条数覆盖 ≠ 权重覆盖），低于阈值标注结论仅供参考
- 零成交路由可见：缺口金额走价格回退链、单独披露零成交路由数与委托金额、
  严重未完成路由豁免笔数/金额下限
- 过滤与订单级聚合统一经 report_measure：多选 IN 匹配、订单参与率按全量聚合
"""

from __future__ import annotations

import sqlite3
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from CostView.src.monitoring import (
    BdibHealthService,
    BdibHealthStatus,
    MetricCoverageService,
    TcaReportAggregator,
    ThresholdRules,
    export_anomaly_rows_csv,
    get_health_safe,
    query_anomaly_routes,
    query_anomaly_routes_page,
    render_report_html,
    report_spec,
    resolve_time_range,
)
from CostView.src.monitoring.metric_coverage import (
    COMPUTED_METRICS,
    METRIC_NULL_REASON,
)
from CostView.src.monitoring import report_measure as rm
from CostView.src.monitoring.tca_report_html import (
    _fmt_order_par_rate,
    _fmt_pct,
    _render_coverage_table,
    _render_health_appendix,
)
from data_access.storage.connection import ConnectionManager

#: 与 test_monitoring.py 同构的最小表结构（含全部 38 项计算指标列）
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


def _insert_route(conn: sqlite3.Connection, order_id: str, oad: str, **overrides) -> None:
    """插入一条最小 tca_route_summary 记录，可用 overrides 覆盖任意列。"""
    values: dict[str, Any] = {
        "OrderId": order_id, "RouteId": "R1", "order_as_of_date": oad,
        "Exchange": "US", "equ_ticker": "AAPL US Equity", "Side": "BUY",
        "RouteShares": 1000.0, "Broker": "BROKERA", "algo": "VWAP",
        "fill_count": 3, "fill": 900.0, "par_rate": 0.15, "p_avg": 150.0,
        "pnl_vwap": -2.5, "RPM": 0.3,
    }
    values.update(overrides)
    cols = ", ".join(values)
    placeholders = ", ".join(["?"] * len(values))
    conn.execute(
        f"INSERT INTO tca_route_summary ({cols}) VALUES ({placeholders})",
        list(values.values()),
    )


@pytest.fixture()
def tca_mgr_factory(tmp_path: Path):
    """工厂 fixture：按给定路由行列表构造临时 fill_bdib.db 并返回 ConnectionManager。

    ``with_fx=True`` 额外补 fx_rate 列，用于 USD 口径（金额缺口 / 零成交委托金额）用例。
    """
    counter = {"n": 0}

    def _make(rows: list[dict[str, Any]], *, with_fx: bool = False) -> ConnectionManager:
        counter["n"] += 1
        db_path = tmp_path / f"fill_bdib_{counter['n']}.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(_TCA_DDL)
        if with_fx:
            conn.execute("ALTER TABLE tca_route_summary ADD COLUMN fx_rate REAL")
        for idx, row in enumerate(rows):
            overrides = dict(row)
            order_id = str(overrides.pop("OrderId", f"O{idx}"))
            oad = str(overrides.pop("order_as_of_date", "20260803"))
            _insert_route(conn, order_id, oad, **overrides)
        conn.commit()
        conn.close()
        return ConnectionManager(path_overrides={
            "fill_bdib": db_path,
            "processed_fills": tmp_path / "processed_fills.db",
            "raw_bdib": tmp_path / "raw_bdib.db",
        })

    return _make


def _query_anomalies(mgr: ConnectionManager):
    """按默认阈值查询异常路由（关闭金额/笔数下限，聚焦阈值判定本身）。"""
    return query_anomaly_routes(
        mgr, "20260803", "20260803", ThresholdRules.from_payload(None),
        min_fill_count=0, min_notional_usd=0.0,
    )


# ── 缺陷 1：成交额加权口径 ────────────────────────────────────────────────


class TestTradedWeighting:
    def test_weighted_pnl_vwap_uses_traded_notional(self, tca_mgr_factory):
        """加权权重为 fill × p_avg，而非 RouteShares × p_avg（意图规模）。"""
        mgr = tca_mgr_factory([
            # 未成交量大的路由：意图规模大但成交额小
            {"OrderId": "W1", "fill": 100.0, "RouteShares": 10000.0,
             "p_avg": 10.0, "pnl_vwap": 100.0, "par_rate": 0.1},
            # 成交量大的路由：成交额大
            {"OrderId": "W2", "fill": 2000.0, "RouteShares": 2000.0,
             "p_avg": 10.0, "pnl_vwap": 0.0, "par_rate": 0.1},
        ])
        kpi = TcaReportAggregator(mgr).build_report("20260803", "20260803")["kpi"]

        traded_weighted = (100.0 * 100.0 * 10.0) / (100.0 * 10.0 + 2000.0 * 10.0)
        route_weighted = (100.0 * 10000.0 * 10.0) / (10000.0 * 10.0 + 2000.0 * 10.0)

        assert kpi["weighted_pnl_vwap"] == pytest.approx(traded_weighted, rel=1e-9)
        # 旧口径（意图规模加权）会给出完全不同的结果，确认已切换
        assert abs(kpi["weighted_pnl_vwap"] - route_weighted) > 1.0

    def test_weight_denominator_matches_notional(self, tca_mgr_factory):
        """加权分母与 KPI notional 同源（fill × p_avg），可互相校验。"""
        mgr = tca_mgr_factory([
            {"OrderId": "W1", "fill": 100.0, "RouteShares": 9999.0,
             "p_avg": 10.0, "pnl_vwap": 5.0},
            {"OrderId": "W2", "fill": 300.0, "RouteShares": 1.0,
             "p_avg": 2.0, "pnl_vwap": 15.0},
        ])
        kpi = TcaReportAggregator(mgr).build_report("20260803", "20260803")["kpi"]

        assert kpi["notional"] == pytest.approx(100.0 * 10.0 + 300.0 * 2.0)
        expected = (5.0 * 1000.0 + 15.0 * 600.0) / (1000.0 + 600.0)
        assert kpi["weighted_pnl_vwap"] == pytest.approx(expected, rel=1e-9)

    def test_avg_par_rate_and_rpm_are_weighted(self, tca_mgr_factory):
        """avg_par_rate / avg_rpm 改用成交额加权，不再被小单主导。"""
        mgr = tca_mgr_factory([
            {"OrderId": "W1", "fill": 1.0, "p_avg": 1.0,
             "par_rate": 0.9, "RPM": 9.0},
            {"OrderId": "W2", "fill": 100000.0, "p_avg": 1.0,
             "par_rate": 0.01, "RPM": 0.1},
        ])
        kpi = TcaReportAggregator(mgr).build_report("20260803", "20260803")["kpi"]

        simple = (0.9 + 0.01) / 2
        weighted = (0.9 * 1.0 + 0.01 * 100000.0) / (1.0 + 100000.0)
        assert kpi["avg_par_rate"] == pytest.approx(weighted, rel=1e-9)
        assert abs(kpi["avg_par_rate"] - simple) > 0.1
        assert kpi["avg_rpm"] == pytest.approx(
            (9.0 * 1.0 + 0.1 * 100000.0) / (1.0 + 100000.0), rel=1e-9,
        )


# ── 缺陷 2：组合级完成率与未成交金额缺口 ──────────────────────────────────


class TestCompletionRate:
    def test_avg_fill_is_portfolio_level(self, tca_mgr_factory):
        """完成率为 SUM(fill)/SUM(RouteShares)，大额未成交不会被小单掩盖。"""
        mgr = tca_mgr_factory([
            {"OrderId": "F1", "fill": 99.0, "RouteShares": 100.0, "p_avg": 10.0},
            {"OrderId": "F2", "fill": 0.0, "RouteShares": 10000.0, "p_avg": 10.0},
        ])
        extra = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803",
        )["extra_kpis"]

        assert extra["avg_fill"] == pytest.approx(99.0 / 10100.0, rel=1e-9)
        naive = (99.0 / 100.0 + 0.0 / 10000.0) / 2
        assert extra["avg_fill"] < naive / 10

    def test_unfilled_notional_none_without_fx(self, tca_mgr_factory):
        """无 fx_rate 列时未成交金额缺口为 None（与 notional_usd 同语义）。"""
        mgr = tca_mgr_factory([
            {"OrderId": "F1", "fill": 500.0, "RouteShares": 1000.0,
             "p_avg": 10.0, "Currency": "USD"},
        ])
        extra = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803",
        )["extra_kpis"]

        assert extra["avg_fill"] == pytest.approx(0.5)
        assert extra["unfilled_notional_usd"] is None


# ── 缺陷 3：订单参与率按交易所聚合 ────────────────────────────────────────


class TestOrderParAggregation:
    def test_order_par_grouped_by_exchange(self, tca_mgr_factory):
        """同一 OrderId 跨交易所的路由不再求和（避免参与率失去物理意义）。"""
        mgr = tca_mgr_factory([
            {"OrderId": "P1", "RouteId": "R1", "Exchange": "US",
             "par_rate": 0.6, "pnl_vwap": -20.0},
            {"OrderId": "P1", "RouteId": "R2", "Exchange": "HK",
             "par_rate": 0.6, "pnl_vwap": -20.0},
        ])
        routes = _query_anomalies(mgr)

        assert len(routes) == 2
        assert all(r.order_par_rate == pytest.approx(0.6) for r in routes)
        assert all(r.order_par_gt100 is False for r in routes)

    def test_order_par_gt100_flagged_and_hits(self, tca_mgr_factory):
        """订单参与率求和超过 100% 时打标记并命中数据质量规则。"""
        mgr = tca_mgr_factory([
            {"OrderId": "Q1", "RouteId": "R1", "par_rate": 1.5, "pnl_vwap": -1.0},
        ])
        routes = _query_anomalies(mgr)

        assert len(routes) == 1
        assert routes[0].order_par_gt100 is True
        assert any(h["key"] == "order_par_gt100" for h in routes[0].hits)


# ── 缺陷 13：overfill 数据质量规则 ────────────────────────────────────────


class TestOverfillRule:
    def test_overfill_flagged_and_hits(self, tca_mgr_factory):
        """成交超过委托（completion_rate > 1）触发 overfill_pct 规则。"""
        mgr = tca_mgr_factory([
            {"OrderId": "V1", "fill": 1100.0, "RouteShares": 1000.0,
             "p_avg": 10.0, "pnl_vwap": -1.0, "par_rate": 0.1},
        ])
        routes = _query_anomalies(mgr)

        assert len(routes) == 1
        assert routes[0].overfill is True
        assert routes[0].completion_rate == pytest.approx(1.1)
        assert any(h["key"] == "overfill_pct" for h in routes[0].hits)

    def test_normal_completion_not_flagged(self, tca_mgr_factory):
        """正常完成率不触发 overfill_pct（规则不误报）。"""
        mgr = tca_mgr_factory([
            {"OrderId": "V1", "fill": 900.0, "RouteShares": 1000.0,
             "p_avg": 10.0, "pnl_vwap": -1.0, "par_rate": 0.1},
        ])
        routes = _query_anomalies(mgr)

        assert len(routes) == 1
        assert routes[0].overfill is False
        assert not any(h["key"] == "overfill_pct" for h in routes[0].hits)

    def test_report_data_quality_counts(self, tca_mgr_factory):
        """报告异常段落携带数据质量计数，供报告头提示区展示。"""
        mgr = tca_mgr_factory([
            {"OrderId": "V1", "fill": 1100.0, "RouteShares": 1000.0,
             "pnl_vwap": -1.0},
            {"OrderId": "Q1", "RouteId": "R1", "par_rate": 1.5, "pnl_vwap": -1.0},
        ])
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803", min_fill_count=0, min_notional_usd=0.0,
        )
        quality = report["anomaly"]["data_quality"]

        assert quality["overfill_count"] == 1
        assert quality["order_par_gt100_count"] == 1


# ── 覆盖率一致性探针 ──────────────────────────────────────────────────────


class TestCoverageConsistency:
    def test_consistency_metrics(self, tca_mgr_factory):
        """覆盖率服务给出完成率一致性百分比（overfill 占比的反面）。"""
        mgr = tca_mgr_factory([
            {"OrderId": "C1", "RouteId": "R1", "fill": 1100.0, "RouteShares": 1000.0},
            {"OrderId": "C2", "RouteId": "R1", "fill": 900.0, "RouteShares": 1000.0},
        ])
        coverage = MetricCoverageService(mgr).get_coverage(
            "20260803", "20260803", ["pnl_vwap"],
        )
        consistency = coverage["consistency"]

        assert consistency["total_routes"] == 2
        assert consistency["overfill_routes"] == 1
        assert consistency["completion_consistency_pct"] == pytest.approx(50.0)

    def test_order_par_consistency_grouped(self, tca_mgr_factory):
        """跨交易所订单不参与求和，一致性检查不误报。"""
        mgr = tca_mgr_factory([
            {"OrderId": "P1", "RouteId": "R1", "Exchange": "US", "par_rate": 0.6},
            {"OrderId": "P1", "RouteId": "R2", "Exchange": "HK", "par_rate": 0.6},
        ])
        consistency = MetricCoverageService(mgr).get_coverage(
            "20260803", "20260803", ["pnl_vwap"],
        )["consistency"]

        assert consistency["total_orders"] == 2
        assert consistency["order_par_gt100_orders"] == 0
        assert consistency["order_par_consistency_pct"] == pytest.approx(100.0)


# ── 缺陷 4：两档严重度与严重度优先排序 ────────────────────────────────────


class TestAnomalySeverity:
    def test_two_tiers_distinguished(self, tca_mgr_factory):
        """warning 档入清单、critical 档单独标注（volume_pct_adv20: 5 / 10）。"""
        mgr = tca_mgr_factory([
            # par_rate 7% → warning（5 <= 7 < 10）
            {"OrderId": "S1", "par_rate": 0.07, "pnl_vwap": -1.0},
            # par_rate 15% → critical（>= 10）
            {"OrderId": "S2", "par_rate": 0.15, "pnl_vwap": -1.0},
        ])
        routes = {r.order_id: r for r in _query_anomalies(mgr)}

        assert routes["S1"].severity == "warning"
        assert routes["S2"].severity == "critical"
        # 每条命中规则都携带 severity 字段（供渲染分级配色）
        assert all("severity" in h for r in routes.values() for h in r.hits)

    def test_sort_puts_critical_first(self, tca_mgr_factory):
        """排序以严重度优先，而非单纯按 pnl_vwap 升序。"""
        mgr = tca_mgr_factory([
            # warning 档，但 pnl_vwap 更小（若按旧排序会排最前）
            {"OrderId": "W_ID", "par_rate": 0.07, "pnl_vwap": -5.0},
            # critical 档，pnl_vwap 更大
            {"OrderId": "C_ID", "par_rate": 0.15, "pnl_vwap": 0.0},
        ])
        routes = _query_anomalies(mgr)

        assert [r.order_id for r in routes] == ["C_ID", "W_ID"]
        assert routes[0].severity == "critical"

    def test_limit_truncates_after_severity_sort(self, tca_mgr_factory):
        """limit 截断发生在严重度排序之后，截断样本无偏。"""
        mgr = tca_mgr_factory([
            {"OrderId": "W_ID", "par_rate": 0.07, "pnl_vwap": -5.0},
            {"OrderId": "C_ID", "par_rate": 0.15, "pnl_vwap": 0.0},
        ])
        routes, total = query_anomaly_routes_page(
            mgr, "20260803", "20260803", ThresholdRules.from_payload(None),
            min_fill_count=0, min_notional_usd=0.0, limit=1,
        )

        assert total == 2
        assert len(routes) == 1
        assert routes[0].order_id == "C_ID"

    def test_report_reports_truncation(self, tca_mgr_factory):
        """报告 anomaly 段落分离「全量计数」与「截断明细」。"""
        mgr = tca_mgr_factory([
            {"OrderId": "W_ID", "par_rate": 0.07, "pnl_vwap": -5.0},
            {"OrderId": "C_ID", "par_rate": 0.15, "pnl_vwap": 0.0},
        ])
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803", min_fill_count=0, min_notional_usd=0.0,
            anomaly_limit=1,
        )
        anomaly = report["anomaly"]

        assert anomaly["count"] == 2
        assert len(anomaly["rows"]) == 1
        assert anomaly["rows_truncated"] == 1
        assert anomaly["rows"][0]["severity"] == "critical"

    def test_threshold_payload_dual_and_legacy(self):
        """payload 支持双档 warning/critical，并向后兼容单档 threshold。"""
        dual = ThresholdRules.from_payload(
            {"volume_pct_adv20": {"mode": "above", "warning": 3, "critical": 6}},
        )
        assert dual.rules["volume_pct_adv20"]["warning"] == 3
        assert dual.rules["volume_pct_adv20"]["critical"] == 6

        legacy = ThresholdRules.from_payload(
            {"volume_pct_adv20": {"mode": "above", "threshold": 7}},
        )
        assert legacy.rules["volume_pct_adv20"]["warning"] == 7
        assert legacy.rules["volume_pct_adv20"]["critical"] == 7

    def test_legacy_rule_key_migrated(self):
        """014: 旧规则键 tracking_error_bps 迁移为 pnl_vwap_bps（新键优先）。"""
        rules = ThresholdRules.from_payload(
            {"tracking_error_bps": {"mode": "absolute-above", "warning": 7}},
        ).rules

        assert "tracking_error_bps" not in rules
        assert rules["pnl_vwap_bps"]["warning"] == 7

        # 新旧键同时出现时不互相覆盖（新键胜出）
        both = ThresholdRules.from_payload({
            "tracking_error_bps": {"mode": "absolute-above", "warning": 7},
            "pnl_vwap_bps": {"mode": "absolute-above", "warning": 9},
        }).rules
        assert both["pnl_vwap_bps"]["warning"] == 9


# ── 缺陷 5：全量 CSV 导出与 HTML 截断提示 ─────────────────────────────────


class TestAnomalyExport:
    def test_export_csv_contains_all_rows(self, tca_mgr_factory, tmp_path):
        """CSV 导出全量明细（不受 HTML 渲染上限影响）。"""
        mgr = tca_mgr_factory([
            {"OrderId": "V1", "fill": 1100.0, "RouteShares": 1000.0, "pnl_vwap": -1.0},
            {"OrderId": "V2", "par_rate": 1.5, "pnl_vwap": -1.0},
        ])
        routes, _ = query_anomaly_routes_page(
            mgr, "20260803", "20260803", ThresholdRules.from_payload(None),
            min_fill_count=0, min_notional_usd=0.0,
        )
        rows = [r.__dict__ for r in routes]
        csv_path = export_anomaly_rows_csv(rows, tmp_path / "anomaly.csv")
        lines = [
            line for line in csv_path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]

        assert len(lines) == len(rows) + 1
        assert "hit_rules" in lines[0]
        assert "severity" in lines[0]

    def test_html_renders_severity_tags_and_export_link(self, tca_mgr_factory):
        """HTML 渲染区分严重度配色，并输出全量导出链接。"""
        mgr = tca_mgr_factory([
            {"OrderId": "C_ID", "par_rate": 0.15, "pnl_vwap": 0.0},
        ])
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803", min_fill_count=0, min_notional_usd=0.0,
        )
        report["anomaly"]["export_ref"] = "anomaly_deadbeef0000.csv"
        html = render_report_html(report, None, "2026-09-11 10:00:00")

        assert "tag-sev-critical" in html
        assert "anomaly_deadbeef0000.csv" in html

    def test_report_renders_data_quality_notice(self, tca_mgr_factory):
        """存在 overfill 时报告渲染数据质量提示区。"""
        mgr = tca_mgr_factory([
            {"OrderId": "V1", "fill": 1100.0, "RouteShares": 1000.0, "pnl_vwap": -1.0},
        ])
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803", min_fill_count=0, min_notional_usd=0.0,
        )
        html = render_report_html(report, None, "2026-09-11 10:00:00")

        assert "数据质量提示" in html


# ── 展示层去封顶（缺陷 13） ───────────────────────────────────────────────


class TestDisplayFormatting:
    def test_pct_not_capped(self):
        """完成率不再封顶，超成交真实暴露。"""
        assert _fmt_pct(1.1) == "110.00%"
        assert _fmt_pct(0.99999) == "100.00%"

    def test_order_par_rate_flag(self):
        """订单参与率超 100% 时追加标记。"""
        assert "&gt;100%" in _fmt_order_par_rate(1.2, True)
        assert "&gt;100%" not in _fmt_order_par_rate(0.8, False)


# ── 缺陷 12：NULL 原因分类与指标白名单一致性 ──────────────────────────────


class TestMetricReasonConsistency:
    def test_keys_match_computed_metrics(self):
        """NULL 原因表键集合与计算指标白名单完全一致（防止维护漂移）。"""
        assert set(METRIC_NULL_REASON) == set(COMPUTED_METRICS)

    def test_fx_rate_not_in_computed_metrics(self):
        """fx_rate 不在指标白名单，亦不应残留在 NULL 原因表。"""
        assert "fx_rate" not in COMPUTED_METRICS
        assert "fx_rate" not in METRIC_NULL_REASON

    def test_recovery_truncated_not_claimed_source(self):
        """跨日恢复标记为条件性列，不再声明为「始终非空」。"""
        assert METRIC_NULL_REASON["recovery_truncated"] == "conditional"


# ── 缺陷 6：覆盖率双口径与整体 SLA ────────────────────────────────────────


class TestCoverageSla:
    def test_overall_coverage_aggregate(self, tca_mgr_factory):
        """整体覆盖率对日期×指标单元格汇总（非单日平均）。"""
        mgr = tca_mgr_factory([
            {"OrderId": "C1", "pnl_vwap": 1.0},
            {"OrderId": "C2", "pnl_vwap": None},
        ])
        coverage = MetricCoverageService(mgr).get_coverage(
            "20260803", "20260803", ["pnl_vwap"],
        )

        assert coverage["overall"]["coverage"] == pytest.approx(50.0)
        # 内部汇总字段不泄漏到响应
        assert "_sla_raw" not in coverage["rows"][0]

    def test_coverage_table_renders_dual_values_and_gap_highlight(self):
        """覆盖率表展示「原始 / SLA」并在缺口日高亮、tooltip 给 NULL 原因。"""
        coverage = {
            "metrics": ["pnl_vwap"],
            "bdib_dependent_metrics": ["pnl_vwap"],
            "null_reasons": {"pnl_vwap": "bdib_cutoff"},
            "expected_null_metrics": [],
            "overall": {"coverage": 80.0, "sla_coverage": 100.0},
            "rows": [{
                "date": "20260803", "exchange": None, "total_routes": 10,
                "coverage": {"pnl_vwap": 80.0},
                "sla_coverage": {"pnl_vwap": 100.0},
                "null_counts": {"pnl_vwap": 2},
            }],
        }
        html = _render_coverage_table(coverage, {"20260803"})

        assert "80.0 / 100.0" in html
        assert "bdib_cutoff" in html
        assert "#2a1f1f" in html  # 缺口日整行高亮
        assert "整体：原始 80.00% / SLA 100.00%" in html


# ── 缺陷 7：健康度精确分级、金额权重与三态降级 ────────────────────────────


class TestBdibHealthPrecision:
    def test_classify_uses_exact_missing_count(self):
        """以缺口 ticker 数精确分级，99.995% 覆盖不得误判为 ok。"""
        assert BdibHealthService._classify(0, 2000, 30) is BdibHealthStatus.OK
        assert BdibHealthService._classify(1, 2000, 30) is BdibHealthStatus.PARTIAL
        assert BdibHealthService._classify(10, 10, 30) is BdibHealthStatus.MISSING
        assert BdibHealthService._classify(1, 2000, -1) is BdibHealthStatus.UNRECOVERABLE

    def test_health_safe_timeout_is_tri_state(self):
        """扫描超时返回显式 skipped 状态，而非 None。"""

        class _Slow:
            def get_health(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                time.sleep(0.4)
                return {"status": "ok", "dates": []}

        result = get_health_safe(
            "20260803", "20260803", timeout=0.01, health_service=_Slow,
        )

        assert result == {"status": "skipped", "reason": "timeout"}

    def test_health_safe_error_is_tri_state(self):
        """扫描异常同样降级为显式状态，便于渲染区分。"""

        class _Boom:
            def get_health(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("boom")

        result = get_health_safe(
            "20260803", "20260803", timeout=5.0, health_service=_Boom,
        )

        assert result == {"status": "skipped", "reason": "error"}

    def test_health_appendix_renders_skipped_state(self):
        """未扫描与「无缺口」在渲染上可区分。"""
        html = _render_health_appendix({"status": "skipped", "reason": "timeout"})

        assert "未完成 BDIB 缺口扫描" in html
        assert "扫描超时" in html

    def test_health_appendix_renders_missing_weight(self):
        """缺口附录展示受影响 route 数与缺口成交金额。"""
        health = {
            "status": "ok",
            "dates": [{
                "date": "20260803", "status": "partial", "coverage_pct": 66.7,
                "missing_ticker_count": 1, "missing_tickers": ["MSFT US Equity"],
                "missing_route_count": 42, "missing_notional": 1234567.0,
                "retention_days_left": 20,
            }],
            "summary": {
                "total_missing_routes": 42, "total_missing_notional": 1234567.0,
            },
        }
        html = _render_health_appendix(health)

        assert "42" in html
        assert "受影响 route 数" in html


# ── 缺陷 10：图表与排行样本量披露 ─────────────────────────────────────────


class TestSampleDisclosure:
    def test_histogram_meta_excludes_null_pnl(self, tca_mgr_factory):
        """直方图 meta 区分「纳入统计」与「全量路由」。"""
        mgr = tca_mgr_factory([
            {"OrderId": "H1", "pnl_vwap": 1.0},
            {"OrderId": "H2", "pnl_vwap": -3.0},
            {"OrderId": "H3", "pnl_vwap": None},
        ])
        histogram = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803",
        )["pnl_vwap_histogram"]

        assert histogram["n_used"] == 2
        assert histogram["n_total"] == 3

    def test_rankings_disclose_sample(self, tca_mgr_factory):
        """排行披露 n_used/n_total，避免「route 数大但成本好」的误读。"""
        mgr = tca_mgr_factory([
            {"OrderId": "R1", "Broker": "A", "pnl_vwap": 1.0},
            {"OrderId": "R2", "Broker": "A", "pnl_vwap": None},
        ])
        broker_rows = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803",
        )["rankings"]["by_broker"]

        assert len(broker_rows) == 1
        assert broker_rows[0]["route_count"] == 2
        assert broker_rows[0]["n_used"] == 1

    def test_histogram_html_shows_sample_note(self, tca_mgr_factory):
        """样本覆盖率不足时图表区给出「结论仅供参考」提示。"""
        mgr = tca_mgr_factory([
            {"OrderId": "H1", "pnl_vwap": 1.0},
            {"OrderId": "H2", "pnl_vwap": None},
        ])
        report = TcaReportAggregator(mgr).build_report("20260803", "20260803")
        html = render_report_html(report, None, "2026-09-11 10:00:00")

        assert "样本 1/2" in html
        assert "样本不足，结论仅供参考" in html

    def test_daily_series_meta_discloses_coverage(self, tca_mgr_factory):
        """按日走势披露有数据交易日数，且不补零（无数据日不出现在序列中）。"""
        mgr = tca_mgr_factory([
            {"OrderId": "D1", "order_as_of_date": "20260803"},
            {"OrderId": "D2", "order_as_of_date": "20260804"},
        ])
        report = TcaReportAggregator(mgr).build_report("20260803", "20260810")

        assert report["daily_series_meta"]["covered_days"] == 2
        assert len(report["daily_series"]) == 2
        assert {p["date"] for p in report["daily_series"]} == {"20260803", "20260804"}

    def test_html_notes_daily_coverage(self, tca_mgr_factory):
        """HTML 报告在走势图下标注覆盖交易日数。"""
        mgr = tca_mgr_factory([{"OrderId": "D1", "order_as_of_date": "20260803"}])
        report = TcaReportAggregator(mgr).build_report("20260803", "20260810")
        html = render_report_html(report, None, "2026-09-11 10:00:00")

        assert "1 个有数据交易日" in html


# ── 缺陷 11：冲击分解的跨日恢复披露 ───────────────────────────────────────


class TestImpactRecoveryDisclosure:
    def test_impact_breakdown_counts_truncated(self, tca_mgr_factory):
        """冲击分解披露跨日恢复路由条数与占比。"""
        mgr = tca_mgr_factory([
            {"OrderId": "I1", "recovery_truncated": 1},
            {"OrderId": "I2", "recovery_truncated": 0},
        ])
        impact = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803",
        )["impact_breakdown"]

        assert impact["recovery_truncated_count"] == 1
        assert impact["recovery_truncated_share"] == pytest.approx(0.5)

    def test_impact_breakdown_html_notes_truncation(self, tca_mgr_factory):
        """渲染层在冲击分解下方说明跨日兜底口径。"""
        mgr = tca_mgr_factory([
            {"OrderId": "I1", "recovery_truncated": 1},
            {"OrderId": "I2", "recovery_truncated": 0},
        ])
        report = TcaReportAggregator(mgr).build_report("20260803", "20260803")
        html = render_report_html(report, None, "2026-09-11 10:00:00")

        assert "跨日兜底口径" in html


# ── 缺陷 8：时间范围 as_of_date 语义 ──────────────────────────────────────


class TestTimeRangeAsOf:
    def test_preset_day_uses_latest_data_date(self):
        """last=day 的数据截至日即最近数据日期。"""
        tr = resolve_time_range(last="day", latest_data_date="20260810")

        assert tr.as_of_date == "20260810"
        assert (tr.start_date, tr.end_date) == ("20260810", "20260810")

    def test_preset_month_uses_reference_date(self):
        """其余预设的截至日为参考日（today），与区间同源。"""
        tr = resolve_time_range(last="month", today=date(2026, 9, 11))

        assert tr.as_of_date == "20260911"
        assert (tr.start_date, tr.end_date) == ("20260801", "20260831")

    def test_explicit_range_as_of_is_end(self):
        """显式区间的截至日取用户指定截止日。"""
        tr = resolve_time_range("20260101", "20260131")

        assert tr.as_of_date == "20260131"


# ── 缺陷 14：口径声明数据化（REPORT_SPEC） ────────────────────────────────


class TestReportSpec:
    def test_report_spec_matches_implementation(self):
        """REPORT_SPEC 与聚合器 / 阈值 / 渲染常量同源。"""
        from CostView.src.monitoring.anomaly_query import DEFAULT_THRESHOLDS
        from CostView.src.monitoring.tca_report_html import (
            _MAX_ANOMALY_ROWS_RENDERED,
        )

        assert (
            report_spec.REPORT_SPEC["anomaly_row_limit"]
            == _MAX_ANOMALY_ROWS_RENDERED
        )
        # 加权表达式与聚合器实现一致
        sql = TcaReportAggregator._weighted_avg_sql("pnl_vwap")
        assert report_spec.REPORT_SPEC["weight_expression"] in sql
        # 严重度档位与阈值结构一致（warning / critical 均存在）
        levels = set(report_spec.REPORT_SPEC["anomaly_severity_levels"])
        for rule in DEFAULT_THRESHOLDS.values():
            assert levels <= set(rule)

    def test_footer_declares_version_and_limits(self):
        """脚注携带版本号、加权口径、明细上限与已知限制文档引用。"""
        text = report_spec.footer_text()

        assert report_spec.SPEC_VERSION in text
        assert "fill * p_avg" in text
        assert str(report_spec.REPORT_SPEC["anomaly_row_limit"]) in text
        assert report_spec.REPORT_SPEC["known_limitations_doc"] in text

    def test_report_spec_matches_measure_layer(self):
        """口径声明与 report_measure 实现常量一致（防「声明-实现」漂移）。"""
        from CostView.src.monitoring.tca_report_html import (
            _SAMPLE_COVERAGE_MIN_PCT,
        )

        spec = report_spec.REPORT_SPEC
        assert spec["weight_coverage_min_pct"] == rm.SAMPLE_COVERAGE_MIN_PCT
        assert _SAMPLE_COVERAGE_MIN_PCT == rm.SAMPLE_COVERAGE_MIN_PCT
        assert tuple(spec["unfilled_price_fallbacks"]) == rm.UNFILLED_PRICE_FALLBACKS
        assert tuple(spec["scope_modes"]) == (rm.WHITELIST_MODE, rm.USER_MODE)
        assert spec["scope_whitelist_source"] == "Config.BDIB_EXCHANGE"

    def test_header_shows_preset_and_as_of(self, tca_mgr_factory):
        """报告头自证报告期：preset + 数据截至日 + 口径版本。"""
        mgr = tca_mgr_factory([{"OrderId": "A1"}])
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803", as_of_date="20260803", preset="day",
        )
        html = render_report_html(report, None, "2026-09-11 10:00:00")

        assert "口径 last=day" in html
        assert "数据截至 20260803" in html
        assert f"口径 v{report_spec.SPEC_VERSION}" in html


# ── P0-1：作用域统一（白名单 / 用户口径）───────────────────────────────────


class TestReportScopeUnified:
    def test_out_of_scope_market_excluded_from_all_sections(self, tca_mgr_factory):
        """白名单外市场不进任何小节，KPI / 市场概览 / 异常 / 覆盖率四处同口径。"""
        mgr = tca_mgr_factory([
            {"OrderId": "S1", "Exchange": "US", "par_rate": 0.15, "pnl_vwap": 0.0},
            {"OrderId": "S2", "Exchange": "CN", "par_rate": 0.15, "pnl_vwap": 0.0},
        ])
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803", min_fill_count=0, min_notional_usd=0.0,
        )

        assert report["kpi"]["route_count"] == 1
        assert {m["exchange"] for m in report["markets"]} == {"US"}
        assert report["anomaly"]["count"] == 1
        assert report["metric_coverage"]["rows"][0]["total_routes"] == 1
        assert report["filters"]["scope"]["mode"] == rm.WHITELIST_MODE

    def test_user_scope_records_out_of_scope_selection(self, tca_mgr_factory):
        """用户显式选择白名单外市场时计入报告并披露 out_of_scope（不静默混入）。"""
        mgr = tca_mgr_factory([{"OrderId": "S1", "Exchange": "CN"}])
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803", exchange="CN,US",
        )
        scope = report["filters"]["scope"]

        assert scope["mode"] == rm.USER_MODE
        assert scope["out_of_scope"] == ["CN"]
        assert report["kpi"]["route_count"] == 1  # 用户口径优先，白名单外市场仍计入
        html = render_report_html(report, None, "2026-09-15 10:00:00")
        assert "不在 BDIB 白名单内" in html

    def test_coverage_respects_user_scope(self, tca_mgr_factory):
        """用户按市场过滤时覆盖率同步收窄（与 KPI 共用作用域）。"""
        mgr = tca_mgr_factory([
            {"OrderId": "U1", "Exchange": "US", "pnl_vwap": 1.0},
            {"OrderId": "H1", "Exchange": "HK", "pnl_vwap": None},
        ])
        coverage = MetricCoverageService(mgr).get_coverage(
            "20260803", "20260803", ["pnl_vwap"], scope=rm.resolve_scope("HK"),
        )

        assert coverage["scope"]["exchanges"] == ["HK"]
        assert coverage["rows"][0]["total_routes"] == 1
        assert coverage["rows"][0]["coverage"]["pnl_vwap"] == 0.0


# ── P0-2：加权 KPI 的样本量与权重覆盖披露 ─────────────────────────────────


class TestWeightCoverageDisclosure:
    def test_weight_coverage_exposes_subset_mean(self, tca_mgr_factory):
        """缺口集中在大单时：条数覆盖 50% 但权重覆盖近 0 → 标记结论不足。"""
        mgr = tca_mgr_factory([
            {"OrderId": "W1", "fill": 1.0, "p_avg": 1.0, "pnl_vwap": 0.0},
            {"OrderId": "W2", "fill": 1000.0, "p_avg": 100.0, "pnl_vwap": None},
        ])
        coverage = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803",
        )["weight_coverage"]
        entry = coverage["metrics"]["pnl_vwap"]

        assert (entry["n_used"], entry["n_total"]) == (1, 2)
        assert entry["sample_pct"] == pytest.approx(50.0)
        assert entry["weight_pct"] < 1.0
        assert entry["insufficient"] is True
        assert coverage["threshold_pct"] == rm.SAMPLE_COVERAGE_MIN_PCT

    def test_kpi_card_renders_sample_and_weight(self, tca_mgr_factory):
        """KPI 卡片副标题披露样本量与权重覆盖率（不再只有数值）。"""
        mgr = tca_mgr_factory([
            {"OrderId": "W1", "fill": 1.0, "p_avg": 1.0, "pnl_vwap": 0.0},
            {"OrderId": "W2", "fill": 1000.0, "p_avg": 100.0, "pnl_vwap": None},
        ])
        report = TcaReportAggregator(mgr).build_report("20260803", "20260803")
        html = render_report_html(report, None, "2026-09-15 10:00:00")

        assert "样本 1/2" in html
        assert "权重覆盖" in html
        assert "样本/权重覆盖不足，结论仅供参考" in html


# ── P0-3：零成交路由的机会成本可见性 ──────────────────────────────────────


class TestZeroFillVisibility:
    def test_zero_fill_counts_and_notional(self, tca_mgr_factory):
        """零成交路由的缺口金额与委托金额：p_avg 缺失时按可达价格回退计量。"""
        mgr = tca_mgr_factory([
            {"OrderId": "Z1", "fill": 0.0, "RouteShares": 1000.0, "fill_count": 0,
             "p_avg": None, "p_arrival": 20.0, "Currency": "USD", "fx_rate": 1.0},
        ], with_fx=True)
        extra = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803",
        )["extra_kpis"]

        assert extra["zero_fill_routes"] == 1
        assert extra["zero_fill_notional_usd"] == pytest.approx(20_000.0)
        # 原先 p_avg 为 NULL → 该路由对缺口贡献被 SUM 跳过（系统性低估）
        assert extra["unfilled_notional_usd"] == pytest.approx(20_000.0)
        assert extra["unfilled_notional_unpriced_routes"] == 0

    def test_unfilled_price_fallback_chain_and_unpriced(self, tca_mgr_factory):
        """价格回退链按 p_avg → p_arrival → p_decision → p_close；全缺则披露未计价。"""
        mgr = tca_mgr_factory([
            {"OrderId": "F1", "fill": 0.0, "RouteShares": 10.0, "fill_count": 0,
             "p_avg": None, "p_arrival": None, "p_decision": 5.0, "p_close": 7.0,
             "Currency": "USD", "fx_rate": 1.0},
            {"OrderId": "F2", "fill": 0.0, "RouteShares": 10.0, "fill_count": 0,
             "p_avg": None, "p_arrival": None, "p_decision": None, "p_close": None,
             "Currency": "USD", "fx_rate": 1.0},
        ], with_fx=True)
        extra = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803",
        )["extra_kpis"]

        assert extra["unfilled_notional_usd"] == pytest.approx(50.0)  # F1 用 p_decision
        assert extra["unfilled_notional_unpriced_routes"] == 1        # F2 未计价
        assert extra["zero_fill_routes"] == 2

    def test_zero_fill_route_survives_floor_filters(self, tca_mgr_factory):
        """零成交路由（fill_pct critical）不受笔数/金额下限屏蔽，最严重情形可见。"""
        mgr = tca_mgr_factory([
            {"OrderId": "Z1", "fill": 0.0, "RouteShares": 1000.0, "fill_count": 0,
             "p_avg": None, "Amount": 0.0, "algo": "VWAP"},
            {"OrderId": "N1", "fill": 990.0, "RouteShares": 1000.0, "fill_count": 1,
             "par_rate": 0.07, "pnl_vwap": -1.0},
        ])
        # 默认下限（笔数 10 / 金额 10000 USD）下：Z1 豁免、N1 仍按下限过滤
        report = TcaReportAggregator(mgr).build_report("20260803", "20260803")

        assert report["anomaly"]["count"] == 1
        assert report["anomaly"]["rows"][0]["order_id"] == "Z1"
        assert any(
            h["key"] == "fill_pct" and h["severity"] == "critical"
            for h in report["anomaly"]["rows"][0]["hits"]
        )

    def test_zero_fill_card_rendered(self, tca_mgr_factory):
        """零成交路由数与委托金额在 KPI 卡片区可见。"""
        mgr = tca_mgr_factory([
            {"OrderId": "Z1", "fill": 0.0, "RouteShares": 1000.0, "fill_count": 0,
             "p_avg": None, "p_arrival": 20.0, "Currency": "USD", "fx_rate": 1.0},
        ], with_fx=True)
        report = TcaReportAggregator(mgr).build_report("20260803", "20260803")
        html = render_report_html(report, None, "2026-09-15 10:00:00")

        assert "零成交路由" in html
        assert "完全未执行" in html


# ── P0-4：过滤条件与订单级聚合的口径一致性 ────────────────────────────────


class TestMeasureConsistency:
    def test_multivalue_filter_applies_to_anomaly(self, tca_mgr_factory):
        """多选过滤（逗号拼接）在异常清单中同样生效，不再静默清空。"""
        mgr = tca_mgr_factory([
            {"OrderId": "A1", "Broker": "BROKERA", "par_rate": 0.15},
            {"OrderId": "B1", "Broker": "BROKERB", "par_rate": 0.15},
            {"OrderId": "C1", "Broker": "BROKERC", "par_rate": 0.15},
        ])
        report = TcaReportAggregator(mgr).build_report(
            "20260803", "20260803", broker="BROKERA,BROKERB",
            min_fill_count=0, min_notional_usd=0.0,
        )

        assert report["kpi"]["route_count"] == 2
        assert report["anomaly"]["count"] == 2
        assert {r["broker"] for r in report["anomaly"]["rows"]} == {
            "BROKERA", "BROKERB",
        }

    def test_order_par_rate_uses_full_scope_not_filtered_rows(self, tca_mgr_factory):
        """订单参与率按全量聚合：按 broker 过滤后仍反映整单参与率（探针不失真）。"""
        mgr = tca_mgr_factory([
            {"OrderId": "P1", "RouteId": "R1", "Broker": "BROKERA", "par_rate": 0.6},
            {"OrderId": "P1", "RouteId": "R2", "Broker": "BROKERB", "par_rate": 0.6},
        ])
        rows, _ = query_anomaly_routes_page(
            mgr, "20260803", "20260803", ThresholdRules.from_payload(None),
            broker="BROKERA", min_fill_count=0, min_notional_usd=0.0,
        )

        assert len(rows) == 1
        assert rows[0].order_par_rate == pytest.approx(1.2)
        assert rows[0].order_par_gt100 is True

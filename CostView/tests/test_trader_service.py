"""trader_service 测试（PR-1）：分页组装 / 日期默认 / 校验 / 与 analyze-orders 对账 100 单。"""

from __future__ import annotations

import csv
import io
import threading

import pytest

from CostView.src import trader_service
from CostView.src.trader_models import TraderFilters
from CostView.tests.trader_fixtures import make_manager

_CONTRACT_KEYS = {
    "filters", "generated_at", "total_orders", "offset", "limit",
    "kpi", "probes", "anomaly_summary", "orders",
}


def _rows_fixture() -> list[dict]:
    return [
        {"OrderId": "M1", "RouteId": "R1", "fill": 700.0, "RouteShares": 1000.0,
         "Amount": 1000.0, "p_avg": 100.0, "fill_count": 4},
        {"OrderId": "M1", "RouteId": "R2", "fill": 200.0, "RouteShares": 500.0,
         "Amount": 500.0, "p_avg": 110.0, "fill_count": 2,
         "order_as_of_date": "20261022"},
        {"OrderId": "S1", "fill": 900.0, "fill_count": 3,
         "order_as_of_date": "20261021"},
        {"OrderId": "S2", "fill": 100.0, "RouteShares": 1000.0,
         "fill_count": 1, "order_as_of_date": "20261020"},
    ]


class TestOrderPage:
    def test_payload_contract_and_slicing(self, tmp_path):
        mgr = make_manager(tmp_path, _rows_fixture())
        filters = TraderFilters(
            start_date="20261020", end_date="20261022", limit=2, offset=1,
            sort="date", sort_dir="desc",
        )
        payload = trader_service.build_order_page(filters, mgr=mgr)

        assert set(payload) == _CONTRACT_KEYS
        assert payload["total_orders"] == 3
        assert payload["offset"] == 1 and payload["limit"] == 2
        # date desc：M1(22) / S1(21) / S2(20) → offset=1 取后两条
        assert [o["order_id"] for o in payload["orders"]] == ["S1", "S2"]
        assert set(payload["kpi"]) >= {"orders", "low_completion_ratio", "anomaly_orders"}
        checks = payload["probes"]["checks"]
        assert [c["id"] for c in checks] == [
            "quantity", "participation", "cost_missing", "fill_quality",
        ]
        assert payload["probes"]["spec_version"] == trader_service.TRADER_SPEC_VERSION

    def test_date_defaults_recent_trading_days(self, tmp_path):
        mgr = make_manager(tmp_path, [
            {"OrderId": f"A{i}", "order_as_of_date": f"202610{20 + i}"}
            for i in range(6)
        ])
        payload = trader_service.build_order_page_from_query(mgr=mgr)

        # 最近 5 个交易日 = 20261021..20261025（20261020 落在窗口外）
        assert payload["filters"]["start_date"] == "20261021"
        assert payload["filters"]["end_date"] == "20261025"
        assert payload["total_orders"] == 5

    def test_empty_db_raises_data_not_ready(self, tmp_path):
        mgr = make_manager(tmp_path, [])
        with pytest.raises(trader_service.DataNotReadyError):
            trader_service.build_order_page_from_query(mgr=mgr)

    def test_explicit_dates_empty_returns_zero_orders(self, tmp_path):
        mgr = make_manager(tmp_path, _rows_fixture())
        payload = trader_service.build_order_page_from_query(
            mgr=mgr, start_date="20270101", end_date="20270131",
        )
        assert payload["total_orders"] == 0
        assert payload["orders"] == []
        assert payload["kpi"]["orders"]["value"] == 0.0

    @pytest.mark.parametrize("kwargs,match", [
        ({"limit": 201}, "limit"),
        ({"offset": -1}, "offset"),
        ({"sort": "hack"}, "sort"),
        ({"sort_dir": "up"}, "sort_dir"),
        ({"completion_bucket": "lt90"}, "completion_bucket"),
        ({"quality": "bad"}, "quality"),
    ])
    def test_validation_errors(self, tmp_path, kwargs, match):
        mgr = make_manager(tmp_path, _rows_fixture())
        with pytest.raises(ValueError, match=match):
            trader_service.build_order_page_from_query(
                mgr=mgr, start_date="20261020", end_date="20261022", **kwargs,
            )


def _export_rows_fixture() -> list[dict]:
    """两单导出夹具：X1 含注入文本 / 逗号 / 负 bps；X2 仅用于上限与排序。"""
    return [
        {
            "OrderId": "X1", "RouteId": "R1", "fill": 600.0, "RouteShares": 1000.0,
            "Amount": 1000.0, "p_avg": 100.0, "p_arrival": 99.0, "p_decision": 98.0,
            "delay_cost": -10.0, "trading_cost": -20.0, "opportunity_cost": -30.0,
            "wagner_is": -50.0, "wagner_is_bps": -5.0, "fill_count": 2,
            "arrival_cost_bps": -2.0, "TraderName": "=EVIL",
            "equ_ticker": "A,B US Equity", "par_rate": 0.01,
        },
        {
            "OrderId": "X2", "RouteId": "R1", "fill": 1000.0, "RouteShares": 1000.0,
            "Amount": 1000.0, "p_avg": 50.0, "fill_count": 3,
            "TraderName": "OK", "equ_ticker": "OK US Equity", "par_rate": 0.01,
        },
    ]


def _export_manager(tmp_path):
    fills = [
        {"OrderId": "X1", "fill_id": "F1", "exec_time": "09:31:00",
         "price": 100.0, "shares": 300.0},
        {"OrderId": "X1", "fill_id": "F2", "exec_time": "09:36:00",
         "price": 101.0, "shares": 300.0},
    ]
    raw = [
        {"OrderId": "X1", "fill_id": "F1", "liquidity": "1"},
        {"OrderId": "X1", "fill_id": "F2", "liquidity": "2"},
    ]
    return make_manager(tmp_path, _export_rows_fixture(), fills=fills, raw_fills=raw)


def _csv_records(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """UTF-8-SIG CSV → (注释行, DictReader 记录)。"""
    lines = content.decode("utf-8-sig").splitlines()
    assert len(lines) >= 4
    assert all(lines[index].startswith("#") for index in range(3))
    reader = csv.DictReader(io.StringIO("\n".join(lines[3:])))
    return lines, list(reader)


class TestExportOrders:
    """210 §3.4.4 / §4.14：订单汇总 CSV 的表头、口径、注入防护与上限。"""

    def test_header_version_filters_and_columns(self, tmp_path) -> None:
        mgr = _export_manager(tmp_path)

        content, filename = trader_service.build_export_csv(
            "orders", start_date="20261022", end_date="20261022", mgr=mgr,
        )

        assert content.startswith(b"\xef\xbb\xbf")           # UTF-8-SIG（Excel 直开）
        lines, records = _csv_records(content)
        assert lines[0] == f"# spec_version={trader_service.TRADER_SPEC_VERSION}"
        assert lines[1].startswith("# generated_at=")
        assert lines[2].startswith("# filters=")
        assert '"kind":"orders"' in lines[2]
        assert '"start_date":"20261022"' in lines[2]
        assert list(records[0]) == list(trader_service.EXPORT_ORDER_COLUMNS)
        assert filename.startswith("trader_orders_20261022_20261022_")
        assert filename.endswith(".csv")

    def test_values_match_list_semantics(self, tmp_path) -> None:
        mgr = _export_manager(tmp_path)

        _, records = _csv_records(trader_service.build_export_csv(
            "orders", start_date="20261022", end_date="20261022", mgr=mgr,
        )[0])
        row = next(item for item in records if item["order_id"] == "X1")

        assert float(row["completion"]) == pytest.approx(0.6)
        assert float(row["fill"]) == pytest.approx(600.0)
        # 分母 RouteShares × p_decision = 1000 × 98；与详情成本分解同源
        assert float(row["delay_bps"]) == pytest.approx(-10 / 98_000 * 10_000)
        assert float(row["trading_bps"]) == pytest.approx(-20 / 98_000 * 10_000)
        assert float(row["opportunity_bps"]) == pytest.approx(-30 / 98_000 * 10_000)
        assert float(row["residual_bps"]) == pytest.approx(
            -5.0 - (-10 - 20 - 30) / 98_000 * 10_000,
        )
        # 逐笔上下文：span 300s / 600 股 → 120 股每分钟；被动 300/600
        assert float(row["fill_span_sec"]) == pytest.approx(300.0)
        assert float(row["speed_shares_per_min"]) == pytest.approx(120.0)
        assert float(row["passive_ratio"]) == pytest.approx(0.5)
        assert float(row["unknown_share"]) == pytest.approx(0.0)
        # 订单创建 09:25 → 路由创建 09:30
        assert float(row["order_to_route_sec"]) == pytest.approx(300.0)
        assert float(row["route_to_first_fill_sec"]) == pytest.approx(60.0)
        assert row["quality_flags"] == ""

    def test_formula_injection_and_csv_escaping(self, tmp_path) -> None:
        mgr = _export_manager(tmp_path)

        _, records = _csv_records(trader_service.build_export_csv(
            "orders", start_date="20261022", end_date="20261022", mgr=mgr,
        )[0])
        row = next(item for item in records if item["order_id"] == "X1")

        assert row["trader_name"] == "'=EVIL"      # 文本前置 ' 防公式注入
        assert row["equ_ticker"] == "A,B US Equity"  # 逗号按 CSV 规则转义后可回读

    def test_negative_numbers_are_not_escaped(self, tmp_path) -> None:
        mgr = _export_manager(tmp_path)

        _, records = _csv_records(trader_service.build_export_csv(
            "orders", start_date="20261022", end_date="20261022", mgr=mgr,
        )[0])
        row = next(item for item in records if item["order_id"] == "X1")

        # 数字列不加 '，否则 Excel 会当文本、破坏汇总
        assert row["delay_bps"].startswith("-")
        assert not row["delay_bps"].startswith("'-")

    def test_order_cap_raises_export_too_large(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(trader_service, "EXPORT_ORDER_CAP", 1)
        mgr = _export_manager(tmp_path)

        with pytest.raises(trader_service.ExportTooLargeError, match="上限"):
            trader_service.build_export_csv(
                "orders", start_date="20261022", end_date="20261022", mgr=mgr,
            )

    def test_empty_range_returns_header_only(self, tmp_path) -> None:
        mgr = _export_manager(tmp_path)

        content, _ = trader_service.build_export_csv(
            "orders", start_date="20270101", end_date="20270131", mgr=mgr,
        )
        _, records = _csv_records(content)

        assert records == []

    def test_order_without_fills_leaves_derived_columns_empty(self, tmp_path) -> None:
        """无逐笔订单：派生列留空、不打 liquidity_unknown（与列表页「无逐笔不写 0」同界）。"""
        mgr = _export_manager(tmp_path)

        _, records = _csv_records(trader_service.build_export_csv(
            "orders", start_date="20261022", end_date="20261022", mgr=mgr,
        )[0])
        row = next(item for item in records if item["order_id"] == "X2")

        assert row["passive_ratio"] == ""
        assert row["unknown_share"] == ""
        assert row["fill_span_sec"] == ""
        assert "liquidity_unknown" not in row["quality_flags"]


class TestExportFills:
    """210 §4.14：成交明细 CSV 的列、Liquidity 分类与上限。"""

    def test_fill_rows_and_liquidity(self, tmp_path) -> None:
        mgr = _export_manager(tmp_path)

        content, filename = trader_service.build_export_csv(
            "fills", start_date="20261022", end_date="20261022", mgr=mgr,
        )
        _, records = _csv_records(content)

        assert filename.startswith("trader_fills_20261022_20261022_")
        assert list(records[0]) == list(trader_service.EXPORT_FILL_COLUMNS)
        assert [row["fill_id"] for row in records] == ["F1", "F2"]
        assert [row["liquidity_class"] for row in records] == ["passive", "aggressive"]
        assert records[0]["liquidity_raw"] == "1"
        assert records[0]["ts_local"].endswith("09:31:00")
        assert records[0]["shares"] == "300.0"
        # fixture 未建 LastCapacity/LastMarket 列 → 空值，不崩溃
        assert records[0]["last_capacity"] == ""
        assert records[0]["last_market"] == ""

    def test_single_order_resolves_dates_from_library(self, tmp_path) -> None:
        mgr = _export_manager(tmp_path)

        content, filename = trader_service.build_export_csv("fills", order_id="X1", mgr=mgr)
        _, records = _csv_records(content)

        assert filename.startswith("trader_fills_20261022_20261022_")
        assert {row["order_id"] for row in records} == {"X1"}

    def test_unknown_order_is_404_semantics(self, tmp_path) -> None:
        mgr = _export_manager(tmp_path)

        with pytest.raises(trader_service.OrderNotFound):
            trader_service.build_export_csv("fills", order_id="NOPE", mgr=mgr)

    def test_fill_cap_raises_export_too_large(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(trader_service, "EXPORT_FILL_CAP", 1)
        mgr = _export_manager(tmp_path)

        with pytest.raises(trader_service.ExportTooLargeError, match="上限"):
            trader_service.build_export_csv(
                "fills", start_date="20261022", end_date="20261022", mgr=mgr,
            )

    def test_invalid_kind(self, tmp_path) -> None:
        mgr = _export_manager(tmp_path)

        with pytest.raises(ValueError, match="kind"):
            trader_service.build_export_csv("bad", mgr=mgr)

    def test_fill_cap_checked_before_streaming(self, tmp_path, monkeypatch) -> None:
        """上限必须在返回生成器前判定：流式响应开始后无法再改 422 状态码。"""
        monkeypatch.setattr(trader_service, "EXPORT_FILL_CAP", 1)
        mgr = _export_manager(tmp_path)

        with pytest.raises(trader_service.ExportTooLargeError, match="上限"):
            trader_service.stream_export_csv(
                "fills", start_date="20261022", end_date="20261022", mgr=mgr,
            )

    def test_fill_text_cells_escaped(self, tmp_path) -> None:
        fills = [{"OrderId": "X1", "fill_id": "=1+1", "exec_time": "09:31:00"}]
        raw = [{"OrderId": "X1", "fill_id": "=1+1", "liquidity": "1"}]
        mgr = make_manager(tmp_path, _export_rows_fixture(), fills=fills, raw_fills=raw)

        _, records = _csv_records(trader_service.build_export_csv(
            "fills", start_date="20261022", end_date="20261022", mgr=mgr,
        )[0])

        assert [row["fill_id"] for row in records] == ["'=1+1"]


class TestCsvCellGuard:
    """公式注入加固：覆盖前导空白（Excel 会忽略空白照常求值）与数字豁免。"""

    def test_leading_whitespace_formula_is_escaped(self) -> None:
        assert trader_service._csv_cell("\t=cmd|calc") == "'\t=cmd|calc"
        assert trader_service._csv_text(" =1+1") == "' =1+1"
        assert trader_service._csv_text("=HYPERLINK()") == "'=HYPERLINK()"

    def test_numbers_none_and_plain_text_untouched(self) -> None:
        assert trader_service._csv_cell(None) == ""
        assert trader_service._csv_cell(-5.0) == -5.0
        assert trader_service._csv_cell(float("nan")) == ""
        assert trader_service._csv_text(None) is None
        assert trader_service._csv_text("VWAP") == "VWAP"


class TestStreamExport:
    """流式入口：首块带 BOM + 表头，拼起来与一次性入口逐字节一致。"""

    def test_first_chunk_has_bom_and_header(self, tmp_path) -> None:
        mgr = _export_manager(tmp_path)

        chunks, filename = trader_service.stream_export_csv(
            "orders", start_date="20261022", end_date="20261022", mgr=mgr,
        )
        iterator = iter(chunks)
        first = next(iterator)
        rest = b"".join(iterator)

        assert first.startswith(b"\xef\xbb\xbf")
        assert b"# spec_version=" in first
        assert b"order_id,order_as_of_date,trader_name" in first
        assert rest  # 仍有数据块
        joined = first + rest
        expected, expected_name = trader_service.build_export_csv(
            "orders", start_date="20261022", end_date="20261022", mgr=mgr,
        )
        # 两次生成的 generated_at / 文件名哈希不同，正文（去注释行）应一致
        assert joined.split(b"\n", 2)[2] == expected.split(b"\n", 2)[2]
        assert filename.startswith("trader_orders_20261022_20261022_")
        assert expected_name.startswith("trader_orders_20261022_20261022_")

    def test_generator_survives_cross_thread_iteration(self, tmp_path) -> None:
        """Starlette 可能在不同工作线程执行相邻两次 ``next()``（回归）：
        连接若跨 ``yield`` 持有，SQLite 会抛 ``ProgrammingError``。"""
        mgr = make_manager(tmp_path, [
            {"OrderId": f"T{i}", "fill": 100.0, "fill_count": 1,
             "order_as_of_date": "20261022"}
            for i in range(401)          # 2 个数据块，驱动 3 次 next()
        ])
        chunks, _ = trader_service.stream_export_csv(
            "orders", start_date="20261022", end_date="20261022", mgr=mgr,
        )
        iterator = iter(chunks)

        def next_in_new_thread() -> bytes:
            box: dict[str, object] = {}

            def target() -> None:
                try:
                    box["value"] = next(iterator)
                except BaseException as exc:  # 原样回传生成器错误
                    box["error"] = exc

            worker = threading.Thread(target=target)
            worker.start()
            worker.join()
            if "error" in box:
                raise box["error"]  # type: ignore[misc]
            return box["value"]  # type: ignore[return-value]

        parts = [next_in_new_thread() for _ in range(3)]

        lines = b"".join(parts).decode("utf-8-sig").splitlines()
        assert len(lines) == 4 + 401      # 3 行注释 + 表头 + 401 单
        assert {line.split(",", 1)[0] for line in lines[4:]} == {
            f"T{i}" for i in range(401)
        }


class TestAnomalySummaryPayload:
    """210 §4.11：订单级异常摘要随列表 payload 下发，KPI 与摘要同口径。"""

    def test_default_rules_apply_at_order_level(self, tmp_path) -> None:
        mgr = make_manager(tmp_path, [
            # completion 0.5 → fill_pct 命中 critical（严重未完成）
            {"OrderId": "LOW", "fill": 500.0, "par_rate": 0.01},
            {"OrderId": "FULL", "fill": 1000.0, "par_rate": 0.01},
        ])
        filters = TraderFilters(start_date="20261022", end_date="20261022")
        payload = trader_service.build_order_page(filters, mgr=mgr)
        summary = payload["anomaly_summary"]

        assert summary["orders_total"] == 1
        assert summary["critical"] == 1
        assert [item["key"] for item in summary["by_rule"]] == ["fill_pct"]
        assert summary["top_orders"][0]["order_id"] == "LOW"
        assert summary["top_orders"][0]["reasons"][0]["key"] == "fill_pct"
        # KPI 与摘要同一并集口径（不再只数 overfill/cost_missing）
        assert payload["kpi"]["anomaly_orders"]["value"] == summary["orders_total"]
        assert payload["probes"]["spec_version"] == "2026.11.04"

    def test_order_level_skips_route_only_metrics(self, tmp_path) -> None:
        """区间/逐笔类规则在订单层不评估：不会因缺字段而误报或崩溃。"""
        mgr = make_manager(tmp_path, [
            {"OrderId": "P1", "par_rate_continuous": 0.9, "pnl_vwap_continuous": 5.0,
             "RPM": 3.0, "par_rate": 0.01, "fill": 1000.0},
        ])
        filters = TraderFilters(start_date="20261022", end_date="20261022")
        summary = trader_service.build_order_page(filters, mgr=mgr)["anomaly_summary"]

        keys = {item["key"] for item in summary["by_rule"]}
        assert "volume_pct_interval" not in keys
        assert "intraday_volatility" not in keys
        assert "price_movement_pct" not in keys
        assert "订单级口径" in summary["note"]


class TestReconcileWithAnalyzeOrders:
    """出口条件：聚合口径与 analyze-orders（TcaQueryService.build_order_report）对账 100 单。"""

    @staticmethod
    def _fixture_rows() -> list[dict]:
        rows: list[dict] = []
        for i in range(100):
            order_id = f"O{i:03d}"
            route_count = 1 + (i % 3)          # 1..3 条路由
            for r in range(route_count):
                rows.append({
                    "OrderId": order_id, "RouteId": f"R{r + 1}",
                    "fill": 100.0 * (r + 1) + i, "RouteShares": 500.0 + 10 * r,
                    "p_avg": 10.0 + 0.5 * r, "fill_count": 2 + r,
                    "arrival_cost_bps": -1.0 * (r + 1), "wagner_is_bps": -3.0 * (r + 1),
                    "opportunity_cost": -5.0 * (r + 1), "wagner_is": -20.0 * (r + 1),
                    "cost_cvar": 2.0 + r, "order_duration_sec": 60.0 * (r + 1),
                })
        return rows

    def test_100_orders_match_aggregate_semantics(self, tmp_path):
        from data_access.storage.connection import AccessTier
        from platform_data.contracts import TcaFilters
        from CostView.src import trader_query as tq
        from CostView.src.tca_query_service import TcaQueryService

        mgr = make_manager(tmp_path, self._fixture_rows())
        filters = TraderFilters(start_date="20261022", end_date="20261022", limit=200)
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        try:
            raw_rows = {r["OrderId"]: r for r in tq.query_order_rows(conn, filters)}
        finally:
            conn.close()
        payload_rows = {
            r["order_id"]: r for r in trader_service.build_order_page(filters, mgr=mgr)["orders"]
        }
        aggregates = {
            a.OrderId: a for a in TcaQueryService(connection_manager=mgr).build_order_report(
                TcaFilters(start_date="20261022", end_date="20261022",
                           aggregation="aggregated", limit=500),
            )
        }

        assert len(raw_rows) == 100
        assert set(raw_rows) == set(aggregates)
        for order_id, row in raw_rows.items():
            agg = aggregates[order_id]
            assert row["fill_count"] == agg.fill_count
            assert row["route_count"] == agg.route_count
            assert row["fill"] == pytest.approx(agg.fill)
            assert row["route_shares"] == pytest.approx(agg.route_shares)
            assert row["completion"] == pytest.approx(agg.par_rate)
            assert row["arrival_cost_bps"] == pytest.approx(agg.arrival_cost_bps)
            assert row["wagner_is_bps"] == pytest.approx(agg.wagner_is_bps)
            assert row["opportunity_cost"] == pytest.approx(agg.opportunity_cost)
            assert row["cost_cvar"] == pytest.approx(agg.cost_cvar)
            assert row["order_duration_sec"] == pytest.approx(agg.order_duration_sec)
            # 列表 payload 与 SQL 聚合同值（契约字段同源）
            assert payload_rows[order_id]["fill"] == pytest.approx(row["fill"])
            assert payload_rows[order_id]["arrival_cost_bps"] == pytest.approx(
                row["arrival_cost_bps"],
            )


# ── PR-2：订单详情 / 逐桶参与率 / 成本分解 / 逐笔补列 ────────────────────────


def _detail_fixture() -> dict:
    """单路由 VWAP 订单 D1：桶/参与率/成本/延迟全可算（含 unknown Liquidity 40%）。"""
    route = {
        "OrderId": "D1", "RouteId": "R1", "fill": 1000.0, "RouteShares": 1000.0,
        "fill_count": 3, "par_rate": 0.1, "p_avg": 150.0, "p_arrival": 149.0,
        "p_decision": 100.0, "p_close": 151.0, "algo": "vwap",
        "delay_cost": -100.0, "trading_cost": -200.0, "opportunity_cost": -50.0,
        "wagner_is": -350.0, "wagner_is_bps": -35.0, "arrival_cost_bps": -4.0,
    }
    fills = [
        {"OrderId": "D1", "fill_id": "F1", "exec_time": "09:31:00",
         "price": 150.0, "shares": 300.0},
        {"OrderId": "D1", "fill_id": "F2", "exec_time": "09:36:00",
         "price": 150.0, "shares": 300.0},
        {"OrderId": "D1", "fill_id": "F3", "exec_time": "09:41:00",
         "price": 150.0, "shares": 400.0},
    ]
    raw = [
        {"OrderId": "D1", "fill_id": "F1", "liquidity": "1"},
        {"OrderId": "D1", "fill_id": "F2", "liquidity": "2"},
        {"OrderId": "D1", "fill_id": "F3", "liquidity": "Z"},
    ]
    bars = [
        {"ts": "09:31:10", "volume": 3000.0},
        {"ts": "09:36:10", "volume": 3000.0},
        {"ts": "09:41:10", "volume": 4000.0},
    ]
    return {"route": route, "fills": fills, "raw": raw, "bars": bars}


def _make_detail_manager(tmp_path, fixture: dict, extra_rows=None, extra_fills=None):
    rows = [fixture["route"]] + (extra_rows or [])
    fills = [
        {"OrderId": f["OrderId"], "fill_id": f["fill_id"], "exec_time": f["exec_time"],
         "price": f["price"], "shares": f["shares"],
         "auction": f.get("auction", 0)}
        for f in fixture["fills"] + (extra_fills or [])
    ]
    raw = [
        {"OrderId": r["OrderId"], "fill_id": r["fill_id"], "liquidity": r["liquidity"]}
        for r in fixture["raw"]
    ]
    bars = [{"ts": b["ts"], "volume": b["volume"]} for b in fixture["bars"]]
    return make_manager(tmp_path, rows, fills=fills, raw_fills=raw, bars=bars)


class TestOrderDetail:
    def test_bucket_sum_participation_and_cost(self, tmp_path):
        """出口条件：桶和=总成交；单路由参与率比值 0.99–1.01；残差 <0.5bps。"""
        from CostView.src import trader_service

        mgr = _make_detail_manager(tmp_path, _detail_fixture())
        detail = trader_service.build_order_detail("D1", mgr=mgr)

        buckets = detail["timeline"]["buckets"]
        assert sum(b["fill"] for b in buckets) == 1000.0
        assert buckets[-1]["cum_completion"] == pytest.approx(1.0)
        check = detail["timeline"]["par_rate_check"]
        assert check["note"] is None
        assert 0.99 <= check["ratio"] <= 1.01
        cost = detail["cost"]
        assert cost["residual_bps"] == pytest.approx(0.0, abs=0.5)
        assert cost["residual_flag"] is None
        assert cost["denominator"] == pytest.approx(100_000.0)

    def test_liquidity_latency_and_quality(self, tmp_path):
        from CostView.src import trader_service

        mgr = _make_detail_manager(tmp_path, _detail_fixture())
        detail = trader_service.build_order_detail("D1", mgr=mgr)

        assert detail["liquidity"]["passive_share_strict"] == pytest.approx(0.3)
        assert detail["liquidity"]["unknown_share"] == pytest.approx(0.4)
        latency = detail["latency"]
        assert latency["order_to_route_sec"] == pytest.approx(300.0)
        assert latency["route_to_first_fill_sec"] == pytest.approx(300.0)
        assert latency["first_continuous_fill_sec"] == pytest.approx(60.0)
        assert latency["scheduled"] is False
        flags = {f["id"]: f["severity"] for f in detail["quality"]["flags"]}
        assert flags["liquidity_unknown"] == "warn"
        assert detail["quality"]["level"] == "warn"

    def test_single_fill_returns_na(self, tmp_path):
        """单笔成交：fill_span/speed 为 None（不是 0），速度/加速度 N/A。"""
        from CostView.src import trader_service

        fixture = _detail_fixture()
        fixture["route"].update({"OrderId": "D2", "fill_count": 1})
        fixture["fills"] = [{
            "OrderId": "D2", "fill_id": "F1", "exec_time": "09:31:00",
            "price": 150.0, "shares": 1000.0,
        }]
        fixture["raw"] = [{"OrderId": "D2", "fill_id": "F1", "liquidity": "1"}]
        fixture["bars"] = []
        mgr = _make_detail_manager(tmp_path, fixture)
        detail = trader_service.build_order_detail("D2", mgr=mgr)

        assert detail["order"]["fill_span_sec"] is None
        assert detail["order"]["speed_shares_per_min"] is None
        assert detail["fill_stats"]["cv"] is None
        assert len(detail["timeline"]["buckets"]) == 1

    def test_auction_bucket_unavailable_and_scheduled(self, tmp_path):
        """收盘竞价桶 participation_status=unavailable；收盘单 scheduled=true。"""
        from CostView.src import trader_service

        fixture = _detail_fixture()
        fixture["route"].update({
            "OrderId": "D3", "algo": "close", "fill_count": 2,
        })
        fixture["fills"] = [
            {"OrderId": "D3", "fill_id": "F1", "exec_time": "15:55:00",
             "price": 150.0, "shares": 300.0},
            {"OrderId": "D3", "fill_id": "F2", "exec_time": "16:00:00",
             "price": 150.0, "shares": 700.0, "auction": 1},
        ]
        fixture["raw"] = [
            {"OrderId": "D3", "fill_id": "F1", "liquidity": "4"},
            {"OrderId": "D3", "fill_id": "F2", "liquidity": "4"},
        ]
        fixture["bars"] = [{"ts": "15:55:10", "volume": 1000.0}]
        mgr = _make_detail_manager(tmp_path, fixture)
        detail = trader_service.build_order_detail("D3", mgr=mgr)

        buckets = detail["timeline"]["buckets"]
        assert buckets[-1]["participation_status"] == "unavailable"
        assert buckets[-1]["participation"] is None
        assert detail["latency"]["scheduled"] is True

    def test_missing_order_raises_404_semantics(self, tmp_path):
        from CostView.src import trader_service

        mgr = _make_detail_manager(tmp_path, _detail_fixture())
        with pytest.raises(trader_service.OrderNotFound):
            trader_service.build_order_detail("NOPE", mgr=mgr)

    def test_invalid_bucket_min(self, tmp_path):
        from CostView.src import trader_service

        mgr = _make_detail_manager(tmp_path, _detail_fixture())
        with pytest.raises(ValueError, match="bucket_min"):
            trader_service.build_order_detail("D1", bucket_min=7, mgr=mgr)


class TestPageFillEnrichment:
    def test_rows_get_span_speed_passive(self, tmp_path):
        """列表当前页逐笔补列（fill_span/speed/passive_ratio）+ fill_quality 探针。"""
        from CostView.src import trader_service

        fixture = _detail_fixture()
        fixture["route"].update({"OrderId": "E1"})
        for f in fixture["fills"]:
            f["OrderId"] = "E1"
        for r in fixture["raw"]:
            r["OrderId"] = "E1"
        fixture["fills"] = fixture["fills"][:2]
        fixture["raw"] = fixture["raw"][:2]
        mgr = _make_detail_manager(tmp_path, fixture)
        payload = trader_service.build_order_page_from_query(
            mgr=mgr, start_date="20261022", end_date="20261022",
        )

        row = payload["orders"][0]
        assert row["fill_span_sec"] == pytest.approx(300.0)
        assert row["speed_shares_per_min"] == pytest.approx(120.0)  # 600 / 5min
        assert row["passive_ratio"] == pytest.approx(0.5)           # 300 passive / 600
        probes = {c["id"]: c for c in payload["probes"]["checks"]}
        assert probes["fill_quality"]["checked"] is True

class TestPeerBenchmark:
    """210 §4.7：两级 peer 口径 / 样本不足 / 排除自身 / 缓存。"""

    @staticmethod
    def _peers(
        count: int, *, ticker: str = "ABCD US Equity", prefix: str = "P",
    ) -> list[dict]:
        """count 条同类订单（OrderId 前缀可区分，避免主键冲突）。"""
        return [
            {"OrderId": f"{prefix}{index}", "equ_ticker": ticker,
             "order_as_of_date": "20261022", "RouteId": f"R{index}"}
            for index in range(count)
        ]

    def _build(self, tmp_path, rows: list[dict]):
        from CostView.src import trader_service

        trader_service.clear_peer_cache()
        mgr = make_manager(tmp_path, rows)
        return trader_service, mgr

    def test_exact_group_percentile_and_self_excluded(self, tmp_path):
        rows = [{"OrderId": "ME", "fill": 900.0}] + self._peers(20)
        service, mgr = self._build(tmp_path, rows)

        payload = service.build_order_peer("ME", mgr=mgr)

        assert payload["group"]["kind"] == "exact"
        assert payload["group"]["window_days"] == 180
        assert payload["group"]["excludes_self"] is True
        assert payload["n"] == 20                     # 自身被排除
        assert payload["sample_insufficient"] is False
        completion = next(m for m in payload["metrics"] if m["key"] == "completion")
        # 全部同值 0.9 → 中位名次公式给 0.5
        assert completion["percentile"] == pytest.approx(0.5)
        # 散点包含自身点（高亮用）
        assert any(point["is_self"] for point in payload["points"])

    def test_insufficient_sample_returns_null_percentile(self, tmp_path):
        rows = [{"OrderId": "ME", "fill": 500.0}] + self._peers(3)
        service, mgr = self._build(tmp_path, rows)

        payload = service.build_order_peer("ME", mgr=mgr)

        assert payload["group"]["kind"] == "insufficient"
        assert payload["sample_insufficient"] is True
        assert payload["n"] == 3
        assert all(m["percentile"] is None and m["median"] is None
                   for m in payload["metrics"])
        assert any("样本不足" in item for item in payload["degraded"])

    def test_falls_back_to_wide_group(self, tmp_path):
        rows = ([{"OrderId": "ME", "fill": 900.0}]
                + self._peers(19, prefix="A")
                + self._peers(45, ticker="OTHER US Equity", prefix="B"))
        service, mgr = self._build(tmp_path, rows)

        payload = service.build_order_peer("ME", mgr=mgr)

        assert payload["group"]["kind"] == "wide"
        assert payload["group"]["definition"] == "exchange+side+algo"
        assert payload["n"] >= 50
        # 夹具无逐笔 → 延迟 p90 不可得，必须显式降级（不写 0）
        assert payload["latency"]["p90_sec"] is None
        assert any("latency_p90" in item for item in payload["degraded"])

    def test_second_call_hits_cache(self, tmp_path, monkeypatch):
        rows = [{"OrderId": "ME", "fill": 500.0}] + self._peers(3)
        service, mgr = self._build(tmp_path, rows)
        calls = {"n": 0}
        original = service.tq.query_peer_orders

        def _counting(*args, **kwargs):
            calls["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(service.tq, "query_peer_orders", _counting)
        first = service.build_order_peer("ME", mgr=mgr)
        after_first = calls["n"]
        second = service.build_order_peer("ME", mgr=mgr)

        assert after_first >= 1
        assert calls["n"] == after_first          # 第二次不再查库
        assert second == first

    def test_missing_order_raises(self, tmp_path):
        service, mgr = self._build(tmp_path, self._peers(3))
        with pytest.raises(service.OrderNotFound):
            service.build_order_peer("NOPE", mgr=mgr)


class TestPeerHints:
    """210 §4.8：提示随 peer payload 下发，未落地规则在 degraded 里披露。"""

    def test_hints_and_skipped_rules_in_payload(self, tmp_path):
        from CostView.src import trader_service

        trader_service.clear_peer_cache()
        # 单笔成交且未完成满（completion=0.5）→ H7 触发
        rows = [{"OrderId": "ME", "fill": 500.0, "fill_count": 1}]
        rows += [
            {"OrderId": f"P{index}", "fill": 900.0, "fill_count": 3, "RouteId": f"R{index}"}
            for index in range(20)
        ]
        mgr = make_manager(tmp_path, rows)

        payload = trader_service.build_order_peer("ME", mgr=mgr)

        # 单笔成交订单（fill_count=1）→ H7 触发
        assert any(hint["rule_id"] == "H7" for hint in payload["hints"])
        hint = next(item for item in payload["hints"] if item["rule_id"] == "H7")
        assert set(hint) == {"rule_id", "title", "evidence", "peer_n", "confidence", "action"}
        # 未落地的 H2/H5/H6 必须逐条披露原因
        for rule_id in ("H2", "H5", "H6"):
            assert any(item.startswith(f"{rule_id}:") for item in payload["degraded"])


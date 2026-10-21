"""EMSX 导出解析与 PM 意图映射单测（057 DL-01）。

金标准：tests/fixtures/emsx_export_golden.csv（057 plan.md 附录 A 脱敏样例改写版，
PM Note 13 填虚构连接键、覆盖五种写法）；遮蔽版 fixtures/emsx_export_masked.csv
验证遮蔽值与受限值按缺失处理。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from export_parser import (
    ExportParseError,
    ScannedExport,
    build_pre_trade_board,
    load_pre_trade_board,
    parse_export_csv,
    parse_pm_note,
    scan_latest_export,
)
from platform_data.contracts.order_intent_contracts import (
    INTENT_MAPPING_VERSION,
    INTENT_SOURCE_EMSX_EXPORT,
    PreTradeOrderBoard,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN_PATH = FIXTURES / "emsx_export_golden.csv"
MASKED_PATH = FIXTURES / "emsx_export_masked.csv"
EXPORT_TS = "2026-10-21T02:30:00+00:00"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _scanned(file_name: str) -> ScannedExport:
    return ScannedExport(file_name=file_name, exported_at=EXPORT_TS, size_bytes=1)


class TestParsePmNote:
    """PM Note 13 → 意图映射：五种写法 + 边界。"""

    def test_empty_prefix_maps_to_vwap(self):
        intent = parse_pm_note("^7000001^0", export_ts=EXPORT_TS)

        assert intent.benchmark == "VWAP"
        assert intent.order_key == "^7000001^0"
        assert intent.close_pct is None
        assert intent.unmatched_reason is None
        assert intent.intent_source == INTENT_SOURCE_EMSX_EXPORT
        assert intent.valid_from == EXPORT_TS

    def test_full_close_maps_to_close(self):
        intent = parse_pm_note("100 % @Close^7000002^0", export_ts=EXPORT_TS)

        assert intent.benchmark == "CLOSE"
        assert intent.close_pct == 100.0
        assert intent.order_key == "^7000002^0"

    def test_partial_close_maps_to_mix(self):
        intent = parse_pm_note("80 % @Close^7000003^0", export_ts=EXPORT_TS)

        assert intent.benchmark == "MIX"
        assert intent.close_pct == 80.0

    def test_decimal_close_ratio_maps_to_mix(self):
        intent = parse_pm_note("62.5 % @Close^7000003^0", export_ts=EXPORT_TS)

        assert intent.benchmark == "MIX"
        assert intent.close_pct == 62.5

    def test_spec_instr_maps_to_special(self):
        intent = parse_pm_note("Spec.Instr.^7000004^0", export_ts=EXPORT_TS)

        assert intent.benchmark == "SPECIAL"
        assert intent.close_pct is None
        assert intent.order_key == "^7000004^0"

    def test_unknown_prefix_maps_to_unmapped(self):
        intent = parse_pm_note("FOO^7000005^0", export_ts=EXPORT_TS)

        assert intent.benchmark == "UNMAPPED"
        assert intent.unmatched_reason == "unknown_prefix"

    def test_empty_note_maps_to_unmapped(self):
        intent = parse_pm_note("   ", export_ts=EXPORT_TS)

        assert intent.benchmark == "UNMAPPED"
        assert intent.unmatched_reason == "empty_pm_note"
        assert intent.order_key == ""

    def test_none_note_maps_to_unmapped(self):
        intent = parse_pm_note(None, export_ts=EXPORT_TS)

        assert intent.benchmark == "UNMAPPED"
        assert intent.unmatched_reason == "empty_pm_note"

    def test_missing_order_key_keeps_benchmark_with_reason(self):
        intent = parse_pm_note("80 % @Close", export_ts=EXPORT_TS)

        assert intent.benchmark == "MIX"
        assert intent.close_pct == 80.0
        assert intent.order_key == ""
        assert intent.unmatched_reason == "missing_order_key"

    def test_raw_note_is_preserved_and_valid_from_overrides(self):
        intent = parse_pm_note("^7000001^0", export_ts=EXPORT_TS, valid_from="2026-10-20T09:00:00+00:00")

        assert intent.raw_note == "^7000001^0"
        assert intent.valid_from == "2026-10-20T09:00:00+00:00"
        assert intent.export_ts == EXPORT_TS


class TestParseExportCsv:
    """CSV 按列名解析：金标准、遮蔽、异常。"""

    def test_golden_fixture_parses_all_rows(self):
        parsed = parse_export_csv(_read(GOLDEN_PATH), file_name="golden.csv")

        assert parsed.file_name == "golden.csv"
        assert len(parsed.rows) == 5
        assert "PM Note 13" in parsed.header
        # 重名列按出现顺序加后缀（附录 A 样例的 Day Part Rate % 出现两次）
        assert parsed.header.count("Day Part Rate % (2)") == 1

    def test_restricted_and_masked_values_are_dropped(self):
        parsed = parse_export_csv(_read(GOLDEN_PATH), file_name="golden.csv")

        first = parsed.rows[0]
        assert first["Vs IntervalVWAP (Bps)"] is None  # Data Export Restricted
        assert first["Vs ArrPx (Bps)"] is None  # 空串
        assert first["PM Note 13"] == "^7000001^0"

    def test_masked_fixture_drops_pm_note_and_numbers(self):
        parsed = parse_export_csv(_read(MASKED_PATH), file_name="masked.csv")

        assert len(parsed.rows) == 2
        assert all(row["PM Note 13"] is None for row in parsed.rows)
        assert all(row["Qty"] is None for row in parsed.rows)

    def test_missing_required_column_raises_with_column_name(self):
        header = "Code,Exch Code,Side,Qty,Status,Create Time (As of)\nSEC_A,EX_A,Sell,100,Working,10:29:01\n"

        with pytest.raises(ExportParseError, match="PM Note 13"):
            parse_export_csv(header, file_name="bad.csv")

    def test_field_count_mismatch_raises_with_line_number(self):
        text = "PM Note 13,Code,Exch Code,Side,Qty,Status,Create Time (As of)\n^1^0,SEC_A,EX_A,Sell,100,Working\n"

        with pytest.raises(ExportParseError, match="第 2 行字段数"):
            parse_export_csv(text, file_name="bad.csv")

    def test_column_reorder_still_parses(self):
        text = "Status,PM Note 13,Code,Exch Code,Side,Qty,Create Time (As of)\nWorking,^7000001^0,SEC_A,EX_A,Sell,100,10:29:01\n"

        parsed = parse_export_csv(text, file_name="reordered.csv")

        assert parsed.rows[0]["PM Note 13"] == "^7000001^0"
        assert parsed.rows[0]["Code"] == "SEC_A"

    def test_empty_file_raises(self):
        with pytest.raises(ExportParseError, match="为空"):
            parse_export_csv("", file_name="empty.csv")

    def test_thousands_separator_is_tolerated(self):
        text = "PM Note 13,Code,Exch Code,Side,Qty,Status,Create Time (As of)\n^1^0,SEC_A,EX_A,Sell,\"1,234,567\",Working,10:29:01\n"

        parsed = parse_export_csv(text, file_name="thousands.csv")

        assert parsed.rows[0]["Qty"] == "1,234,567"


class TestScanLatestExport:
    """收件箱扫描：按 mtime 取最新一份。"""

    def test_returns_latest_by_mtime(self, tmp_path):
        older = tmp_path / "emsx_orders_20261020.csv"
        newer = tmp_path / "emsx_orders_20261021.csv"
        older.write_text("h", encoding="utf-8")
        newer.write_text("h", encoding="utf-8")
        os.utime(older, (1_000_000, 1_000_000))
        os.utime(newer, (2_000_000, 2_000_000))

        scanned = scan_latest_export(str(tmp_path))

        assert scanned is not None
        assert scanned.file_name == "emsx_orders_20261021.csv"
        assert scanned.size_bytes == 1

    def test_missing_dir_returns_none(self, tmp_path):
        assert scan_latest_export(str(tmp_path / "nope")) is None

    def test_empty_dir_returns_none(self, tmp_path):
        assert scan_latest_export(str(tmp_path)) is None

    def test_ignores_non_csv_files(self, tmp_path):
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

        assert scan_latest_export(str(tmp_path)) is None


class TestBuildPreTradeBoard:
    """盘前单组装：意图、覆盖率、未匹配清单。"""

    def _board(self) -> PreTradeOrderBoard:
        parsed = parse_export_csv(_read(GOLDEN_PATH), file_name="golden.csv")
        return build_pre_trade_board(parsed, _scanned("golden.csv"))

    def test_board_covers_five_orders_with_expected_benchmarks(self):
        board = self._board()

        assert board.order_count == 5
        assert [row.intent.benchmark for row in board.orders] == [
            "VWAP",
            "CLOSE",
            "MIX",
            "SPECIAL",
            "UNMAPPED",
        ]
        assert board.orders[0].code == "SEC_A"
        assert board.orders[0].qty == 100000.0
        assert board.orders[0].intent.order_key == "^7000001^0"

    def test_coverage_and_unmatched_list(self):
        board = self._board()

        assert board.intent_coverage_pct == 80.0
        assert len(board.unmatched) == 1
        assert board.unmatched[0].code == "SEC_E"
        assert board.unmatched[0].reason == "unknown_prefix"
        assert board.intent_mapping_version == INTENT_MAPPING_VERSION
        assert board.export_file_name == "golden.csv"

    def test_masked_board_has_zero_coverage(self):
        parsed = parse_export_csv(_read(MASKED_PATH), file_name="masked.csv")

        board = build_pre_trade_board(parsed, _scanned("masked.csv"))

        assert board.order_count == 2
        assert board.intent_coverage_pct == 0.0
        assert {entry.reason for entry in board.unmatched} == {"empty_pm_note"}

    def test_non_key_columns_land_in_extra_fields(self):
        board = self._board()

        first = board.orders[0]
        assert first.extra_fields.get("Mkt Stat") == "ACTV"
        assert first.extra_fields.get("GICS Ind Grp Name") == "Banks"
        assert first.extra_fields.get("Day Part Rate %") == "0"
        assert first.extra_fields.get("Day Part Rate % (2)") == "0"
        assert "PM Note 13" not in first.extra_fields


class TestLoadPreTradeBoard:
    """收件箱 → 盘前单一体入口。"""

    def test_loads_board_from_inbox(self, tmp_path):
        (tmp_path / "emsx_orders.csv").write_text(_read(GOLDEN_PATH), encoding="utf-8")

        board = load_pre_trade_board(str(tmp_path))

        assert board is not None
        assert board.order_count == 5
        assert board.intent_coverage_pct == 80.0

    def test_empty_inbox_returns_none(self, tmp_path):
        assert load_pre_trade_board(str(tmp_path)) is None

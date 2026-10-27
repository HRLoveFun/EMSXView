"""057 DL-07 读侧 — 盘中库只读适配器测试。

锁死行为：
1. 缺文件/缺表/清单损坏一律降级为空（不静默当最新）；
2. 返回列与契约 TABLE_COLUMNS 一致；
3. freshness 按 manifest as_of 计算滞后，as_of 不可解析记 -1.0；
4. data_dir 覆盖与默认路径规则；未知表名显式报错。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_access import IntradayStoreReader  # noqa: E402
from platform_data.contracts import TABLE_COLUMNS  # noqa: E402

TRADE_DATE = "20261027"


def _make_db(root: Path, tables: tuple[str, ...] = ("order_intent", "snapshot_t0")) -> Path:
    db_dir = root / "intraday"
    db_dir.mkdir(parents=True, exist_ok=True)
    path = db_dir / f"intraday_{TRADE_DATE}.db"
    conn = sqlite3.connect(path)
    try:
        for table in tables:
            cols = ", ".join(f"{name} TEXT" for name in TABLE_COLUMNS[table])
            conn.execute(f"CREATE TABLE {table} ({cols})")
        if "order_intent" in tables:
            conn.execute(
                "INSERT INTO order_intent (order_key, benchmark, close_pct, raw_note, "
                "intent_source, valid_from, export_ts, unmatched_reason, mapping_version) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                ("ABC US 1", "CLOSE", "1.0", "100 % @Close^ABC US 1^0", "export", "2026-10-27T01:00:00+00:00",
                 "2026-10-27T01:00:00+00:00", None, "v1"),
            )
            conn.execute(
                "INSERT INTO order_intent (order_key, benchmark, close_pct, raw_note, "
                "intent_source, valid_from, export_ts, unmatched_reason, mapping_version) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                ("DEF US 2", "VWAP", None, "^DEF US 2^0", "export", "2026-10-27T01:05:00+00:00",
                 "2026-10-27T01:05:00+00:00", None, "v1"),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _write_manifest(root: Path, datasets: list[dict]) -> None:
    db_dir = root / "intraday"
    db_dir.mkdir(parents=True, exist_ok=True)
    (db_dir / "intraday_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": "intraday-manifest-v1",
                "generated_at": "2026-10-27T02:00:00+00:00",
                "trade_date": TRADE_DATE,
                "datasets": datasets,
            }
        ),
        encoding="utf-8",
    )


class TestMissingDb:
    def test_missing_file_degrades_to_empty(self, tmp_path):
        reader = IntradayStoreReader(TRADE_DATE, data_dir=tmp_path)
        assert reader.available() is False
        assert reader.read_order_intents() == []
        assert reader.read_snapshot_t0() == []
        assert reader.load_manifest() is None
        assert reader.freshness() == []

    def test_missing_table_degrades_to_empty(self, tmp_path):
        _make_db(tmp_path, tables=("order_intent",))
        reader = IntradayStoreReader(TRADE_DATE, data_dir=tmp_path)
        assert reader.available() is True
        assert reader.read_order_intents()
        assert reader.read_snapshot_t0() == []

    def test_corrupt_manifest_returns_none(self, tmp_path):
        _make_db(tmp_path)
        db_dir = tmp_path / "intraday"
        (db_dir / "intraday_manifest.json").write_text("{not json", encoding="utf-8")
        reader = IntradayStoreReader(TRADE_DATE, data_dir=tmp_path)
        assert reader.load_manifest() is None
        assert reader.freshness() == []


class TestReadDatasets:
    def test_order_intent_columns_match_contract(self, tmp_path):
        _make_db(tmp_path)
        rows = IntradayStoreReader(TRADE_DATE, data_dir=tmp_path).read_order_intents()
        assert len(rows) == 2
        assert set(rows[0]) == set(TABLE_COLUMNS["order_intent"])
        assert {r["benchmark"] for r in rows} == {"CLOSE", "VWAP"}

    def test_unknown_table_rejected(self):
        reader = IntradayStoreReader(TRADE_DATE)
        try:
            reader._rows("intraday_bogus")
        except ValueError as exc:
            assert "intraday_bogus" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("unknown table must raise")


class TestFreshness:
    def test_lag_minutes_from_manifest(self, tmp_path):
        _make_db(tmp_path)
        as_of = "2026-10-27T01:00:00+00:00"
        _write_manifest(
            tmp_path,
            [
                {"dataset": "order_intent", "as_of": as_of, "watermark": "", "row_count": 2,
                 "status": "ok", "last_error": None},
            ],
        )
        reader = IntradayStoreReader(TRADE_DATE, data_dir=tmp_path)
        now = datetime(2026, 10, 27, 1, 30, tzinfo=timezone.utc)
        [entry] = reader.freshness(now=now)
        assert entry.dataset == "order_intent"
        assert entry.lag_minutes == 30.0

    def test_unparseable_as_of_is_minus_one(self, tmp_path):
        _make_db(tmp_path)
        _write_manifest(
            tmp_path,
            [{"dataset": "snapshot_t0", "as_of": "", "watermark": "", "row_count": 0,
              "status": "stale", "last_error": "no bars"}],
        )
        [entry] = IntradayStoreReader(TRADE_DATE, data_dir=tmp_path).freshness(
            now=datetime(2026, 10, 27, tzinfo=timezone.utc)
        )
        assert entry.lag_minutes == -1.0

    def test_manifest_naive_timestamp_treated_as_utc(self, tmp_path):
        _make_db(tmp_path)
        _write_manifest(
            tmp_path,
            [{"dataset": "order_intent", "as_of": "2026-10-27T01:00:00", "watermark": "",
              "row_count": 0, "status": "ok", "last_error": None}],
        )
        now = datetime(2026, 10, 27, 1, 15, tzinfo=timezone.utc)
        [entry] = IntradayStoreReader(TRADE_DATE, data_dir=tmp_path).freshness(now=now)
        assert entry.lag_minutes == 15.0

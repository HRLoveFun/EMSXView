"""H1/H5 回归测试: 归档删除边界防护 (2026-08-14)。

背景:
    - H1: raw_fills.order_as_of_date 存 "YYYY-MM-DD HH:MM:SS" 全时间串,
      旧实现直接与 YYYYMMDD cutoff 字符串比较, '-' < '0' 导致同一年
      数据全部被误判为过期 (整年误删)。
    - H5: retention_months 无校验, `or 24` 吞掉 0, 负数令 cutoff 计算
      失效 (range 为空 → cutoff=当月1日 → 全量误删)。

校验:
    1. iso-datetime 格式列仅判定真正过期行
    2. compact (YYYYMMDD) 格式列行为不变
    3. retention < 1 抛 ValueError (参数错误尽早暴露)
    4. 端到端归档仅迁移过期行, 并生成清单快照
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from DataPipeline.storage.archiver import DataArchiver

_CUTOFF = datetime(2025, 8, 1)  # 模拟 cutoff 2025-08-01


def test_iso_datetime_format_only_expired_rows():
    """raw_fills 场景: 全时间串日期列不误判未过期行为过期。"""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE raw_fills (order_id TEXT PRIMARY KEY, "
        "order_as_of_date TEXT, source_date TEXT)"
    )
    conn.executemany(
        "INSERT INTO raw_fills VALUES (?, ?, ?)",
        [
            ("o1", "2025-07-01 09:30:00", "20250701"),  # 过期
            ("o2", "2025-08-15 09:30:00", "20250815"),  # 未过期 (旧逻辑误判)
            ("o3", "2025-09-01 09:30:00", "20250901"),  # 未过期 (旧逻辑误判)
        ],
    )
    conn.commit()

    assert DataArchiver._detect_date_format(conn, "raw_fills", "order_as_of_date") == "iso-datetime"

    predicate, params = DataArchiver._build_date_predicate(
        conn, "raw_fills", "order_as_of_date", _CUTOFF
    )
    expired = conn.execute(
        f"SELECT order_id FROM raw_fills WHERE {predicate}", params
    ).fetchall()
    conn.close()

    assert {r[0] for r in expired} == {"o1"}


def test_compact_format_behavior_unchanged():
    """processed_fills 场景: YYYYMMDD 格式列比较行为不变。"""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE processed_fills (fill_id TEXT PRIMARY KEY, "
        "order_as_of_date TEXT)"
    )
    conn.executemany(
        "INSERT INTO processed_fills VALUES (?, ?)",
        [("f1", "20250701"), ("f2", "20250815"), ("f3", "20250901")],
    )
    conn.commit()

    assert DataArchiver._detect_date_format(conn, "processed_fills", "order_as_of_date") == "compact"

    predicate, params = DataArchiver._build_date_predicate(
        conn, "processed_fills", "order_as_of_date", _CUTOFF
    )
    expired = conn.execute(
        f"SELECT fill_id FROM processed_fills WHERE {predicate}", params
    ).fetchall()
    conn.close()

    assert {r[0] for r in expired} == {"f1"}


@pytest.mark.parametrize("bad_retention", [0, -3, -100])
def test_retention_below_one_raises(bad_retention):
    """retention < 1 必须抛 ValueError (在 DB 存在性检查之前)。"""
    with tempfile.TemporaryDirectory() as tmp:
        archiver = DataArchiver(Path(tmp))
        with pytest.raises(ValueError):
            archiver.archive_expired("processed_fills", retention_months=bad_retention)


def test_end_to_end_archive_writes_manifest():
    """端到端: 归档仅迁移过期行, 且生成清单快照。"""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        db_path = data_dir / "raw_fills.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE raw_fills (order_id TEXT PRIMARY KEY, "
            "order_as_of_date TEXT, source_date TEXT)"
        )
        conn.executemany(
            "INSERT INTO raw_fills VALUES (?, ?, ?)",
            [
                ("o1", "2024-01-05 10:00:00", "20240105"),  # 过期 (12个月保留)
                ("o2", "2025-08-15 10:00:00", "20250815"),  # 未过期
            ],
        )
        conn.commit()
        conn.close()

        archiver = DataArchiver(data_dir)
        results = archiver.archive_expired("raw_fills", dry_run=False)

        assert results.get("raw_fills") == 1

        check = sqlite3.connect(str(db_path))
        remaining = check.execute("SELECT order_id FROM raw_fills").fetchall()
        check.close()
        assert {r[0] for r in remaining} == {"o2"}

        manifests = list((data_dir / "archive").glob("archive_manifest_*.json"))
        assert manifests, "未生成归档清单快照"

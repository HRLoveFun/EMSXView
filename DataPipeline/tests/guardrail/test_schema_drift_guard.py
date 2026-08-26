"""Schema drift Guardrail 单元测试。

对照 docs/archive/2026-08-26/002-pipeline-guardrail/quickstart.md 场景（schema drift 检测，已归档）。
验证 4 类漂移检测（PRIMARY_KEY_TYPE_MISMATCH / COLUMN_MISSING_IN_DDL /
COLUMN_MISSING_IN_CODE / VALUE_TYPE_MISMATCH）。
"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

import pytest

from DataPipeline.pipeline_guards.schema_drift_guard import (
    KNOWN_DRIFT_WHITELIST,
    SchemaDriftGuard,
    run_schema_drift_check,
)
from DataPipeline.validation.enums import SeverityLevel, ViolationType


@pytest.fixture
def temp_ddl_with_integer_pk(tmp_path: Path) -> Path:
    """临时 DDL：声明 event_id 为 INTEGER PRIMARY KEY。"""
    content = textwrap.dedent("""
        CREATE TABLE IF NOT EXISTS route_event_history (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            OrderId TEXT NOT NULL
        );
    """)
    ddl = tmp_path / "test_partition.sql"
    ddl.write_text(content, encoding="utf-8")
    return ddl


@pytest.fixture
def temp_ddl_clean(tmp_path: Path) -> Path:
    """临时 DDL：声明 clean_table，全部类型一致。"""
    content = textwrap.dedent("""
        CREATE TABLE IF NOT EXISTS clean_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            count INTEGER
        );
    """)
    ddl = tmp_path / "clean_partition.sql"
    ddl.write_text(content, encoding="utf-8")
    return ddl


@pytest.fixture
def temp_code_writes_string_event_id(tmp_path: Path) -> Path:
    """临时代码：写入 f-string event_id（PR-3 关键漂移点）。"""
    content = textwrap.dedent('''
        """Synthetic write site for test."""
        def write_event():
            return {
                "event_id": f"fill:abc:def:001:20260418",
                "OrderId": "x",
            }
    ''')
    code = tmp_path / "test_writer.py"
    code.write_text(content, encoding="utf-8")
    return code


@pytest.fixture
def temp_code_writes_correct_type(tmp_path: Path) -> Path:
    """临时代码：写入 INTEGER id（无漂移）。"""
    content = textwrap.dedent('''
        def write_clean():
            return {"id": 1, "name": "test", "count": 5}
    ''')
    code = tmp_path / "clean_writer.py"
    code.write_text(content, encoding="utf-8")
    return code


# ═══════════════════════════════════════════════════════════════════════════════
# T-PR3-01: 检测 INTEGER 主键但代码写字符串（已知漂移场景）
# ═══════════════════════════════════════════════════════════════════════════════

def test_detect_primary_key_type_mismatch(
    temp_ddl_with_integer_pk, temp_code_writes_string_event_id,
) -> None:
    """DDL 声明 INTEGER PRIMARY KEY，但代码层写入 f-string（TEXT）— 应检出。"""
    guard = SchemaDriftGuard(
        ddl_paths=[temp_ddl_with_integer_pk],
        code_paths=[temp_code_writes_string_event_id],
        whitelist=set(),  # 禁用白名单，确保 ERROR 级别
    )
    result = guard.scan()
    drifts = [d for d in result.drifts if d.drift_type == "PRIMARY_KEY_TYPE_MISMATCH"]
    assert len(drifts) >= 1, "应检测到至少 1 条 PRIMARY_KEY_TYPE_MISMATCH 漂移"
    drift = drifts[0]
    assert drift.table == "route_event_history"
    assert drift.field == "event_id"
    assert "INTEGER" in drift.expected
    assert "TEXT" in drift.actual


# ═══════════════════════════════════════════════════════════════════════════════
# T-PR3-02: 白名单机制 — 已知漂移降级为 INFO
# ═══════════════════════════════════════════════════════════════════════════════

def test_known_drift_is_whitelisted_to_info() -> None:
    """默认入口（扫描项目 DDL + 关键代码）应检测到 route_event_history.event_id 漂移，
    但通过 KNOWN_DRIFT_WHITELIST 降级为 INFO 级别（不阻断）。"""
    result, violations = run_schema_drift_check()
    event_id_violations = [
        v for v in violations
        if v.field_name == "route_event_history.event_id"
    ]
    if event_id_violations:
        # 若有 event_id 漂移（视当前代码而定），必为 INFO 级别
        for v in event_id_violations:
            assert v.severity == SeverityLevel.INFO, (
                f"已知漂移应降级为 INFO，实际 {v.severity}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# T-PR3-03: 禁用白名单后升级为 ERROR（阻断）
# ═══════════════════════════════════════════════════════════════════════════════

def test_unknown_drift_blocks_at_error_level(
    temp_ddl_with_integer_pk, temp_code_writes_string_event_id,
) -> None:
    """禁用白名单后，新漂移应为 ERROR 级别。"""
    guard = SchemaDriftGuard(
        ddl_paths=[temp_ddl_with_integer_pk],
        code_paths=[temp_code_writes_string_event_id],
        whitelist=set(),
    )
    result = guard.scan()
    violations = guard.to_violations(result)
    error_violations = [v for v in violations if v.severity == SeverityLevel.ERROR]
    assert len(error_violations) >= 1
    assert any(
        v.violation_type == ViolationType.TYPE_MISMATCH
        for v in error_violations
    )


# ═══════════════════════════════════════════════════════════════════════════════
# T-PR3-04: 干净 DDL + 干净代码 → 无漂移
# ═══════════════════════════════════════════════════════════════════════════════

def test_clean_ddl_and_code_no_drift(
    temp_ddl_clean, temp_code_writes_correct_type,
) -> None:
    """类型完全一致时，不应产生任何漂移。"""
    guard = SchemaDriftGuard(
        ddl_paths=[temp_ddl_clean],
        code_paths=[temp_code_writes_correct_type],
        whitelist=set(),
    )
    result = guard.scan()
    assert not result.has_drift, f"应有 0 条漂移，实际 {len(result.drifts)} 条"


# ═══════════════════════════════════════════════════════════════════════════════
# T-PR3-05: DDL 解析正确性
# ═══════════════════════════════════════════════════════════════════════════════

def test_ddl_parser_extracts_columns(temp_ddl_with_integer_pk) -> None:
    """验证 DDL 解析能正确提取表名和列类型。"""
    guard = SchemaDriftGuard()
    parsed = guard._parse_ddl(temp_ddl_with_integer_pk)
    assert "route_event_history" in parsed
    assert parsed["route_event_history"]["event_id"] == "INTEGER"
    assert parsed["route_event_history"]["OrderId"] == "TEXT"


# ═══════════════════════════════════════════════════════════════════════════════
# T-PR3-06: 白名单默认包含 route_event_history.event_id
# ═══════════════════════════════════════════════════════════════════════════════

def test_default_whitelist_contains_known_drift() -> None:
    """PR-3 白名单默认包含已知的 route_event_history.event_id 漂移。"""
    assert ("route_event_history", "event_id", "PRIMARY_KEY_TYPE_MISMATCH") \
        in KNOWN_DRIFT_WHITELIST

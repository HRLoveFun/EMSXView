"""monitoring 子包内部共享的小工具（去重后的唯一实现）。

背景：``_to_float`` / ``_to_int`` / ``_has_column`` / `_table_exists` 曾在
``anomaly_query`` / ``report_aggregator`` / ``metric_coverage`` / ``bdib_health``
各写一遍，实现细节存在分叉（如 ``_to_float`` 一处对非法值抛异常、另一处返回
None；``_has_column`` 一处区分大小写、另一处不区分），属典型的「同一契约多处
实现」。2026-09-15 收敛到本模块，各调用方的同名方法仅作薄转发。

与 ``report_measure.py`` 的分工：本模块放**无业务语义**的类型/schema 小工具，
凡涉及报告口径的 SQL 表达式与聚合规则一律放 ``report_measure``。
"""
from __future__ import annotations

from typing import Any, Optional

from data_access.config import Config

__all__ = [
    "to_float", "to_int", "columns", "has_column", "table_exists",
    "tca_summary_columns", "tca_summary_exists",
]


def to_float(value: Any) -> Optional[float]:
    """数值安全转换：None / NaN / 不可解析 → None（不抛异常）。"""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def to_int(value: Any) -> Optional[int]:
    """整数安全转换（fill_count 等）：None / 不可解析 → None（不抛异常）。"""
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def columns(conn: Any, table: str) -> set[str]:
    """返回表现有列名集合（小写；PRAGMA 失败 → 空集，供降级路径使用）。"""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except Exception:
        return set()
    return {str(row[1]).lower() for row in rows}


def has_column(conn: Any, table: str, column: str) -> bool:
    """判断表是否含指定列（向后兼容旧 schema 缺列场景）。

    大小写不敏感；PRAGMA 失败（库不可用 / 表不存在）视为无该列而非抛出，
    以便降级路径继续执行。
    """
    return column.lower() in columns(conn, table)


def table_exists(conn: Any, table_name: str) -> bool:
    """指定表/视图是否存在于当前库（SQLite / 视图均计入）。"""
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') "
            "AND name = ? LIMIT 1",
            [table_name],
        ).fetchone()
    except Exception:
        return False
    return row is not None


def tca_summary_exists(conn: Any) -> bool:
    """``tca_route_summary`` 表/视图是否存在（monitoring 各查询的公共前置检查）。"""
    return table_exists(conn, Config.TCA_ROUTE_SUMMARY_TABLE)


def tca_summary_columns(conn: Any) -> set[str]:
    """``tca_route_summary`` 现有列名集合（小写；PRAGMA 失败 → 空集）。"""
    return columns(conn, Config.TCA_ROUTE_SUMMARY_TABLE)

"""Phase B 单元测试: upsert_raw_api_data 对字符串 'NA' 的正确识别.

校验预防补丁 (与 Exchange NaN->NA 修复同模式):
    1. Ticker 原值为 'NA' (National Bank of Canada) 时, DB 应写入 'NA' 而非 NULL
    2. Ticker 原值为 'NA' 时, 不限于 NATL BK CANADA, 任何 security 的 'NA' ticker
       都应被恢复 (通用性, 与 Exchange 修复一致)
    3. BBG 真返回 None 时, DB 保持 NULL (不误伤)
    4. Ticker 值非 'NA' 时 (如 'ASML') 应正常写入, 无副作用

并行验证: Exchange 原有 'NA' 识别仍生效 (不回归).
"""

from __future__ import annotations

import sqlite3
from typing import Optional

import pytest

from DataPipeline.config import Config
from DataPipeline.storage.schema.inline_ddl import init_raw_fills_schema
from DataPipeline.storage.repositories.raw_fills import SqliteRawFillWriteRepository


# ── 测试辅助: 可注入 :memory: DB 的 Repository 子类 ───────────────────────


class _ConnWrapper:
    """让 close() 变 no-op, 避免一次调用就关闭共享 :memory: conn."""

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    @property
    def raw_connection(self):
        return self._c

    def execute(self, sql, params=()): return self._c.execute(sql, params)
    def executemany(self, sql, params): return self._c.executemany(sql, params)
    def commit(self): self._c.commit()
    def close(self): pass  # 测试中不关闭共享连接


class _InMemoryRawFillRepo(SqliteRawFillWriteRepository):
    """绕过 ConnectionManager, 直接使用 :memory: sqlite connection."""

    def __init__(self, conn: sqlite3.Connection):
        # 不调 super().__init__ 以避免创建 ConnectionManager
        self._conn = conn

    def _get_write_conn(self):
        return _ConnWrapper(self._conn)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def raw_fills_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    init_raw_fills_schema(conn)
    yield conn
    conn.close()


def _make_fill(order_id: str, ticker: Optional[str], **extras) -> dict:
    """构造一个最小可写入 raw_fills 的 fill dict."""
    fill = {
        "OrderId": order_id, "RouteId": "1", "FillId": "1",
        "Ticker": ticker,
        "Currency": extras.get("Currency", "CAD"),
        "Exchange": extras.get("Exchange", "CN"),
        "SecurityName": extras.get("SecurityName", "NATL BK CANADA"),
        "Side": "B", "Amount": "100", "Type": "MKT",
        "Broker": "EQ-TEST", "StrategyType": "TARGETCL",
        "TraderName": "TEST", "RouteShares": "100",
        "FillPrice": "100.0", "FillShares": "100", "ExecType": "FILL",
        "DateTimeOfFill": "2026-01-01T10:00:00-05:00",
        "NyOrderCreateAsOfDateTime": "2026-01-01T09:00:00-05:00",
        "NyTranCreateAsOfDateTime": "2026-01-01T09:30:00-05:00",
    }
    return fill


# ═══════════════════════════════════════════════════════════════════════
# Part 1: Ticker 字符串 'NA' 识别 (预防补丁核心校验)
# ═══════════════════════════════════════════════════════════════════════


def test_ticker_na_string_preserved(raw_fills_db):
    """Ticker 原值为字符串 'NA' 时, DB 应写入 'NA' 而非 NULL."""
    fills = [_make_fill("T1", "NA")]
    repo = _InMemoryRawFillRepo(raw_fills_db)
    repo.upsert_raw_api_data(fills, source_date="20260101")
    row = raw_fills_db.execute(
        "SELECT Ticker FROM raw_fills WHERE OrderId='T1'"
    ).fetchone()
    assert row is not None
    assert row[0] == "NA", f"Ticker 应为 'NA', 实际: {row[0]!r}"


def test_ticker_na_preserved_across_securities(raw_fills_db):
    """任何 security 的 Ticker='NA' 都应恢复, 不限于 NATL BK CANADA (通用性)."""
    fills = [_make_fill("T2", "NA", SecurityName="UNKNOWN SEC", Currency="USD", Exchange="US")]
    repo = _InMemoryRawFillRepo(raw_fills_db)
    repo.upsert_raw_api_data(fills, source_date="20260101")
    row = raw_fills_db.execute(
        "SELECT Ticker FROM raw_fills WHERE OrderId='T2'"
    ).fetchone()
    assert row is not None
    assert row[0] == "NA", f"Ticker 应为 'NA' (任何 security), 实际: {row[0]!r}"


def test_ticker_real_null_stays_null(raw_fills_db):
    """若 BBG 真返回 Ticker=None (非字符串 'NA'), DB 应保持 NULL."""
    fills = [_make_fill("T3", None)]
    repo = _InMemoryRawFillRepo(raw_fills_db)
    repo.upsert_raw_api_data(fills, source_date="20260101")
    row = raw_fills_db.execute(
        "SELECT Ticker FROM raw_fills WHERE OrderId='T3'"
    ).fetchone()
    assert row is not None
    assert row[0] is None, f"Ticker 真返回 None 时应保持 NULL, 实际: {row[0]!r}"


def test_ticker_other_string_no_side_effect(raw_fills_db):
    """Ticker 值非 'NA' 时 (如 'ASML') 应正常写入, 无副作用."""
    fills = [_make_fill("T4", "ASML", Currency="EUR", Exchange="NA", SecurityName="ASML HOLDING NV")]
    repo = _InMemoryRawFillRepo(raw_fills_db)
    repo.upsert_raw_api_data(fills, source_date="20260101")
    row = raw_fills_db.execute(
        "SELECT Ticker FROM raw_fills WHERE OrderId='T4'"
    ).fetchone()
    assert row is not None
    assert row[0] == "ASML", f"Ticker='ASML' 应原样写入, 实际: {row[0]!r}"


# ═══════════════════════════════════════════════════════════════════════
# Part 2: Exchange 原有 'NA' 修复无回归 (并行校验)
# ═══════════════════════════════════════════════════════════════════════


def test_exchange_na_string_still_preserved(raw_fills_db):
    """Exchange 原值为 'NA' (荷兰 Amsterdam) 时仍应正确恢复 (无回归)."""
    fills = [_make_fill("T5", "ASML", Currency="EUR", Exchange="NA", SecurityName="ASML HOLDING NV")]
    repo = _InMemoryRawFillRepo(raw_fills_db)
    repo.upsert_raw_api_data(fills, source_date="20260101")
    row = raw_fills_db.execute(
        "SELECT Exchange FROM raw_fills WHERE OrderId='T5'"
    ).fetchone()
    assert row is not None
    assert row[0] == "NA", f"Exchange 应为 'NA' (荷兰), 实际: {row[0]!r}"


def test_ticker_and_exchange_na_both_preserved(raw_fills_db):
    """Ticker='NA' 与 Exchange='NA' 同时出现的边界场景 (同 fill 不互扰)."""
    # 注意: Ticker='NA' + Exchange='NA' 在 BBG 实际不会共现 (前者是 CAD/CN, 后者是 EUR);
    # 但修复逻辑应独立工作, 互不干扰.
    fills = [_make_fill("T6", "NA", Currency="EUR", Exchange="NA", SecurityName="NATL BK EUR DUMMY")]
    repo = _InMemoryRawFillRepo(raw_fills_db)
    repo.upsert_raw_api_data(fills, source_date="20260101")
    row = raw_fills_db.execute(
        "SELECT Ticker, Exchange FROM raw_fills WHERE OrderId='T6'"
    ).fetchone()
    assert row is not None
    assert row[0] == "NA", f"Ticker 应为 'NA', 实际: {row[0]!r}"
    assert row[1] == "NA", f"Exchange 应为 'NA', 实际: {row[1]!r}"
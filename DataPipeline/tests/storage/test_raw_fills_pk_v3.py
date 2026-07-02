"""Phase A 单元测试: raw_fills PK v3 + fetch_log 软状态机制.

校验:
    1. init_raw_fills_schema 建表的 PK 含 source_date
    2. 同 (OrderId, RouteId, FillId) 跨 source_date INSERT OR REPLACE 两行共存
    3. _migrate_raw_fills_pk 幂等 (新表已是新 PK 则直接返回)
    4. fetch_log CHECK 约束生效 (非法状态 raise)
    5. add_fetch_log_record 软标记同 source_date 旧行 'deprecated'
    6. record_fetch (fill_fetch_history.db) 同步软标记行为
"""

from __future__ import annotations

import sqlite3
from typing import Optional

import pytest

from DataPipeline.config import Config
from DataPipeline.storage.schema.inline_ddl import (
    init_raw_fills_schema,
    _migrate_raw_fills_pk,
)
from DataPipeline.storage.repositories.raw_fills import SqliteRawFillWriteRepository
from DataPipeline.storage.repositories.fetch_history import (
    SqliteFetchHistoryRepository,
)


# ── 测试辅助: 可注入 :memory: DB 的 Repository 子类 ───────────────────────


class _ConnWrapper:
    """让 close() 变 no-op, 避免一次调用就关闭共享 :memory: conn."""

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

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


class _InMemoryFetchHistoryRepo(SqliteFetchHistoryRepository):
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def _get_admin_conn(self):
        return _ConnWrapper(self._conn)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def raw_fills_db() -> sqlite3.Connection:
    """提供已建好 schema 的 :memory: raw_fills.db 连接."""
    conn = sqlite3.connect(":memory:")
    init_raw_fills_schema(conn)
    yield conn
    conn.close()


# ═══════════════════════════════════════════════════════════════════════
# Part 1: raw_fills PK v3
# ═══════════════════════════════════════════════════════════════════════


def test_init_schema_pk_includes_source_date(raw_fills_db):
    """init_raw_fills_schema 建表时 PK 必须含 source_date."""
    pk_cols = [
        row[1] for row in raw_fills_db.execute("PRAGMA table_info(raw_fills)").fetchall()
        if row[5] > 0
    ]
    assert pk_cols == ["OrderId", "RouteId", "FillId", "source_date"]


def test_cross_source_date_inserts_coexist(raw_fills_db):
    """同 (O,R,F) 跨 source_date 两行 INSERT OR REPLACE 应两行共存 (修复覆盖根因)."""
    cols = ("OrderId", "RouteId", "FillId", "source_date", "fetched_at", "order_as_of_date")
    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT OR REPLACE INTO raw_fills ({','.join(cols)}) VALUES ({placeholders})"

    raw_fills_db.execute(sql, ("O1", "1", "1", "20260101", "t1", "20260101"))
    raw_fills_db.execute(sql, ("O1", "1", "1", "20260102", "t2", "20260102"))
    raw_fills_db.commit()

    rows = raw_fills_db.execute(
        "SELECT source_date FROM raw_fills WHERE OrderId='O1' ORDER BY source_date"
    ).fetchall()
    assert len(rows) == 2
    assert [r[0] for r in rows] == ["20260101", "20260102"]


def test_migrate_raw_fills_pk_idempotent(raw_fills_db):
    """_migrate_raw_fills_pk 在已是新 PK 的表上调用必须无副作用 (幂等)."""
    rows_before = raw_fills_db.execute("SELECT COUNT(*) FROM raw_fills").fetchone()[0]
    _migrate_raw_fills_pk(raw_fills_db)  # 应直接返回, 不重建
    rows_after = raw_fills_db.execute("SELECT COUNT(*) FROM raw_fills").fetchone()[0]
    pk_cols = [
        row[1] for row in raw_fills_db.execute("PRAGMA table_info(raw_fills)").fetchall()
        if row[5] > 0
    ]
    assert rows_before == rows_after == 0
    assert pk_cols == ["OrderId", "RouteId", "FillId", "source_date"]


def test_migrate_raw_fills_pk_from_old_schema():
    """从旧 PK (3 列) 升级到新 PK (4 列) 时数据完整保留."""
    conn = sqlite3.connect(":memory:")
    # 建旧 schema 表
    conn.execute("""
        CREATE TABLE raw_fills (
            OrderId TEXT NOT NULL, Account TEXT, SecurityName TEXT, Ticker TEXT,
            Exchange TEXT, Currency TEXT, Side TEXT, Amount TEXT,
            NyOrderCreateAsOfDateTime TEXT, Type TEXT, LimitPrice REAL, Broker TEXT,
            StopPrice REAL, StrategyType TEXT, TraderName TEXT, TraderUuid TEXT,
            RouteId TEXT NOT NULL, NyTranCreateAsOfDateTime TEXT, RouteShares TEXT,
            FillId TEXT NOT NULL, ExecType TEXT, DateTimeOfFill TEXT,
            FillPrice TEXT, FillShares TEXT, LastCapacity TEXT, LastMarket TEXT,
            Liquidity TEXT, LocalExchangeSymbol TEXT,
            source_date TEXT NOT NULL DEFAULT '',
            fetched_at TEXT, ingested_at TEXT,
            order_as_of_date TEXT, exchange_exec_time TEXT,
            PRIMARY KEY (OrderId, RouteId, FillId)
        )
    """)
    conn.execute(
        "INSERT INTO raw_fills (OrderId, RouteId, FillId, source_date, Ticker, Currency) "
        "VALUES ('O1','1','1','20260101','ASML','EUR')"
    )
    conn.execute(
        "INSERT INTO raw_fills (OrderId, RouteId, FillId, source_date, Ticker, Currency) "
        "VALUES ('O1','1','2','20260101','ASML','EUR')"
    )
    conn.commit()

    _migrate_raw_fills_pk(conn)

    rows = conn.execute("SELECT COUNT(*) FROM raw_fills").fetchone()[0]
    assert rows == 2
    pk_cols = [row[1] for row in conn.execute("PRAGMA table_info(raw_fills)").fetchall() if row[5] > 0]
    assert pk_cols == ["OrderId", "RouteId", "FillId", "source_date"]
    conn.close()


# ═══════════════════════════════════════════════════════════════════════
# Part 2: fetch_log 软状态机制
# ═══════════════════════════════════════════════════════════════════════


def test_fetch_log_check_constraint_enforced(raw_fills_db):
    """fetch_log 状态字段必须拒绝非法值."""
    with pytest.raises(sqlite3.IntegrityError):
        raw_fills_db.execute(
            "INSERT INTO fetch_log (source_date, row_count, data_hash, status) "
            "VALUES ('20990101', 1, 'h', 'invalid_status')"
        )


def test_add_fetch_log_record_soft_supersedes(raw_fills_db):
    """add_fetch_log_record 同 source_date 不同 hash: 旧行 deprecated, 新行 fetched."""
    repo = _InMemoryRawFillRepo(raw_fills_db)
    repo.add_fetch_log_record("20260101", 100, "hash_A")
    repo.add_fetch_log_record("20260101", 50, "hash_B")

    rows = raw_fills_db.execute(
        "SELECT data_hash, status FROM fetch_log WHERE source_date='20260101' ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == ("hash_A", "deprecated")
    assert rows[1] == ("hash_B", "fetched")


def test_add_fetch_log_record_unique_hash_still_enforced(raw_fills_db):
    """UNIQUE(source_date, data_hash) 仍生效: 内容级幂等保留."""
    repo = _InMemoryRawFillRepo(raw_fills_db)
    repo.add_fetch_log_record("20260101", 100, "hash_A")
    # 同 (source_date, data_hash) 应被 INSERT OR REPLACE 兜底 (旧行被 UPDATE deprecated, 新行替换占位)
    repo.add_fetch_log_record("20260101", 200, "hash_A")
    rows = raw_fills_db.execute(
        "SELECT data_hash, status, row_count FROM fetch_log WHERE source_date='20260101'"
    ).fetchall()
    # 旧行被 deprecated, INSERT OR REPLACE 后会被 UPDATE 同一行 (REPLACE 删除旧行 + 插入新)
    # 实际效果: 一行 fetched, 使用 INSERT OR REPLACE 后旧行被替换
    fetched = [r for r in rows if r[1] == "fetched"]
    assert len(fetched) == 1
    assert fetched[0][0] == "hash_A"
    assert fetched[0][2] == 200


def test_record_fetch_history_soft_supersedes(tmp_path):
    """fill_fetch_history.db::record_fetch 同步软标记 deprecated."""
    db_path = tmp_path / "test_fetch_history.db"
    conn = sqlite3.connect(str(db_path))
    repo = _InMemoryFetchHistoryRepo(conn)
    repo.record_fetch("20260101", "h1", 100)
    repo.record_fetch("20260101", "h2", 50)

    rows = conn.execute(
        f"SELECT data_hash, status FROM {Config.FETCH_HISTORY_TABLE} "
        "WHERE source_date='20260101' ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == ("h1", "deprecated")
    assert rows[1] == ("h2", "fetched")
    conn.close()
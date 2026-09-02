"""READ tier 文件级只读测试 (009-external-data-store)。

覆盖点：
- READ 连接以 mode=ro 打开：绕过 SQL 拦截也无法写入（物理只读）；
- READ 连接不创建不存在的库（fail-fast，防误建空库）；
- READ 连接正常 SELECT；
- WRITE 连接可写且保持 WAL 模式（管道 = 唯一写入方）。
"""

from __future__ import annotations

import sqlite3

import pytest

from DataPipeline.storage.connection import AccessTier, ConnectionManager


@pytest.fixture
def mgr(tmp_path) -> ConnectionManager:
    """指向临时库文件的 ConnectionManager（raw_fills 已建表）。"""
    db = tmp_path / "raw_fills.db"
    manager = ConnectionManager(path_overrides={"raw_fills": db})
    with manager.connection("raw_fills", AccessTier.WRITE) as conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.commit()
    return manager


def test_read_conn_rejects_write_by_sql_tier(mgr):
    """READ 连接的写操作被 SQL 分类拦截（第一道防线）。"""
    with mgr.connection("raw_fills", AccessTier.READ) as conn:
        with pytest.raises(PermissionError):
            conn.execute("INSERT INTO t (v) VALUES ('x')")


def test_read_conn_physically_readonly(mgr):
    """即使经 raw_connection 绕过 SQL 拦截，文件级 mode=ro 仍拒绝写入。"""
    with mgr.connection("raw_fills", AccessTier.READ) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.raw_connection.execute("INSERT INTO t (v) VALUES ('y')")


def test_read_conn_does_not_create_missing_db(tmp_path):
    """READ 连接要求库文件已存在——缺失即 FileNotFoundError，不误建空库。"""
    manager = ConnectionManager(path_overrides={"raw_fills": tmp_path / "ghost.db"})
    with pytest.raises(FileNotFoundError):
        manager.get_connection("raw_fills", AccessTier.READ)
    # 确认没有静默创建文件
    assert not (tmp_path / "ghost.db").exists()


def test_read_conn_select_works(mgr):
    """READ 连接正常执行 SELECT 查询。"""
    with mgr.connection("raw_fills", AccessTier.WRITE) as w:
        w.execute("INSERT INTO t (v) VALUES ('a')")
        w.commit()

    with mgr.connection("raw_fills", AccessTier.READ) as r:
        rows = r.execute("SELECT v FROM t").fetchall()

    assert rows == [("a",)]


def test_write_conn_insert_and_wal(mgr):
    """WRITE 连接可写，且库保持 WAL journal mode。"""
    with mgr.connection("raw_fills", AccessTier.WRITE) as conn:
        conn.execute("INSERT INTO t (v) VALUES ('ok')")
        conn.commit()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert str(mode).lower() == "wal"

    # 写入确实落库
    with mgr.connection("raw_fills", AccessTier.READ) as r:
        count = r.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    assert count == 1


def test_env_access_tier_override(tmp_path, monkeypatch):
    """COSTVIEW_DB_ACCESS=read 时默认 tier 变为 READ（API 进程只读部署开关）。"""
    from DataPipeline.storage.connection import resolve_access_tier

    monkeypatch.setenv("COSTVIEW_DB_ACCESS", "read")
    assert resolve_access_tier() == AccessTier.READ

    monkeypatch.setenv("COSTVIEW_DB_ACCESS", "write")
    assert resolve_access_tier() == AccessTier.WRITE

    # 显式参数优先于环境变量
    monkeypatch.setenv("COSTVIEW_DB_ACCESS", "read")
    assert resolve_access_tier(AccessTier.WRITE) == AccessTier.WRITE

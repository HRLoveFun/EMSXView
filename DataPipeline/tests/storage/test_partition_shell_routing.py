"""分区表空壳路由回归测试（M3.1 / 事故 A3，2026-08-26）。

历史事故：Phase B 分区迁移在 processed_fills.db 残留 0 行空壳表
（ticker_repository 等 8 张），SqliteFillReadRepository._conn_for 以
「表存在」为路由判据，把读取路由到空壳表 → get_ticker_exchange_map
返回 {} → S5 BDIB 阶段静默短路、raw_bdib.db 停更 2 天而状态绿色。

本测试锁定三条路由规则：
1. legacy 表存在但为 0 行空壳 → 必须回退分区库
2. legacy 表存在且有数据 → 保持读 legacy（迁移前/双写场景）
3. legacy 表不存在 → 回退分区库（原有 B4 行为不回归）
"""

from __future__ import annotations

import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from DataPipeline.storage.connection import ConnectionManager
from DataPipeline.storage.repositories.fills import SqliteFillReadRepository


class PartitionShellRoutingTest(unittest.TestCase):
    """_conn_for 空壳表检测路由。"""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        # addCleanup 后注册先执行：先释放连接再删临时目录
        # （Windows 上连接未释放会导致目录删除报 WinError 32）
        self.addCleanup(self._tmp.cleanup)
        overrides = {
            "processed_fills": Path(self._tmp.name) / "processed_fills.db",
            "ticker_registry": Path(self._tmp.name) / "ticker_registry.db",
        }
        self.mgr = ConnectionManager(path_overrides=overrides)
        self.addCleanup(self.mgr.close_thread_cached_connections)

    def _admin(self, db_key: str):
        """admin 连接须显式关闭：sqlite3.Connection 的 with 仅管理事务。"""
        return closing(self.mgr.get_admin_connection(db_key))

    def _create_shell_and_partition_tables(self) -> None:
        """legacy 建 0 行空壳表；分区库建有数据表。"""
        with self._admin("processed_fills") as conn:
            conn.execute(
                "CREATE TABLE ticker_repository "
                "(equ_ticker TEXT, exchange TEXT, updated_at TEXT)"
            )
            conn.commit()
        with self._admin("ticker_registry") as conn:
            conn.execute(
                "CREATE TABLE ticker_repository "
                "(equ_ticker TEXT, exchange TEXT, updated_at TEXT)"
            )
            conn.executemany(
                "INSERT INTO ticker_repository (equ_ticker, exchange) VALUES (?, ?)",
                [("AAPL US", "US"), ("7203 JT", "JP")],
            )
            conn.commit()

    def test_shell_table_routes_to_partition_db(self) -> None:
        """legacy 空壳表（0 行）必须回退分区库——事故 A3 的直接回归锁定。"""
        self._create_shell_and_partition_tables()
        repo = SqliteFillReadRepository(connection_manager=self.mgr)
        mapping = repo.get_ticker_exchange_map(exchanges=["US", "JP"])
        self.assertEqual(mapping, {"AAPL US": "US", "7203 JT": "JP"})

    def test_live_legacy_table_still_used(self) -> None:
        """legacy 表有数据时保持读 legacy（迁移前双写场景不回归）。"""
        self._create_shell_and_partition_tables()
        with self._admin("processed_fills") as conn:
            conn.execute(
                "INSERT INTO ticker_repository (equ_ticker, exchange) "
                "VALUES ('LEG US', 'US')"
            )
            conn.commit()
        repo = SqliteFillReadRepository(connection_manager=self.mgr)
        mapping = repo.get_ticker_exchange_map(exchanges=["US"])
        self.assertEqual(mapping, {"LEG US": "US"})

    def test_missing_table_routes_to_partition_db(self) -> None:
        """legacy 表不存在时回退分区库（原有 B4 行为不回归）。"""
        self._create_shell_and_partition_tables()
        with self._admin("processed_fills") as conn:
            conn.execute("DROP TABLE ticker_repository")
            conn.commit()
        repo = SqliteFillReadRepository(connection_manager=self.mgr)
        mapping = repo.get_ticker_exchange_map(exchanges=["JP"])
        self.assertEqual(mapping, {"7203 JT": "JP"})


if __name__ == "__main__":
    unittest.main()

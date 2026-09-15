"""BDIB行情 Parquet/DuckDB 只读存储层。

提供:
    MarketStoreReader  — 通过DuckDB从Parquet读取BDIB数据

写入路径（MarketStoreWriter）已随 010-extract-pipeline 迁往独立仓库
EMSXDataPipeline（唯一写入方）。
分区布局: {BDIB_PARQUET_DIR}/year=YYYY/month=MM/data.parquet
DuckDB使用hive_partitioning自动解析year/month分区列。

Usage:
    from data_access.storage.market_store import MarketStoreReader

    reader = MarketStoreReader(Config.BDIB_PARQUET_DIR)
    df = reader.query("SELECT * FROM bdib_bars WHERE equ_ticker = ?", [ticker])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from data_access.config import Config

logger = logging.getLogger(__name__)


class MarketStoreReader:
    """通过DuckDB从Parquet文件读取BDIB数据。

    使用DuckDB的read_parquet + hive_partitioning自动解析分区列。
    """

    def __init__(self, root_dir: Optional[Path] = None):
        self._root = root_dir or Config.BDIB_PARQUET_DIR
        self._table_name = "bdib_bars"
        self._conn: Any = None
        # 防护 (M7): 最近一次查询错误 — 调用方可区分"真无数据"与"查询失败"
        self.last_query_error: Optional[str] = None

    @property
    def parquet_dir(self) -> Path:
        return self._root

    @property
    def table_name(self) -> str:
        """返回DuckDB视图表名，用于外部SQL构建。"""
        return self._table_name

    def _ensure_connection(self) -> Any:
        if self._conn is not None:
            return self._conn
        import duckdb
        self._conn = duckdb.connect()
        self._register_parquet_view()
        return self._conn

    def _register_parquet_view(self) -> None:
        if not self._root.exists():
            return
        parquet_files = list(self._root.rglob("*.parquet"))
        if not parquet_files:
            return
        glob_pattern = str(self._root / "**" / "*.parquet").replace("\\", "/")
        self._conn.execute(f"""
            CREATE OR REPLACE VIEW {self._table_name} AS
            SELECT * FROM read_parquet(
                '{glob_pattern}',
                hive_partitioning = true,
                hive_types = {{'year': VARCHAR, 'month': VARCHAR}}
            )
        """)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def query(self, sql: str, params: Optional[list] = None) -> pd.DataFrame:
        """执行DuckDB查询.

        防护 (M7): 查询失败不再静默返回空 DataFrame — 记录 error 日志并
        写入 last_query_error, 调用方可区分"真无数据"与"查询失败"。
        """
        conn = self._ensure_connection()
        try:
            if params:
                result = conn.execute(sql, params).fetchdf()
            else:
                result = conn.execute(sql).fetchdf()
            self.last_query_error = None
            return result
        except Exception as e:
            self.last_query_error = str(e)
            logger.error("DuckDB 查询失败: %s", e)
            return pd.DataFrame()



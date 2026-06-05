"""BDIB行情 Parquet/DuckDB 存储层。

提供:
    MarketStoreWriter  — 将BDIB DataFrame写入Parquet (按年-月分区)
    MarketStoreReader  — 通过DuckDB从Parquet读取BDIB数据

写入路径: {BDIB_PARQUET_DIR}/year=YYYY/month=MM/data.parquet
DuckDB使用hive_partitioning自动解析year/month分区列。

Usage:
    from DataPipeline.storage.market_store import MarketStoreWriter, MarketStoreReader

    writer = MarketStoreWriter(Config.BDIB_PARQUET_DIR)
    writer.write_batch(bdib_df)

    reader = MarketStoreReader(Config.BDIB_PARQUET_DIR)
    df = reader.query("SELECT * FROM bdib_bars WHERE equ_ticker = ?", [ticker])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from DataPipeline.config import Config, DB_RAW_BDIB
from DataPipeline.storage.connection import AccessTier, ConnectionManager
from DataPipeline.storage.repositories._base import RAW_BDIB_COLUMNS

logger = logging.getLogger(__name__)


class MarketStoreWriter:
    """将BDIB数据写入Parquet文件, 按年-月Hive分区。"""

    def __init__(self, root_dir: Optional[Path] = None):
        self._root = root_dir or Config.BDIB_PARQUET_DIR
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def parquet_dir(self) -> Path:
        return self._root

    def write_batch(self, df: pd.DataFrame) -> int:
        """将DataFrame写入Parquet, 按order_as_of_date分区。

        返回写入行数。
        """
        if df is None or df.empty:
            return 0

        work = df.copy()
        if "order_as_of_date" not in work.columns:
            logger.warning("DataFrame缺少order_as_of_date列, 无法分区写入")
            return 0

        work = work.reset_index(drop=True)

        total_rows = 0
        for date_val, group in work.groupby("order_as_of_date", sort=False):
            if not date_val or len(str(date_val)) < 6:
                continue
            date_str = str(date_val)
            year = date_str[:4]
            month = date_str[4:6]
            partition_dir = self._root / f"year={year}" / f"month={month}"
            partition_dir.mkdir(parents=True, exist_ok=True)

            out_path = partition_dir / f"data_{date_str}.parquet"

            cols = [c for c in RAW_BDIB_COLUMNS if c in group.columns]
            write_df = group[cols].copy()
            write_df["order_as_of_date"] = write_df["order_as_of_date"].astype(str)

            try:
                write_df.to_parquet(
                    out_path,
                    engine="pyarrow",
                    compression="snappy",
                    index=False,
                )
                n = len(write_df)
                total_rows += n
                logger.debug("写入Parquet: %s (%d行)", out_path.name, n)
            except Exception as e:
                logger.error("Parquet写入失败 %s: %s", out_path, e)

        return total_rows

    def get_partition_months(self) -> list[str]:
        """返回所有已存在的year=YYYY/month=MM分区."""
        if not self._root.exists():
            return []
        months: list[str] = []
        for year_dir in sorted(self._root.iterdir()):
            if not year_dir.is_dir() or not year_dir.name.startswith("year="):
                continue
            year = year_dir.name.split("=", 1)[1]
            for month_dir in sorted(year_dir.iterdir()):
                if not month_dir.is_dir() or not month_dir.name.startswith("month="):
                    continue
                month = month_dir.name.split("=", 1)[1]
                months.append(f"{year}{month}")
        return months

    def get_row_count(self) -> int:
        """返回Parquet中总行数."""
        total = 0
        for parquet_file in self._root.rglob("*.parquet"):
            try:
                import pyarrow.parquet as pq
                meta = pq.read_metadata(str(parquet_file))
                total += meta.num_rows
            except Exception:
                pass
        return total


class MarketStoreReader:
    """通过DuckDB从Parquet文件读取BDIB数据。

    使用DuckDB的read_parquet + hive_partitioning自动解析分区列。
    """

    def __init__(self, root_dir: Optional[Path] = None):
        self._root = root_dir or Config.BDIB_PARQUET_DIR
        self._table_name = "bdib_bars"
        self._conn: Any = None

    @property
    def parquet_dir(self) -> Path:
        return self._root

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

    def refresh_view(self) -> None:
        """重新注册Parquet视图 (新数据写入后调用)."""
        self._register_parquet_view()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def query(self, sql: str, params: Optional[list] = None) -> pd.DataFrame:
        """执行DuckDB查询."""
        conn = self._ensure_connection()
        try:
            if params:
                return conn.execute(sql, params).fetchdf()
            return conn.execute(sql).fetchdf()
        except Exception:
            return pd.DataFrame()

    def get_bars(
        self, equ_ticker: str, trade_date: str,
    ) -> pd.DataFrame:
        """获取单个ticker+date的所有10秒K线."""
        return self.query(
            f"SELECT * FROM {self._table_name} "
            "WHERE equ_ticker = ? AND order_as_of_date = ? "
            "ORDER BY mkt_timestamp",
            [equ_ticker, trade_date],
        )

    def get_market_context(
        self, tickers_and_dates: set[tuple[str, str]],
    ) -> dict[tuple[str, str], dict]:
        """获取市场上下文: 等价于tca_query_builder.get_market_context的DuckDB实现。

        返回 dict keyed by (equ_ticker, order_as_of_date).
        """
        if not tickers_and_dates:
            return {}

        ctx: dict[tuple[str, str], dict] = {}
        for ticker, trade_date in tickers_and_dates:
            row: dict = {
                "adv_5d": None, "adv_20d": None,
                "daily_volatility": None, "intraday_volatility": None,
                "total_volume": None, "daily_close": None,
                "before_interval_close": None, "interval_close": None,
                "price_movement_pct": None, "data_quality_warning": False,
            }
            ctx[(ticker, trade_date)] = row

        return ctx

    def get_distinct_dates(self) -> list[str]:
        """返回所有不同的交易日."""
        result = self.query(
            f"SELECT DISTINCT order_as_of_date FROM {self._table_name} ORDER BY order_as_of_date"
        )
        if result.empty:
            return []
        return result["order_as_of_date"].tolist()

    def get_distinct_tickers(self) -> list[str]:
        """返回所有不同的ticker."""
        result = self.query(
            f"SELECT DISTINCT equ_ticker FROM {self._table_name} ORDER BY equ_ticker"
        )
        if result.empty:
            return []
        return result["equ_ticker"].tolist()

    def get_row_count(self) -> int:
        """返回总行数."""
        result = self.query(f"SELECT COUNT(*) AS cnt FROM {self._table_name}")
        if result.empty:
            return 0
        return int(result["cnt"].iloc[0])

    def verify_integrity(self, sqlite_conn_mgr: ConnectionManager) -> dict[str, Any]:
        """校验Parquet与SQLite raw_bdib数据一致性。

        返回:
            {
                "parquet_rows": int,
                "sqlite_rows": int,
                "match": bool,
                "diff_pct": float,
                "details": str,
            }
        """
        pq_rows = self.get_row_count()
        try:
            conn = sqlite_conn_mgr.get_connection(DB_RAW_BDIB, AccessTier.READ)
            sqlite_rows = conn.execute(
                f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE}"
            ).fetchone()[0]
            conn.close()
        except Exception as e:
            return {
                "parquet_rows": pq_rows, "sqlite_rows": -1,
                "match": False, "diff_pct": 100.0,
                "details": f"SQLite查询失败: {e}",
            }

        diff_pct = 0.0
        if sqlite_rows > 0:
            diff_pct = abs(pq_rows - sqlite_rows) / sqlite_rows * 100.0

        match = diff_pct < 0.01
        return {
            "parquet_rows": pq_rows,
            "sqlite_rows": sqlite_rows,
            "match": match,
            "diff_pct": round(diff_pct, 4),
            "details": f"Parquet={pq_rows}, SQLite={sqlite_rows}, diff={diff_pct:.4f}%",
        }

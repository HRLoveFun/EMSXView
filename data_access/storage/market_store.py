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

from data_access.config import Config, DB_RAW_BDIB
from data_access.storage.connection import AccessTier, ConnectionManager

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

    def refresh_view(self) -> None:
        """重新注册Parquet视图 (新数据写入后调用)."""
        self._register_parquet_view()

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
        self,
        tickers_and_dates: set[tuple[str, str]],
        route_rows: list[dict] | None = None,
    ) -> dict[tuple[str, str], dict]:
        """获取市场上下文 (DuckDB/Parquet 路径)。

        从 Parquet 查询 before_interval_close / interval_close / bar completeness。
        ADV/volatility 需由调用者从 bdib_daily_summary 补充。
        （CostView.tca_query_builder 中的 SQLite+ADV 补全实现已随 010 迁移
        预计算删除——报告期市场上下文现由 tca_route_summary 预算列承载。）

        Args:
            tickers_and_dates: (equ_ticker, order_as_of_date) 集合
            route_rows: route 行列表，用于确定 interval_start/interval_end。
                        每行需含 equ_ticker, order_as_of_date, start_time, end_time。

        Returns:
            dict keyed by (equ_ticker, order_as_of_date)，含 before_interval_close,
            interval_close, price_movement_pct, data_quality_warning。
            ADV/volatility 字段为 None（需调用者补充）。
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

            if route_rows:
                # 从 route_rows 确定 interval_start / interval_end
                start_times = [
                    r["start_time"]
                    for r in route_rows
                    if r.get("equ_ticker") == ticker
                    and r["order_as_of_date"] == trade_date
                    and r.get("start_time")
                ]
                interval_start = min(start_times) if start_times else None

                end_times = [
                    r["end_time"]
                    for r in route_rows
                    if r.get("equ_ticker") == ticker
                    and r["order_as_of_date"] == trade_date
                    and r.get("end_time")
                ]
                interval_end = max(end_times) if end_times else None

                # 查询 before_interval_close
                if interval_start:
                    before_df = self.query(
                        f"SELECT close FROM {self._table_name} "
                        "WHERE equ_ticker = ? AND order_as_of_date = ? "
                        "AND mkt_timestamp < ? "
                        "ORDER BY mkt_timestamp DESC LIMIT 1",
                        [ticker, trade_date, interval_start],
                    )
                    row["before_interval_close"] = (
                        float(before_df["close"].iloc[0]) if not before_df.empty else None
                    )

                # 查询 interval_close
                if interval_end:
                    close_df = self.query(
                        f"SELECT close FROM {self._table_name} "
                        "WHERE equ_ticker = ? AND order_as_of_date = ? "
                        "AND mkt_timestamp <= ? "
                        "ORDER BY mkt_timestamp DESC LIMIT 1",
                        [ticker, trade_date, interval_end],
                    )
                    row["interval_close"] = (
                        float(close_df["close"].iloc[0]) if not close_df.empty else None
                    )

                # 计算 price_movement_pct
                if row.get("interval_close") and row.get("before_interval_close"):
                    row["price_movement_pct"] = (
                        row["interval_close"] / row["before_interval_close"] - 1.0
                    ) * 100.0

                # 查询 bar completeness
                if interval_start and interval_end:
                    count_df = self.query(
                        f"SELECT COUNT(*) AS cnt FROM {self._table_name} "
                        "WHERE equ_ticker = ? AND order_as_of_date = ? "
                        "AND mkt_timestamp >= ? AND mkt_timestamp <= ?",
                        [ticker, trade_date, interval_start, interval_end],
                    )
                    actual_bars = int(count_df["cnt"].iloc[0]) if not count_df.empty else 0
                    try:
                        from datetime import datetime as _dt
                        t_start = _dt.strptime(interval_start, "%H:%M:%S")
                        t_end = _dt.strptime(interval_end, "%H:%M:%S")
                        expected_bars = max(1, int((t_end - t_start).total_seconds() / 10))
                    except ValueError:
                        expected_bars = 1
                    row["data_quality_warning"] = actual_bars < 0.8 * expected_bars

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

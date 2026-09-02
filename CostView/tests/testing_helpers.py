"""Shared test utilities — create temp databases and test data.

Principle: delegate schema creation to production DB classes (single source of
truth), not reinvent DDL here. Zero duplication with production code.
"""

from __future__ import annotations

import gc
import logging
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pandas as pd

from data_access.storage.connection import ConnectionManager

logger = logging.getLogger(__name__)

logging.disable(logging.CRITICAL)


def _close_cached_connections(mgr: ConnectionManager) -> None:
    """关闭 ConnectionManager 的线程本地缓存连接（供 weakref.finalize 使用）。"""
    mgr.close_thread_cached_connections()


def close_temp_db(mgr: ConnectionManager) -> None:
    """关闭测试用临时数据库的全部连接并触发 GC 回收。

    Windows 下 SQLite 以 WAL 模式打开时会产生 -wal/-shm 伴生文件，
    即使连接已 close，若底层 sqlite3.Connection 对象尚未被垃圾回收，
    临时目录清理（TemporaryDirectory.cleanup）仍会抛 WinError 32。
    显式 gc.collect() 确保所有连接对象释放文件句柄。
    """
    if isinstance(mgr, _FinalizingConnectionManager):
        mgr.close()
    else:
        mgr.close_thread_cached_connections()
    gc.collect()


class _FinalizingConnectionManager(ConnectionManager):
    """在对象被回收时自动关闭线程本地缓存连接。

    Windows 下 SQLite 文件句柄需显式释放才能删除临时目录。
    测试 tearDown 清理 TemporaryDirectory 前，若 READ 缓存连接仍被
    ConnectionManager 持有，tempfile 删除会抛 WinError 32。
    本类通过 weakref.finalize 在回收时统一关闭缓存连接。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 使用模块级函数 + 显式参数，避免 finalize 强引用 self 造成循环引用
        self._finalizer = weakref.finalize(self, _close_cached_connections, self)

    def close(self) -> None:
        """显式关闭缓存连接（幂等）。"""
        if not self._finalizer.alive:
            return
        self.close_thread_cached_connections()
        self._finalizer.detach()


# ═══════════════════════════════════════════════════════════════════════════
# Temp database creation — delegates to production DB classes
# ═══════════════════════════════════════════════════════════════════════════


def create_temp_db(
    db_key: str,
    tmp_dir: str | Path,
    extra_dbs: Optional[List[str]] = None,
) -> ConnectionManager:
    """Create a temporary SQLite database, bootstrapping schema via production classes.

    Parameters
    ----------
    db_key : str
        主数据库键（如 ``"processed_fills"``），临时文件为 ``{db_key}.db``。
    tmp_dir : str | Path
        临时目录。
    extra_dbs : list[str] | None
        额外覆盖到同一临时目录的分区数据库键（如 ``"ticker_registry"``），
        防止测试写入落到真实数据目录。

    Returns
    -------
    ConnectionManager
        指向临时文件的 ConnectionManager。

    Usage::
        mgr = create_temp_db("processed_fills", self.tmp_dir.name)
        repo = SqliteFillReadRepository(mgr)
    """
    tmp_dir = Path(tmp_dir)
    overrides: Dict[str, Path] = {db_key: tmp_dir / f"{db_key}.db"}
    for extra in extra_dbs or []:
        overrides[extra] = tmp_dir / f"{extra}.db"
    mgr = _FinalizingConnectionManager(path_overrides=overrides)
    _bootstrap_schema(db_key, overrides[db_key], mgr)
    for extra in extra_dbs or []:
        _bootstrap_schema(extra, overrides[extra], mgr)
    return mgr


def _bootstrap_schema(db_key: str, db_path: Path, mgr: ConnectionManager) -> None:
    """Delegate schema creation to production schema functions (no DDL duplication)."""
    if db_key == "raw_fills":
        from data_access.storage.schema.inline_ddl import init_raw_fills_schema
        with mgr.get_admin_connection("raw_fills") as conn:
            init_raw_fills_schema(conn)
    elif db_key == "processed_fills":
        # Initialize schema via the production schema function.
        from data_access.storage.repositories._schema import init_processed_fills_schema
        from data_access.storage.repositories.fills import SqliteFillWriteRepository
        init_processed_fills_schema(SqliteFillWriteRepository(mgr))
    elif db_key == "raw_bdib":
        from data_access.storage.schema.inline_ddl import init_raw_bdib_schema
        with mgr.get_admin_connection("raw_bdib") as conn:
            init_raw_bdib_schema(conn)
    elif db_key == "processed_raw_bdib":
        from data_access.storage.schema.inline_ddl import init_processed_raw_bdib_schema
        with mgr.get_admin_connection("processed_raw_bdib") as conn:
            init_processed_raw_bdib_schema(conn)
    elif db_key == "fill_bdib":
        from data_access.storage.schema.inline_ddl import init_fill_bdib_schema
        with mgr.get_admin_connection("fill_bdib") as conn:
            init_fill_bdib_schema(conn)
    elif db_key == "regime":
        from data_access.storage.schema.migrations.apply import apply_pending
        apply_pending(db_path)
        # Add tables not managed by regime migrations (attribution, pipeline runs)
        _ensure_regime_extra_tables(mgr)
    elif db_key == "ticker_registry":
        _bootstrap_ticker_registry(db_path)
    else:
        raise ValueError(f"Unknown db_key: {db_key}")


def _bootstrap_ticker_registry(db_path: Path) -> None:
    """从 db_partition.sql 切出 ticker_registry 段执行（schema 单一来源）。

    db_partition.sql 同时包含 execution_history 与 ticker_registry 两段 DDL，
    此处按段注释标记切片，仅执行 ticker_registry 部分。
    """
    import sqlite3

    import DataPipeline

    sql_file = (
        Path(DataPipeline.__file__).resolve().parent
        / "storage" / "schema" / "db_partition.sql"
    )
    content = sql_file.read_text(encoding="utf-8")
    start = content.index("-- ticker_registry.db")
    end_marker = "-- processed_fills.db"
    end = content.index(end_marker, start)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(content[start:end])
        conn.commit()
    finally:
        conn.close()


def _ensure_regime_extra_tables(mgr: ConnectionManager) -> None:
    """Regime migrations manage ref/daily/fill tables; attribution/pipeline tables are extras."""
    conn = mgr.get_admin_connection("regime")
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fill_attribution_metrics (
                OrderId TEXT NOT NULL, RouteId TEXT NOT NULL, FillId TEXT NOT NULL,
                order_as_of_date_iso TEXT NOT NULL, config_version TEXT NOT NULL,
                market_code TEXT, broker TEXT, algo TEXT, side TEXT,
                fill_shares REAL, fill_price REAL, route_shares REAL,
                pct_adv REAL, participation_rate REAL, arrival_px REAL,
                interval_vwap REAL, mid_at_fill REAL, mid_fill_plus_1m REAL,
                mid_fill_plus_5m REAL, mid_fill_plus_30m REAL, is_bps REAL,
                vwap_bps REAL, reversal_1m_bps REAL, reversal_5m_bps REAL,
                reversal_30m_bps REAL, data_quality_flags TEXT, source_version TEXT,
                ingested_at TIMESTAMP,
                PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date_iso, config_version)
            );
            CREATE TABLE IF NOT EXISTS audit_pipeline_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT, stage_name TEXT NOT NULL,
                run_started_at TIMESTAMP, status TEXT, target_start_date TEXT,
                target_end_date TEXT, config_version TEXT, schema_version INTEGER,
                completed_at TIMESTAMP, run_finished_at TIMESTAMP,
                rows_written INTEGER DEFAULT 0, rows_updated INTEGER DEFAULT 0,
                error_message TEXT, duration_sec REAL
            );
            CREATE TABLE IF NOT EXISTS audit_research_snapshots (
                run_id INTEGER PRIMARY KEY, stage_name TEXT NOT NULL,
                config_version TEXT NOT NULL, start_date TEXT NOT NULL,
                end_date TEXT NOT NULL, rows_written INTEGER NOT NULL,
                rows_total INTEGER NOT NULL, snapshot_sha256 TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_attribution_config_versions (
                version_id TEXT PRIMARY KEY, bench_methods TEXT NOT NULL,
                reversal_windows_min TEXT NOT NULL, winsor_pct REAL NOT NULL,
                adv_window_days INTEGER NOT NULL, bootstrap_n INTEGER NOT NULL,
                min_cell_n INTEGER NOT NULL, is_active INTEGER DEFAULT 0,
                description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# Test DataFrame Factories
# ═══════════════════════════════════════════════════════════════════════════


def make_fills_dataframe(
    num_rows: int = 5,
    date_str: str = "20260408",
    base_order_id: str = "ORD001",
) -> pd.DataFrame:
    """Generate a test DataFrame mimicking processed_fills table structure.

    Parameters
    ----------
    num_rows : int
        Number of fill rows to generate.
    date_str : str
        Order-as-of date in YYYYMMDD format.
    base_order_id : str
        Base order ID prefix.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns matching processed_fills schema.
    """
    rows = []
    for i in range(num_rows):
        rows.append({
            "OrderId": f"{base_order_id}",
            "RouteId": f"RTE{i:03d}",
            "FillId": f"FILL{i:05d}",
            "order_as_of_date": date_str,
            "mkt_timestamp": f"09:30:{i:02d}0",
            "exchange_exec_time": f"2026-04-08 09:30:{i:02d}0",
            "ExecType": "FILL",
            "FillPrice": 100.0 + i * 0.5,
            "FillShares": 100 + i * 10,
            "RouteShares": 200 + i * 10,
            "Side": "BUY",
            "Broker": "BROKER_A",
            "StrategyType": "VWAP",
            "Amount": 10000.0 + i * 500,
            "Exchange": "US",
            "Currency": "USD",
            "region": "US",
            "algo": "VWAP",
            "TraderName": "TraderA",
            "DateTimeOfFill": f"2026-04-08 09:30:{i:02d}0.000000-04:00",
            "is_closing_auction": 0,
            "route_as_of_time": f"09:30:{i:02d}0",
        })
    return pd.DataFrame(rows)


def make_bdib_dataframe(
    num_bars: int = 10,
    date_str: str = "20260408",
    ticker: str = "AAPL US Equity",
    base_close: float = 100.0,
) -> pd.DataFrame:
    """Generate a test DataFrame mimicking raw BDIB bar structure.

    Parameters
    ----------
    num_bars : int
        Number of 10-second bars to generate.
    date_str : str
        Trade date in YYYYMMDD format.
    ticker : str
        Equity ticker symbol.
    base_close : float
        Starting close price.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns matching raw_bdib schema.
    """
    rows = []
    for i in range(num_bars):
        total_seconds = 9 * 3600 + 30 * 60 + i * 10  # 09:30:00 onwards
        hh, rem = divmod(total_seconds, 3600)
        mm, ss = divmod(rem, 60)
        rows.append({
            "equ_ticker": ticker,
            "order_as_of_date": date_str,
            "mkt_timestamp": f"{hh:02d}:{mm:02d}:{ss:02d}",
            "open": base_close + i * 0.1,
            "high": base_close + i * 0.1 + 0.05,
            "low": base_close + i * 0.1 - 0.05,
            "close": base_close + i * 0.1,
            "volume": 1000.0 + i * 10,
            "num_trds": 10.0 + i,
            "value": 100000.0 + i * 1000,
        })
    return pd.DataFrame(rows)


def make_raw_fills_dataframe(
    num_rows: int = 3,
    date_str: str = "20260408",
) -> pd.DataFrame:
    """Generate a test DataFrame mimicking raw_fills table structure."""
    rows = []
    for i in range(num_rows):
        rows.append({
            "OrderId": f"ORD{i:03d}",
            "RouteId": f"RTE{i:03d}",
            "FillId": f"FILL{i:05d}",
            "Account": f"ACC{i:03d}",
            "SecurityName": f"SEC{i:03d}",
            "Ticker": "AAPL",
            "Exchange": "US",
            "Currency": "USD",
            "Side": "BUY",
            "Amount": str(10000.0 + i * 1000),
            "NyOrderCreateAsOfDateTime": f"2026-04-08T09:30:00",
            "Type": "LIMIT",
            "LimitPrice": str(100.0 + i),
            "Broker": "BROKER_A",
            "RouteId": f"RTE{i:03d}",
            "RouteShares": str(200),
            "FillId": f"FILL{i:05d}",
            "ExecType": "FILL",
            "DateTimeOfFill": f"2026-04-08T09:30:0{i}",
            "FillPrice": str(100.0 + i * 0.5),
            "FillShares": str(100),
            "LastCapacity": "AGENCY",
            "LastMarket": "NASDAQ",
            "source_date": date_str,
        })
    return pd.DataFrame(rows)


def make_integrated_dataframe(
    num_rows: int = 3,
    date_str: str = "20260408",
) -> pd.DataFrame:
    """Generate a test DataFrame mimicking fill_bdib table structure."""
    rows = []
    for i in range(num_rows):
        rows.append({
            "OrderId": f"ORD001",
            "RouteId": f"RTE{i:03d}",
            "order_as_of_date": date_str,
            "mkt_timestamp": f"09:30:0{i}",
            "equ_ticker": "AAPL US Equity",
            "ccy_ticker": "USD",
            "fill_volume": 100.0 + i * 10,
            "fill_px": 100.0 + i * 0.5,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5 + i * 0.1,
            "volume": 1000.0,
            "value": 100000.0,
            "vwap": 100.3,
            "log_chg_pct_10s": 0.001,
            "fx_rate": 1.0,
            "cum_vwap": 100.3,
            "cum_fill_vwap": 100.2,
            "cum_slippage_bps": -0.5,
            "cum_slippage_usd": -10.0,
            "cum_volume_pct": 0.1,
            "cum_tracking_error": 0.02,
            "cum_info_ratio": 0.5,
            "cum_interval_volatility": 0.15,
            "standard_cum_interval_volatility": 0.15,
        })
    return pd.DataFrame(rows)


def make_attribution_dataframe(
    num_rows: int = 3,
    date_iso: str = "2026-04-08",
    config_version: str = "test-v1",
) -> pd.DataFrame:
    """Generate a test DataFrame for attribution metrics."""
    rows = []
    for i in range(num_rows):
        rows.append({
            "OrderId": f"ORD001",
            "RouteId": f"RTE{i:03d}",
            "FillId": f"FILL{i:05d}",
            "order_as_of_date_iso": date_iso,
            "config_version": config_version,
            "market_code": "US",
            "broker": "BROKER_A",
            "algo": "VWAP",
            "side": "BUY",
            "fill_shares": 100.0,
            "fill_price": 100.0 + i * 0.5,
            "route_shares": 200.0,
            "pct_adv": 0.01,
            "participation_rate": 0.05,
            "arrival_px": 99.5,
            "interval_vwap": 100.3,
            "mid_at_fill": 100.0,
            "mid_fill_plus_1m": 100.1,
            "mid_fill_plus_5m": 100.5,
            "mid_fill_plus_30m": 101.0,
            "is_bps": 5.0,
            "vwap_bps": 3.0,
            "reversal_1m_bps": -1.0,
            "reversal_5m_bps": -5.0,
            "reversal_30m_bps": -10.0,
            "data_quality_flags": "OK",
            "source_version": "1.0",
            "ingested_at": "2026-04-08T12:00:00",
        })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════
# Fake / Mock Factories
# ═══════════════════════════════════════════════════════════════════════════


class FakePipelineContext:
    """Lightweight mock of PipelineContext for stage testing.

    Provides the essential API surface (db, summary, errors, log_error)
    without requiring a real database connection.

    Usage:
        ctx = FakePipelineContext(target_dates=["20260408"])
        ctx.summary["processing"] = {"rows_processed": 100}
    """

    def __init__(
        self,
        target_dates: Optional[List[str]] = None,
        force: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.target_dates = target_dates or []
        self.force = force
        self.config = config or {}
        self.excel_dir = None
        self.summary: Dict[str, Any] = {}
        self.is_successful = True
        self.errors: List[Dict[str, Any]] = []
        # stage 实现演进后新增的上下文字段；真实 PipelineContext 均有，
        # Fake 版保持 None 以模拟"无连接管理器"环境
        self.connection_manager = None
        self.run_id = None

        # Repository injection fields
        self.fill_repo = None
        self.bar_repo = None
        self.regime_repo = None
        self.config_repo = None

        # Mock the db facade with new repository API
        self._db = MagicMock()

        # Mock individual repositories
        self._db.fills_read = MagicMock()
        self._db.fills_write = MagicMock()
        self._db.raw_fills_read = MagicMock()
        self._db.raw_fills_write = MagicMock()
        self._db.market_data_read = MagicMock()
        self._db.market_data_write = MagicMock()
        self._db.integrated_read = MagicMock()
        self._db.integrated_write = MagicMock()
        self._db.regime_read = MagicMock()
        self._db.regime_write = MagicMock()

    @property
    def db(self):
        return self._db

    def log_error(self, stage_name: str, error: Exception) -> None:
        self.errors.append({"stage": stage_name, "error": str(error)})
        self.is_successful = False


def assert_dataframe_equal(
    actual: pd.DataFrame,
    expected: pd.DataFrame,
    check_dtype: bool = False,
) -> None:
    """Assert two DataFrames are equal, ignoring row order.

    Parameters
    ----------
    actual : pd.DataFrame
        Actual result.
    expected : pd.DataFrame
        Expected result.
    check_dtype : bool
        Whether to check column dtypes (default: False).
    """
    if actual.empty and expected.empty:
        return

    # Sort by all columns for comparison
    sort_cols = list(actual.columns)
    actual_sorted = actual.sort_values(by=sort_cols).reset_index(drop=True)
    expected_sorted = expected.sort_values(by=sort_cols).reset_index(drop=True)

    if check_dtype:
        pd.testing.assert_frame_equal(actual_sorted, expected_sorted)
    else:
        pd.testing.assert_frame_equal(
            actual_sorted, expected_sorted, check_dtype=False,
        )

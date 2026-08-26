"""Inline DDL for databases without formal migration systems.

Each function creates tables and indexes (IF NOT EXISTS) for a specific
database, using a raw ``sqlite3.Connection`` obtained from
``ConnectionManager.get_admin_connection()``.

These functions are called by ``MigrationManager._ensure_inline_schema()``
instead of instantiating old DB classes, breaking the dependency on the
legacy layer.

Note: migration logic (ALTER TABLE ADD COLUMN) is intentionally omitted
here.  That logic is idempotent and runs automatically when the old DB
classes are instantiated by the pipeline.  The purpose of this module is
to ensure the database file and its base schema exist.
"""

from __future__ import annotations

import logging
import sqlite3

from DataPipeline.config import Config
from .columns import (
    AGG_1MIN_COLUMNS,
    AGG_COLUMNS,
    COLUMN_TYPE_MAP,
    FX_RATES_COLUMNS,
    ORDER_HISTORY_COLUMNS,
    PROCESSED_COLUMNS,
    ROUTE_EVENT_HISTORY_COLUMNS,
    ROUTE_HISTORY_COLUMNS,
    ROUTE_REGISTRY_COLUMNS,
    TCA_CORE_BENCHMARKS_COLUMNS,
    TCA_RISK_IMPACT_COLUMNS,
    TCA_ROUTE_SUMMARY_COLUMNS,
)

logger = logging.getLogger(__name__)


def _build_column_defs(columns: list[str], type_map: dict[str, str]) -> str:
    """Build SQL column definition string from column list."""
    parts = []
    for col in columns:
        col_type = type_map.get(col, "TEXT")
        parts.append(f"[{col}] {col_type}")
    return ",\n                    ".join(parts)


def init_raw_fills_schema(conn: sqlite3.Connection) -> None:
    """Create raw_fills.db tables and indexes."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.RAW_FILLS_TABLE} (
            OrderId               TEXT NOT NULL,
            Account               TEXT,
            SecurityName          TEXT,
            Ticker                TEXT,
            Exchange              TEXT,
            Currency              TEXT,
            Side                  TEXT,
            Amount                REAL,
            NyOrderCreateAsOfDateTime TEXT,
            Type                  TEXT,
            LimitPrice            REAL,
            Broker                TEXT,
            StopPrice             REAL,
            StrategyType          TEXT,
            TraderName            TEXT,
            TraderUuid            TEXT,
            RouteId               TEXT NOT NULL,
            NyTranCreateAsOfDateTime TEXT,
            RouteShares           INTEGER,
            FillId                TEXT NOT NULL,
            ExecType              TEXT,
            DateTimeOfFill        TEXT,
            FillPrice             REAL,
            FillShares            INTEGER,
            LastCapacity          TEXT,
            LastMarket            TEXT,
            Liquidity             TEXT,
            LocalExchangeSymbol   TEXT,
            source_date           TEXT NOT NULL DEFAULT '',
            fetched_at            TEXT DEFAULT (datetime('now')),
            ingested_at           TEXT DEFAULT (datetime('now')),
            order_as_of_date      TEXT DEFAULT '',
            exchange_exec_time    TEXT DEFAULT '',
            PRIMARY KEY (OrderId, RouteId, FillId, source_date)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_raw_source_date
        ON {Config.RAW_FILLS_TABLE} (source_date)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_raw_order_date
        ON {Config.RAW_FILLS_TABLE} (order_as_of_date)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_raw_ticker
        ON {Config.RAW_FILLS_TABLE} (Ticker)
    """)

    # fetch_log
    # status 软状态机: 'fetched'(current) / 'deprecated'(被新版本取代) /
    #                  'superseded'(显式替换) / 'failed'(拉取失败)
    # 同 source_date 多次 fetch 时, add_fetch_log_record 自动软标记旧行 deprecated,
    # 与 UNIQUE(source_date, data_hash) 共同实现 latest-wins 语义同时保留审计
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.FETCH_LOG_TABLE} (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            source_date           TEXT NOT NULL,
            fetch_timestamp       TEXT DEFAULT (datetime('now')),
            row_count             INTEGER NOT NULL,
            data_hash             TEXT NOT NULL,
            file_path             TEXT,
            status                TEXT NOT NULL DEFAULT 'fetched'
                                  CHECK (status IN ('fetched','deprecated','superseded','failed')),
            UNIQUE(source_date, data_hash)
        )
    """)

    # ingestion_log (legacy)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.INGESTION_LOG_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_date TEXT NOT NULL,
            source_file TEXT,
            ingestion_timestamp TEXT DEFAULT (datetime('now')),
            row_count INTEGER,
            new_row_count INTEGER,
            hash_value TEXT,
            UNIQUE(source_date, hash_value)
        )
    """)

    # order_fetch_log
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.ORDER_FETCH_LOG_TABLE} (
            order_id              TEXT NOT NULL,
            source_date           TEXT NOT NULL,
            fetch_timestamp       TEXT DEFAULT (datetime('now')),
            row_count             INTEGER NOT NULL,
            data_hash             TEXT NOT NULL,
            PRIMARY KEY (order_id, source_date)
        )
    """)
    conn.commit()

    _migrate_raw_fills_column_types(conn)
    _migrate_raw_fills_pk(conn)

    logger.debug("raw_fills.db schema ensured (inline DDL)")


# raw_fills 表完整列顺序（与 init_raw_fills_schema DDL 一致）
_RAW_FILLS_ALL_COLUMNS = [
    "OrderId", "Account", "SecurityName", "Ticker", "Exchange",
    "Currency", "Side", "Amount", "NyOrderCreateAsOfDateTime",
    "Type", "LimitPrice", "Broker", "StopPrice", "StrategyType",
    "TraderName", "TraderUuid", "RouteId", "NyTranCreateAsOfDateTime",
    "RouteShares", "FillId", "ExecType", "DateTimeOfFill",
    "FillPrice", "FillShares", "LastCapacity", "LastMarket",
    "Liquidity", "LocalExchangeSymbol",
    "source_date", "fetched_at", "ingested_at",
    "order_as_of_date", "exchange_exec_time",
]


def _migrate_raw_fills_column_types(conn: sqlite3.Connection) -> None:
    """将 LimitPrice/StopPrice 列从 TEXT 升级为 REAL（幂等）。

    v2 修复：raw_fills 表的 LimitPrice/StopPrice 原为 TEXT，与 Pydantic Schema
    (float | None)、Bloomberg getElementAsFloat、下游 CostView 测试 DDL 不一致。
    本函数检测若仍为 TEXT，则用 CREATE NEW + COPY + DROP + RENAME 模式重建表
    （SQLite 不支持 ALTER COLUMN 改类型）。

    安全保障：
    - 幂等：已是 REAL 则直接返回，可安全重跑
    - 单事务：BEGIN/COMMIT 包裹，全成功或全回滚
    - 崩溃恢复：开头清理上次崩溃可能残留的 _new 表
    - 空字符串→NULL：避免 '' 被 SQLite 类型亲和转为 0.0
    """
    table = Config.RAW_FILLS_TABLE
    col_info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not col_info:
        return

    col_types = {row[1]: row[2].upper() for row in col_info}
    limit_type = col_types.get("LimitPrice", "")
    stop_type = col_types.get("StopPrice", "")

    if limit_type == "REAL" and stop_type == "REAL":
        return

    logger.info(
        "raw_fills 列类型迁移: LimitPrice(%s→REAL), StopPrice(%s→REAL)",
        limit_type, stop_type,
    )

    conn.execute(f"DROP TABLE IF EXISTS {table}_new")

    conn.execute("BEGIN")
    try:
        conn.execute(f"""
            CREATE TABLE {table}_new (
                OrderId               TEXT NOT NULL,
                Account               TEXT,
                SecurityName          TEXT,
                Ticker                TEXT,
                Exchange              TEXT,
                Currency              TEXT,
                Side                  TEXT,
                Amount                TEXT,
                NyOrderCreateAsOfDateTime TEXT,
                Type                  TEXT,
                LimitPrice            REAL,
                Broker                TEXT,
                StopPrice             REAL,
                StrategyType          TEXT,
                TraderName            TEXT,
                TraderUuid            TEXT,
                RouteId               TEXT NOT NULL,
                NyTranCreateAsOfDateTime TEXT,
                RouteShares           TEXT,
                FillId                TEXT NOT NULL,
                ExecType              TEXT,
                DateTimeOfFill        TEXT,
                FillPrice             TEXT,
                FillShares            TEXT,
                LastCapacity          TEXT,
                LastMarket            TEXT,
                Liquidity             TEXT,
                LocalExchangeSymbol   TEXT,
                source_date           TEXT NOT NULL DEFAULT '',
                fetched_at            TEXT DEFAULT (datetime('now')),
                ingested_at           TEXT DEFAULT (datetime('now')),
                order_as_of_date      TEXT DEFAULT '',
                exchange_exec_time    TEXT DEFAULT '',
                PRIMARY KEY (OrderId, RouteId, FillId, source_date)
            )
        """)

        col_list = ", ".join(_RAW_FILLS_ALL_COLUMNS)
        select_exprs = ", ".join(
            f"CASE WHEN TRIM([{c}])='' OR [{c}] IS NULL THEN NULL ELSE CAST([{c}] AS REAL) END"
            if c in ("LimitPrice", "StopPrice") else f"[{c}]"
            for c in _RAW_FILLS_ALL_COLUMNS
        )
        conn.execute(f"INSERT INTO {table}_new ({col_list}) SELECT {select_exprs} FROM {table}")

        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")

        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_raw_source_date ON {table} (source_date)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_raw_order_date ON {table} (order_as_of_date)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_raw_ticker ON {table} (Ticker)")

        conn.execute("COMMIT")
        logger.info("raw_fills 列类型迁移完成: LimitPrice/StopPrice → REAL")
    except Exception:
        conn.execute("ROLLBACK")
        conn.execute(f"DROP TABLE IF EXISTS {table}_new")
        raise


def _migrate_raw_fills_pk(conn: sqlite3.Connection) -> None:
    """将 raw_fills PK 从 (OrderId, RouteId, FillId) 升级为 + source_date 4 元组（幂等）。

    v3 修复：原 PK 不含 source_date, 导致 Bloomberg 同 OrderId 跨日 fetch 时
    INSERT OR REPLACE 覆盖早期 source_date 行 (209 个孤儿行的根因)。新增
    source_date 维度后, 跨日同 PK 自然分离为新行, 不再覆盖。

    安全保障:
    - 幂等: PRAGMA 检测 PK 已含 source_date 则直接返回, 可安全重跑
    - 单事务: BEGIN/COMMIT 包裹, 全成功或全回滚
    - 崩溃恢复: 开头清理上次崩溃可能残留的 _new 表
    - 零数据丢失: 与 v2_to_v3.sql 等价; 实测 0 个新 PK 冲突组与 0 行 source_date NULL
    """
    table = Config.RAW_FILLS_TABLE
    col_info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not col_info:
        return

    # PK 列在 PRAGMA 中按 pk 列序号返回; 0 表示非 PK, >0 表示 PK 第 N 列
    pk_cols = [row[1] for row in col_info if row[5] > 0]
    if "source_date" in pk_cols:
        return  # 已升级到 v3

    logger.info(
        "raw_fills PK 迁移: (%s) -> (%s, source_date)",
        ", ".join(pk_cols), ", ".join(pk_cols),
    )

    conn.execute(f"DROP TABLE IF EXISTS {table}_new")
    conn.execute("BEGIN")
    try:
        conn.execute(f"""
            CREATE TABLE {table}_new (
                OrderId               TEXT NOT NULL,
                Account               TEXT,
                SecurityName          TEXT,
                Ticker                TEXT,
                Exchange              TEXT,
                Currency              TEXT,
                Side                  TEXT,
                Amount                TEXT,
                NyOrderCreateAsOfDateTime TEXT,
                Type                  TEXT,
                LimitPrice            REAL,
                Broker                TEXT,
                StopPrice             REAL,
                StrategyType          TEXT,
                TraderName            TEXT,
                TraderUuid            TEXT,
                RouteId               TEXT NOT NULL,
                NyTranCreateAsOfDateTime TEXT,
                RouteShares           TEXT,
                FillId                TEXT NOT NULL,
                ExecType              TEXT,
                DateTimeOfFill        TEXT,
                FillPrice             TEXT,
                FillShares            TEXT,
                LastCapacity          TEXT,
                LastMarket            TEXT,
                Liquidity             TEXT,
                LocalExchangeSymbol   TEXT,
                source_date           TEXT NOT NULL DEFAULT '',
                fetched_at            TEXT DEFAULT (datetime('now')),
                ingested_at           TEXT DEFAULT (datetime('now')),
                order_as_of_date      TEXT DEFAULT '',
                exchange_exec_time    TEXT DEFAULT '',
                PRIMARY KEY (OrderId, RouteId, FillId, source_date)
            )
        """)

        col_list = ", ".join(_RAW_FILLS_ALL_COLUMNS)
        conn.execute(f"INSERT INTO {table}_new ({col_list}) SELECT {col_list} FROM {table}")

        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")

        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_raw_source_date ON {table} (source_date)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_raw_order_date ON {table} (order_as_of_date)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_raw_ticker ON {table} (Ticker)")

        conn.execute("COMMIT")
        logger.info("raw_fills PK 迁移完成: 已加入 source_date 维度")
    except Exception:
        conn.execute("ROLLBACK")
        conn.execute(f"DROP TABLE IF EXISTS {table}_new")
        raise


def init_raw_bdib_schema(conn: sqlite3.Connection) -> None:
    """Create raw_bdib.db tables and indexes.

    历史：物理表曾残留 3 个废弃衍生列（vwap / fluctuation / log_chg_pct_10s），
    这些列是早期版本 DDL 直接 CREATE TABLE 时包含的，当前代码不再写入。
    修复记录（2026-07-07）：
    - v1: 运行 scripts/ops/cleanup_raw_bdib_empty_bars.py 清理 28,591 行空 bar
    - v2: 运行 raw_bdib/v1_to_v2.sql 删除三个废弃列（SQLite 3.35+ DROP COLUMN）
    当前 schema 已对齐代码定义（12 列），衍生字段由 compute_derived_fields() 内存即时计算。
    """
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.RAW_BDIB_TABLE} (
            equ_ticker       TEXT NOT NULL,
            order_as_of_date TEXT NOT NULL,
            mkt_timestamp    TEXT NOT NULL,
            open             REAL,
            high             REAL,
            low              REAL,
            close            REAL,
            volume           REAL,
            num_trds         REAL,
            value            REAL,
            fetched_at       TEXT DEFAULT (datetime('now')),
            source           TEXT DEFAULT 'bloomberg',
            PRIMARY KEY (equ_ticker, order_as_of_date, mkt_timestamp)
        )
    """)
    # 冗余索引清理: idx_raw_bdib_date 被 idx_raw_bdib_date_ticker 前缀覆盖，
    # idx_raw_bdib_ticker 被 PK(equ_ticker, ...) 覆盖，移除以减少写入开销
    conn.execute(f"DROP INDEX IF EXISTS idx_raw_bdib_date")
    conn.execute(f"DROP INDEX IF EXISTS idx_raw_bdib_ticker")
    # 保留 (order_as_of_date, equ_ticker) 复合索引，覆盖按日期+ticker 查询场景
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_raw_bdib_date_ticker ON {Config.RAW_BDIB_TABLE} (order_as_of_date, equ_ticker)"
    )

    # bdib_daily_summary
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.BDIB_DAILY_SUMMARY_TABLE} (
            equ_ticker        TEXT NOT NULL,
            trade_date        TEXT NOT NULL,
            total_volume      REAL,
            daily_vwap        REAL,
            daily_close       REAL,
            daily_volatility  REAL,
            intraday_volatility REAL,
            adv_5d            REAL,
            adv_20d           REAL,
            computed_at       TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (equ_ticker, trade_date)
        )
    """)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_daily_summary_ticker "
        f"ON {Config.BDIB_DAILY_SUMMARY_TABLE} (equ_ticker)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_daily_summary_date "
        f"ON {Config.BDIB_DAILY_SUMMARY_TABLE} (trade_date)"
    )
    conn.commit()
    logger.debug("raw_bdib.db schema ensured (inline DDL)")


def init_processed_raw_bdib_schema(conn: sqlite3.Connection) -> None:
    """Create processed_raw_bdib.db tables and indexes."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.PROCESSED_RAW_BDIB_TABLE} (
            equ_ticker       TEXT NOT NULL,
            order_as_of_date TEXT NOT NULL,
            mkt_timestamp    TEXT NOT NULL,
            open             REAL,
            high             REAL,
            low              REAL,
            close            REAL,
            volume           REAL,
            num_trds         REAL,
            value            REAL,
            vwap             REAL,
            fluctuation      REAL,
            log_chg_pct_10s  REAL,
            fetched_at       TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (equ_ticker, order_as_of_date, mkt_timestamp)
        )
    """)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_proc_raw_bdib_date ON {Config.PROCESSED_RAW_BDIB_TABLE} (order_as_of_date)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_proc_raw_bdib_ticker ON {Config.PROCESSED_RAW_BDIB_TABLE} (equ_ticker)"
    )
    conn.commit()
    logger.debug("processed_raw_bdib.db schema ensured (inline DDL)")


def init_fill_bdib_schema(conn: sqlite3.Connection) -> None:
    """Create fill_bdib.db tables and indexes."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.FILL_BDIB_TABLE} (
            OrderId                          TEXT NOT NULL,
            RouteId                          TEXT NOT NULL,
            order_as_of_date                 TEXT NOT NULL,
            mkt_timestamp                    TEXT NOT NULL,
            equ_ticker                       TEXT,
            ccy_ticker                       TEXT,
            fill_volume                       REAL,
            fill_px                           REAL,
            open                              REAL,
            high                              REAL,
            low                               REAL,
            close                             REAL,
            volume                            REAL,
            value                             REAL,
            vwap                              REAL,
            log_chg_pct_10s                   REAL,
            fx_rate                           REAL,
            cum_vwap                          REAL,
            cum_fill_vwap                     REAL,
            cum_slippage_bps                  REAL,
            cum_slippage_usd                  REAL,
            cum_volume_pct                    REAL,
            cum_tracking_error                REAL,
            cum_info_ratio                   REAL,
            cum_interval_volatility           REAL,
            standard_cum_interval_volatility   REAL,
            PRIMARY KEY (OrderId, RouteId, order_as_of_date, mkt_timestamp)
        )
    """)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_fill_bdib_date ON {Config.FILL_BDIB_TABLE} (order_as_of_date)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_fill_bdib_ticker ON {Config.FILL_BDIB_TABLE} (equ_ticker)"
    )
    conn.commit()

    # 同时确保 tca_route_summary 表存在
    init_tca_route_summary_schema(conn)
    # fx-rate-persistence: 同时确保 fx_rates 汇率表存在（币种 × 交易日唯一真相源）
    init_fx_rates_schema(conn)
    logger.debug("fill_bdib.db schema ensured (inline DDL)")


def init_tca_route_summary_schema(conn: sqlite3.Connection) -> None:
    """Create tca_route_summary table in fill_bdib.db.

    processed_bdib 层：存储基于 raw_bdib 衍生的路由级 TCA 指标，
    作为 raw_bdib 相关衍生列/中间值的统一存储层。
    """
    trs_cols = _build_column_defs(TCA_ROUTE_SUMMARY_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.TCA_ROUTE_SUMMARY_TABLE} (
            {trs_cols},
            PRIMARY KEY (OrderId, RouteId, order_as_of_date)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_trs_date
        ON {Config.TCA_ROUTE_SUMMARY_TABLE} (order_as_of_date)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_trs_ticker
        ON {Config.TCA_ROUTE_SUMMARY_TABLE} (equ_ticker)
    """)
    conn.commit()

    # 003-tca-core-benchmarks: 追加 Phase 0 + Phase 1 新列（幂等表重建迁移）
    _migrate_tca_route_summary_v2(conn)
    # 007-costview-report-filters: 追加路由级 fx_rate 列（幂等轻量迁移）
    _migrate_tca_route_summary_add_fx_rate(conn)

    logger.debug("tca_route_summary schema ensured (inline DDL)")


def init_fx_rates_schema(conn: sqlite3.Connection) -> None:
    """Create fx_rates table in fill_bdib.db（fx-rate-persistence）。

    币种 × 交易日汇率唯一真相源：
    - PK (ccy_ticker, order_as_of_date) 同时覆盖精确命中与 ≤日期回退两类查询
      （前缀命中 + 前缀内按日期序倒扫）
    - px_last 与 fx_rate 双存（原始逆报价 + 换算值），便于审计与精度追溯
    - source 区分 'bloomberg'（实时拉取）与 'fill_bdib_seed'（历史反推）
    """
    fx_cols = _build_column_defs(FX_RATES_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.FX_RATES_TABLE} (
            {fx_cols},
            PRIMARY KEY (ccy_ticker, order_as_of_date)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_fx_rates_date
        ON {Config.FX_RATES_TABLE} (order_as_of_date)
    """)
    conn.commit()
    logger.debug("fx_rates schema ensured (inline DDL)")


# 003-tca-core-benchmarks: Phase 0 + Phase 1 新增列（一次表重建，幂等）
_TCA_V2_NEW_COLUMNS: list[str] = TCA_CORE_BENCHMARKS_COLUMNS + TCA_RISK_IMPACT_COLUMNS


def _migrate_tca_route_summary_add_fx_rate(conn: sqlite3.Connection) -> None:
    """tca_route_summary 追加路由级 fx_rate 列（007，幂等轻量迁移）。"""
    table = Config.TCA_ROUTE_SUMMARY_TABLE
    try:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.OperationalError:
        return  # 表不存在，由 CREATE TABLE IF NOT EXISTS 处理
    if "fx_rate" in existing:
        return  # 幂等：已迁移完成
    conn.execute(f'ALTER TABLE {table} ADD COLUMN fx_rate REAL')
    logger.info("tca_route_summary 表新增 fx_rate 列（007）")


def _migrate_tca_route_summary_v2(conn: sqlite3.Connection) -> None:
    """tca_route_summary 表重建迁移：追加 Phase0 + Phase1 新列（幂等）。

    遵循项目表重建模式（CREATE _new + COPY + DROP + RENAME），而非 ALTER
    TABLE ADD COLUMN —— 与 ``_migrate_raw_fills_column_types`` 一致。
    安全保证：
    - 幂等：PRAGMA table_info 检查新列已存在即跳过
    - 单事务：BEGIN/COMMIT 包裹整个操作
    - 崩溃恢复：开头 DROP TABLE IF EXISTS _new 清理残留
    - 现有列原样复制，新列填 NULL（数据零改动）
    """
    table = Config.TCA_ROUTE_SUMMARY_TABLE
    col_info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not col_info:
        return  # 表不存在，由 CREATE TABLE IF NOT EXISTS 处理

    existing = {row[1] for row in col_info}
    if set(_TCA_V2_NEW_COLUMNS) <= existing:
        return  # 幂等：已迁移完成

    all_cols = TCA_ROUTE_SUMMARY_COLUMNS  # 35 现有 + 20 新列（columns.py 已更新）
    conn.execute(f"DROP TABLE IF EXISTS {table}_new")
    conn.execute("BEGIN")
    try:
        cols_def = _build_column_defs(all_cols, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE {table}_new (
                {cols_def},
                PRIMARY KEY (OrderId, RouteId, order_as_of_date)
            )
        """)
        select_exprs = ", ".join(
            f"[{c}]" if c in existing else "NULL"
            for c in all_cols
        )
        conn.execute(f"""
            INSERT INTO {table}_new ({", ".join(all_cols)})
            SELECT {select_exprs} FROM {table}
        """)
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_trs_date ON {table} (order_as_of_date)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_trs_ticker ON {table} (equ_ticker)"
        )
        conn.execute("COMMIT")
        logger.info("tca_route_summary 表重建迁移完成: +%d 新列", len(_TCA_V2_NEW_COLUMNS))
    except Exception:
        conn.execute("ROLLBACK")
        conn.execute(f"DROP TABLE IF EXISTS {table}_new")
        raise


def _migrate_processed_fills_add_fx_rate(conn: sqlite3.Connection) -> None:
    """processed_fills 追加 fx_rate 列（007-costview-report-filters，幂等）。

    轻量 ALTER TABLE ADD COLUMN（仅新增一列，无重建），已存在则跳过。
    """
    table = Config.PROCESSED_FILLS_TABLE
    try:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.OperationalError:
        return  # 表不存在，由 CREATE TABLE IF NOT EXISTS 处理
    if "fx_rate" in existing:
        return  # 幂等：已迁移完成
    conn.execute(f'ALTER TABLE {table} ADD COLUMN fx_rate REAL')
    logger.info("processed_fills 表新增 fx_rate 列（007）")


def init_processed_fills_schema(conn: sqlite3.Connection) -> None:
    """Create processed_fills.db tables and indexes.

    This is the most complex database with 7+ tables.  Column definitions
    are imported from ``db.schema.columns`` to stay in sync with the rest
    of the codebase.
    """
    # ── processed_fills ──
    proc_cols = _build_column_defs(PROCESSED_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.PROCESSED_FILLS_TABLE} (
            {proc_cols},
            PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_proc_date
        ON {Config.PROCESSED_FILLS_TABLE} (order_as_of_date)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_proc_orderid
        ON {Config.PROCESSED_FILLS_TABLE} (OrderId)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_proc_routeid
        ON {Config.PROCESSED_FILLS_TABLE} (RouteId)
    """)
    _migrate_processed_fills_add_fx_rate(conn)

    # ── route_registry ──
    route_reg_cols = _build_column_defs(ROUTE_REGISTRY_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS route_registry (
            {route_reg_cols},
            PRIMARY KEY (OrderId, RouteId)
        )
    """)

    # ── order_history (PR-1: VIEW over route_history) ──
    # 不再创建物理表，order_history 是 route_history 的 GROUP BY 派生视图
    # 实际视图 DDL 引用 route_history 的列；inline 创建时依赖 route_history 已存在
    route_history_cols_inline = _build_column_defs(ROUTE_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.ROUTE_HISTORY_TABLE} (
            {route_history_cols_inline},
            PRIMARY KEY (OrderId, RouteId, order_as_of_date)
        )
    """)
    # order_history 视图（若 route_history 已存在则创建）
    conn.execute(f"""
        CREATE VIEW IF NOT EXISTS {Config.ORDER_HISTORY_TABLE} AS
            SELECT
                OrderId,
                order_as_of_date,
                MAX(equ_ticker)                       AS equ_ticker,
                MAX(ccy_ticker)                       AS ccy_ticker,
                MAX(Side)                             AS Side,
                MAX(Broker)                           AS Broker,
                MAX(algo)                             AS algo,
                MAX(TraderName)                       AS TraderName,
                MAX(Exchange)                         AS Exchange,
                COUNT(DISTINCT RouteId)               AS route_count,
                SUM(fill_count)                       AS fill_count,
                SUM(total_fill_shares)                AS total_fill_shares,
                MAX(order_amount)                     AS order_amount,
                CASE
                    WHEN SUM(COALESCE(total_fill_shares, 0)) = 0 THEN NULL
                    ELSE SUM(COALESCE(average_fill_price, 0) * COALESCE(total_fill_shares, 0))
                         / SUM(COALESCE(total_fill_shares, 0))
                END                                   AS average_fill_price,
                MIN(first_fill_time)                  AS first_fill_time,
                MAX(last_fill_time)                   AS last_fill_time,
                MAX(primary_source)                   AS primary_source,
                MAX(source_priority)                  AS source_priority,
                MAX(refresh_strategy)                 AS refresh_strategy,
                MAX(source_refreshed_at)              AS source_refreshed_at,
                MAX(source_lineage)                   AS source_lineage
            FROM {Config.ROUTE_HISTORY_TABLE}
            GROUP BY OrderId, order_as_of_date
    """)

    # ── route_history ──
    # PR-1: route_history 表已在上方 order_history 视图创建前置保证（避免 VIEW 引用未建表错误）
    route_history_cols = _build_column_defs(ROUTE_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.ROUTE_HISTORY_TABLE} (
            {route_history_cols},
            PRIMARY KEY (OrderId, RouteId, order_as_of_date)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_route_history_date
        ON {Config.ROUTE_HISTORY_TABLE} (order_as_of_date)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_route_history_ticker
        ON {Config.ROUTE_HISTORY_TABLE} (equ_ticker)
    """)

    # ── route_event_history ──
    route_event_history_cols = _build_column_defs(ROUTE_EVENT_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.ROUTE_EVENT_HISTORY_TABLE} (
            {route_event_history_cols},
            PRIMARY KEY (event_id)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_route_event_history_date
        ON {Config.ROUTE_EVENT_HISTORY_TABLE} (order_as_of_date)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_route_event_history_route
        ON {Config.ROUTE_EVENT_HISTORY_TABLE} (OrderId, RouteId)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_route_event_history_timestamp
        ON {Config.ROUTE_EVENT_HISTORY_TABLE} (event_timestamp)
    """)

    # ── processing_log ──
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.PROCESSING_LOG_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_as_of_date TEXT NOT NULL,
            processing_timestamp TEXT DEFAULT (datetime('now')),
            row_count INTEGER,
            stage TEXT DEFAULT 'processed',
            UNIQUE(order_as_of_date, stage)
        )
    """)

    # ── ticker_date_mapping ──
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.TICKER_DATE_MAPPING_TABLE} (
            ticker TEXT NOT NULL,
            ticker_type TEXT NOT NULL,
            order_as_of_date TEXT NOT NULL,
            PRIMARY KEY (ticker, ticker_type, order_as_of_date)
        )
    """)

    # ── order_label ──
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.ORDER_LABEL_TABLE} (
            OrderId TEXT PRIMARY KEY,
            order_as_of_date TEXT,
            equ_ticker TEXT
        )
    """)

    # ── ticker_repository ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticker_repository (
            equ_ticker TEXT PRIMARY KEY,
            exchange   TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── equ_ticker_registry ──
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.EQU_TICKER_REGISTRY_TABLE} (
            equ_ticker      TEXT PRIMARY KEY,
            first_seen_date TEXT,
            last_seen_date  TEXT,
            order_count     INTEGER DEFAULT 0
        )
    """)

    # ── ccy_ticker_registry ──
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.CCY_TICKER_REGISTRY_TABLE} (
            ccy_ticker      TEXT PRIMARY KEY,
            first_seen_date TEXT,
            last_seen_date  TEXT,
            order_count     INTEGER DEFAULT 0
        )
    """)

    # ── agg_fills_10s ──
    agg_cols = _build_column_defs(AGG_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.AGG_10S_TABLE} (
            {agg_cols},
            PRIMARY KEY (OrderId, RouteId, mkt_timestamp, order_as_of_date)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_agg_10s_date
        ON {Config.AGG_10S_TABLE} (order_as_of_date)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_agg_10s_order_route
        ON {Config.AGG_10S_TABLE} (OrderId, RouteId)
    """)

    # ── agg_fills_1min ──
    agg_1min_cols = _build_column_defs(AGG_1MIN_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.AGG_1MIN_TABLE} (
            {agg_1min_cols},
            PRIMARY KEY (OrderId, RouteId, mkt_timestamp_1min, order_as_of_date)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_agg_1min_date
        ON {Config.AGG_1MIN_TABLE} (order_as_of_date)
    """)

    # ── Legacy tables ──
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.AGG_PROCESSED_FILLS_TABLE} (
            OrderId TEXT NOT NULL,
            mkt_timestamp TEXT NOT NULL,
            order_as_of_date TEXT,
            PRIMARY KEY (OrderId, mkt_timestamp, order_as_of_date)
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.PROCESSED_FILLS_1MIN_TABLE} (
            OrderId TEXT NOT NULL,
            mkt_timestamp_1min TEXT NOT NULL,
            order_as_of_date TEXT,
            PRIMARY KEY (OrderId, mkt_timestamp_1min, order_as_of_date)
        )
    """)

    conn.commit()
    logger.debug("processed_fills.db schema ensured (inline DDL)")
